"""Adds agent endpoints + /chat/agent/stream. Existing endpoints are untouched.

server.py needs just two lines before `if __name__ == "__main__":`
    import agents_api, sys
    agents_api.install(app, sys.modules[__name__])
"""
import asyncio
import json
import threading
import time
from collections import deque
from contextlib import closing
from typing import Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import Cancelled, build_system, decide, format_for_main, mem_info


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def install(app, srv):
    registry, pipeline, memory = build_system(srv.MODEL_MANAGER)
    traces = deque(maxlen=20)

    class AgentChatRequest(srv.ChatRequest):
        agents: str = "auto"          # auto | on | off

    class EnableReq(BaseModel):
        enabled: bool

    class RerankReq(BaseModel):
        query: str
        documents: List[str]

    class EmbedReq(BaseModel):
        texts: List[str]
        is_query: bool = False

    class MemDoc(BaseModel):
        text: str
        source: str = ""

    class MemAddReq(BaseModel):
        documents: List[MemDoc]

    class MemSearchReq(BaseModel):
        query: str
        k: int = 4

    class ResearchReq(BaseModel):
        question: str

    def on_worker(fn):
        return asyncio.wrap_future(srv.submit(fn))

    def embed_fn(texts, is_query):
        r = registry.run("embedding", "embed", {"texts": texts, "is_query": is_query})
        if not r["ok"]:
            raise RuntimeError(r["error"])
        return r["result"]["embeddings"]

    def agent_or_404(agent_id):
        try:
            return registry.get(agent_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")

    def main_generate(system: str, user: str, max_tokens: int) -> str:
        """Short greedy generation on the main model; no shared KV cache involved."""
        if srv.active_model in (None, "stablecode"):
            return ""
        model, tokenizer = srv.chat_runtime()
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        ids = tokenizer.encode(srv.render_prompt(tokenizer, msgs, False),
                                   add_special_tokens=False)
        out = ""
        for r in srv.stream_generate(model, tokenizer, prompt=ids, max_tokens=max_tokens,
                                     sampler=srv.make_sampler(temp=0.0)):
            out += r.text
        return out

    def run_exclusive(fn):
        previous_model = srv.active_model
        try:
            return fn()
        finally:
            registry.release_all()
            if previous_model:
                srv.load_model(previous_model)

    def run_research_exclusive(question, emit=None, cancelled=None):
        previous_model = srv.active_model
        if previous_model:
            srv.MODEL_MANAGER.release(f"chat:{previous_model}")
        try:
            return pipeline.run(question, emit=emit, cancelled=cancelled)
        finally:
            registry.release_all()
            srv.clear_mx_cache()
            if previous_model:
                srv.load_model(previous_model)

    # ---- inspection / control --------------------------------------------
    @app.get("/agents")
    def list_agents():
        return {"agents": registry.list(), "max_resident": registry.max_resident}

    @app.get("/agents/status")
    def agents_status():
        return {"main_model": srv.active_model, "main_status": srv.model_status,
                "search_tool": pipeline.search.name, "memory_items": memory.count(),
                "resident": [a.id for a in registry.resident()], "memory": mem_info(),
                "agents": registry.list()}

    @app.get("/agents/trace")
    def agents_trace():
        return {"traces": list(traces)}

    @app.get("/agents/{agent_id}")
    def agent_info(agent_id: str):
        return agent_or_404(agent_id).describe()

    @app.post("/agents/{agent_id}/enabled")
    async def set_enabled(agent_id: str, req: EnableReq):
        agent = agent_or_404(agent_id)
        agent.enabled = req.enabled
        if not req.enabled and agent.loaded:
            await on_worker(lambda: run_exclusive(agent.unload))
        return agent.describe()

    @app.post("/agents/{agent_id}/load")
    async def load_agent(agent_id: str):
        agent = agent_or_404(agent_id)
        r = await on_worker(lambda: run_exclusive(lambda: _load(agent)))
        return {"agent": agent.describe(), "result": r}

    def _load(agent):
        if not agent.enabled:
            return {"ok": False, "error": "disabled"}
        try:
            while len(registry.resident()) >= registry.max_resident and not agent.loaded:
                min(registry.resident(), key=lambda a: a.last_used).unload()
            agent.load()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/agents/{agent_id}/unload")
    async def unload_agent(agent_id: str):
        agent = agent_or_404(agent_id)
        await on_worker(lambda: run_exclusive(agent.unload))
        return agent.describe()

    # ---- direct specialist access (for testing) ----------------------------
    @app.post("/agents/reranker/score")
    async def rerank(req: RerankReq):
        r = await on_worker(lambda: run_exclusive(lambda: registry.run(
            "reranker", "score", {"query": req.query, "documents": req.documents})))
        if not r["ok"]:
            raise HTTPException(status_code=503, detail=r["error"])
        return r

    @app.post("/agents/embedding/embed")
    async def embed(req: EmbedReq):
        r = await on_worker(lambda: run_exclusive(lambda: registry.run(
            "embedding", "embed", {"texts": req.texts, "is_query": req.is_query})))
        if not r["ok"]:
            raise HTTPException(status_code=503, detail=r["error"])
        r["result"]["embeddings"] = [[round(x, 5) for x in v] for v in r["result"]["embeddings"]]
        return r

    @app.post("/agents/memory/add")
    async def memory_add(req: MemAddReq):
        n = await on_worker(lambda: run_exclusive(
            lambda: memory.add([d.model_dump() for d in req.documents], embed_fn)))
        return {"added": n, "total": memory.count()}

    @app.post("/agents/memory/search")
    async def memory_search(req: MemSearchReq):
        hits = await on_worker(lambda: run_exclusive(
            lambda: memory.search(req.query, req.k, embed_fn)))
        return {"hits": hits}

    @app.post("/agents/research")
    async def research(req: ResearchReq):
        def job():
            rep = run_research_exclusive(req.question)
            traces.append({"at": time.time(), "question": req.question, "report": rep})
            return rep
        return await on_worker(job)

    # ---- chat with orchestration -------------------------------------------
    @app.post("/chat/agent/stream")
    async def chat_agent_stream(req: AgentChatRequest):
        srv.validate(req)
        loop = asyncio.get_running_loop()

        async def events():
            q: asyncio.Queue = asyncio.Queue()
            cancel = threading.Event()

            def push(item):
                loop.call_soon_threadsafe(q.put_nowait, item)

            def job():
                try:
                    if cancel.is_set():
                        return
                    started = time.perf_counter()
                    if srv.active_model is None or not srv.MODEL_MANAGER.is_active(
                        f"chat:{srv.active_model}"
                    ):
                        raise HTTPException(status_code=503, detail="No model is loaded.")
                    srv.mx.reset_peak_memory()
                    last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
                    question = last_user.content if last_user else ""
                    final = req
                    agent_info = {"used": False}

                    d = decide(question, req.agents, main_generate)
                    push(_sse({"agent": {"stage": "decision", **d}}))
                    if d["research"]:
                        rep = run_research_exclusive(
                            question,
                            emit=lambda e: push(_sse({"agent": e})),
                            cancelled=cancel.is_set,
                        )
                        traces.append({"at": time.time(), "question": question, "decision": d, "report": rep})
                        notes = format_for_main(rep)
                        msgs = list(req.messages)
                        idx = max(i for i, m in enumerate(msgs) if m.role == "user")
                        msgs[idx] = srv.Message(role="user",
                                                content=f"{notes}\n\nUser question:\n{msgs[idx].content}")
                        final = req.model_copy(update={"messages": msgs})
                        agent_info = {"used": True, "timings": rep["timings"],
                                      "searched": rep["searched"], "facts": len(rep["facts"])}
                    agent_time = time.perf_counter() - started

                    t1 = time.perf_counter()
                    first, last, prompt_len = None, None, 0
                    with closing(srv.token_stream(final)) as gen:
                        for prompt_len, response in gen:
                            if cancel.is_set():
                                break
                            if first is None:
                                first = time.perf_counter() - t1
                            last = response
                            if response.text:
                                push(_sse({"delta": response.text}))
                    if not cancel.is_set():
                        push(_sse({
                            "done": True,
                            "tokens": last.generation_tokens if last else 0,
                            "prompt_tokens": prompt_len,
                            "time_sec": round(time.perf_counter() - started, 2),
                            "first_token_sec": round(first or 0.0, 3),
                            "tokens_per_sec": round(last.generation_tps, 1) if last else 0,
                            "model": srv.MODELS[srv.active_model]["name"],
                            "context_limit": srv.MAX_CONTEXT_TOKENS,
                            "agents": {**agent_info, "agent_time_sec": round(agent_time, 2)},
                        }))
                except Cancelled:
                    registry.release_all()
                except HTTPException as exc:
                    push(_sse({"error": exc.detail, "status": exc.status_code}))
                except Exception as exc:
                    registry.release_all()
                    push(_sse({"error": f"Generation failed: {exc}", "status": 500}))
                finally:
                    push(None)

            srv.submit(job)
            try:
                while True:
                    item = await q.get()
                    if item is None:
                        break
                    chunk, done = [item], False
                    while True:
                        try:
                            nxt = q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        if nxt is None:
                            done = True
                            break
                        chunk.append(nxt)
                    yield "".join(chunk)
                    if done:
                        break
            finally:
                cancel.set()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
