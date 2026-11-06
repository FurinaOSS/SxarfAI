"""Research pipeline + routing decision. Qwen3-4B stays the main model; this
module only coordinates specialists and returns a structured report."""
import json
import re
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from .base import mem_info

RESEARCH_HINT = re.compile(
    r"\b(research|look ?up|find out|docs?|documentation|official|latest|current|"
    r"recent|today|news|release|version|api|library|package|rfc|spec(?:ification)?|"
    r"how (?:does|do|is) .{2,60} work|which (?:function|method|class)|compare|"
    r"what (?:is|are|changed|happened)|who is|when (?:did|was|is)|where is|"
    r"why (?:is|are|did|does)|who (?:founded|created|built|started)|"
    r"founder|creator|history of|secure|security|source|cite)\b", re.I)

OFFICIAL = ("python.org", "readthedocs.io", "readthedocs.org", "mozilla.org", "cryptography.io",
            "w3.org", "ietf.org", "rfc-editor.org", "nodejs.org", "rust-lang.org", "go.dev",
            "postgresql.org", "sqlite.org", "developer.apple.com", "ml-explore.github.io",
            "kernel.org", "gnu.org", "developer.android.com", "docs.rs")

MIN_SOURCE_SCORE = 0.25
MIN_PASSAGE_SCORE = 0.35


class Cancelled(Exception):
    pass


def is_official(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host.startswith("docs.") or any(host == d or host.endswith("." + d) for d in OFFICIAL)


def chunk_text(text: str, size: int = 700, max_chunks: int = 12) -> List[str]:
    out, cur = [], ""
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:
            cut = para.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 3 else size
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if len(cur) + len(para) + 1 > size and cur:
            out.append(cur)
            cur = ""
        cur = (cur + " " + para).strip()
    if cur:
        out.append(cur)
    return [c for c in out if len(c) > 60][:max_chunks]


def parse_json_obj(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def decide(question: str, mode: str, main_generate: Optional[Callable[[str, str, int], str]]) -> Dict[str, Any]:
    """Route by local heuristics so research never needs an extra model generation."""
    if mode == "off":
        return {"research": False, "reason": "agents disabled for this request", "by": "request"}
    if mode == "on":
        return {"research": True, "topic": question[:120], "reason": "forced on", "by": "request"}
    matched = bool(RESEARCH_HINT.search(question))
    return {
        "research": matched,
        "topic": question[:120],
        "reason": "research keywords detected" if matched else "ordinary question; answered directly",
        "by": "heuristic",
    }


class ResearchPipeline:
    def __init__(self, registry, search, fetcher, memory=None):
        self.registry, self.search, self.fetcher, self.memory = registry, search, fetcher, memory

    def run(self, question: str, emit=None, cancelled=None) -> Dict[str, Any]:
        emit = emit or (lambda e: None)
        cancelled = cancelled or (lambda: False)
        rep: Dict[str, Any] = {
            "question": question, "searched": False, "search_tool": self.search.name,
            "queries": [], "sources": [], "facts": [], "gaps": [], "search_errors": [],
            "agent_runs": [], "timings": {}, "conflict_check": "not performed by the researcher; main model must cross-check",
        }

        @contextmanager
        def stage(name):
            if cancelled():
                raise Cancelled()
            emit({"stage": name, "status": "start"})
            t = time.perf_counter()
            try:
                yield
            finally:
                dt = round(time.perf_counter() - t, 3)
                rep["timings"][name] = dt
                emit({"stage": name, "status": "done", "time_sec": dt, "memory": mem_info()})

        def call(agent_id, task, payload):
            r = self.registry.run(agent_id, task, payload)
            rep["agent_runs"].append({k: r[k] for k in ("agent", "task", "ok", "error", "time_sec", "load_time_sec")})
            if not r["ok"]:
                rep["gaps"].append(f"{agent_id} unavailable ({r['error']})")
            return r["result"] if r["ok"] else None

        def embed(texts, is_query):
            res = call("embedding", "embed", {"texts": texts, "is_query": is_query})
            if res is None:
                raise RuntimeError("embedding agent unavailable")
            return res["embeddings"]

        # 1. queries
        with stage("queries"):
            from .researcher import fallback_queries
            planned = [question.strip()[:120], *fallback_queries(question)[1:]]
            rep["queries"] = list(dict.fromkeys(q for q in planned if q))[:4]

        # 2. search
        cands: List[Dict[str, Any]] = []
        with stage("search"):
            if not self.search.available():
                rep["gaps"].append("No web search tool is configured; nothing was searched online.")
            else:
                seen = set()
                for q in rep["queries"][:3]:
                    if cancelled():
                        raise Cancelled()
                    try:
                        results = self.search.search(q, 5)
                        if results:
                            rep["searched"] = True
                        for it in results:
                            if it["url"] not in seen:
                                seen.add(it["url"])
                                cands.append(it)
                    except Exception as exc:
                        error = f"{q!r}: {type(exc).__name__}: {exc}"
                        rep["search_errors"].append(error)
                        rep["gaps"].append(f"Search failed for {q!r}: {type(exc).__name__}: {exc}")
                if not rep["searched"]:
                    rep["gaps"].append("Web search returned no results; no online evidence was retrieved.")

        # 3. rank sources
        with stage("rank_sources"):
            if cands:
                res = call("reranker", "score", {"query": question,
                           "documents": [f"{c['title']}\n{c['snippet']}" for c in cands]})
                for i, c in enumerate(cands):
                    c["score"] = res["scores"][i] if res else None
                    c["official"] = is_official(c["url"])
                if res:
                    cands.sort(key=lambda c: c["score"] + (0.1 if c["official"] else 0), reverse=True)
                    above_threshold = [c for c in cands if c["score"] >= MIN_SOURCE_SCORE]
                    cands = above_threshold or cands[:3]
                else:
                    rep["gaps"].append("Sources are in search-engine order (no relevance scoring).")
                cands = cands[:3]
                rep["sources"] = [{k: c[k] for k in ("url", "title", "score", "official")} for c in cands]

        # 4. fetch + chunk (+ stored memory)
        passages: List[Dict[str, Any]] = []
        with stage("fetch"):
            for c in cands:
                if cancelled():
                    raise Cancelled()
                try:
                    for ch in chunk_text(self.fetcher.fetch(c["url"])):
                        passages.append({"text": ch, "url": c["url"], "title": c["title"], "origin": "web"})
                except Exception as exc:
                    rep["gaps"].append(f"Could not fetch {c['url']}: {type(exc).__name__}")
                    if c.get("snippet"):
                        passages.append({"text": c["snippet"], "url": c["url"], "title": c["title"], "origin": "snippet"})
            if self.memory is not None and self.memory.count() and self.registry.get("embedding").enabled:
                try:
                    for h in self.memory.search(question, 4, embed):
                        passages.append({"text": h["text"], "url": h["source"] or None,
                                         "title": "stored knowledge", "origin": "memory"})
                except Exception as exc:
                    rep["gaps"].append(f"Memory search failed: {exc}")

        # 5. rank passages
        with stage("rank_passages"):
            if passages:
                passages = passages[:40]
                res = call("reranker", "score", {"query": question, "documents": [p["text"] for p in passages]})
                if res:
                    for p, s in zip(passages, res["scores"]):
                        p["score"] = s
                    ranked = sorted(passages, key=lambda p: p["score"], reverse=True)
                    above_threshold = [p for p in ranked if p["score"] >= MIN_PASSAGE_SCORE]
                    passages = above_threshold or ranked[:4]
                passages = passages[:4]

        # 6. extract verbatim evidence deterministically; the main model synthesizes it.
        with stage("extract"):
            if passages:
                from .researcher import relevant_quotes
                for passage in passages:
                    for quote in relevant_quotes(question, passage["text"]):
                        rep["facts"].append({
                            "fact": quote, "source_url": passage.get("url"),
                            "title": passage.get("title"), "origin": passage.get("origin", "web"),
                            "rerank_score": passage.get("score"), "verified": True,
                        })
            if not rep["facts"]:
                rep["gaps"].append("No verifiable evidence was extracted.")
            urls = {f["source_url"] for f in rep["facts"] if f["source_url"]}
            if rep["facts"] and len(urls) < 2:
                rep["gaps"].append("Evidence comes from fewer than 2 distinct sources.")
            if rep["facts"] and not any(is_official(u) for u in urls):
                rep["gaps"].append("No official documentation among the evidence.")

        self.registry.release_all()
        return rep


def format_for_main(rep: Dict[str, Any]) -> str:
    lines = ["[RESEARCH REPORT - produced by Sxarf specialist agents]",
             f"Web search performed: {'yes (' + rep['search_tool'] + ')' if rep['searched'] else 'NO'}"]
    if rep["facts"]:
        lines.append("Verified excerpts (exact text from sources):")
        for i, f in enumerate(rep["facts"], 1):
            lines.append(f'{i}. "{f["fact"]}" - {f["source_url"] or f["origin"]}')
    elif rep["sources"]:
        lines.append("Retrieved sources (page contents could not be verified):")
        for source in rep["sources"]:
            lines.append(f'- {source["title"]}: {source["url"]}')
    if rep["gaps"]:
        lines.append("Gaps / uncertainty:")
        lines += [f"- {g}" for g in rep["gaps"]]
    lines.append("Rules: rely on these excerpts for factual claims, cite their URLs, and say "
                 "plainly where the report is missing or insufficient. Do not invent sources.")
    return "\n".join(lines)
