#!/usr/bin/env python3
"""Local multi-model MLX chat server for Apple Silicon (max-speed build).

Speed features:
  * One dedicated worker thread owns the model, the GPU stream and the KV
    cache. Loading and every generation run on it, so there is no lock
    contention, no per-token thread hopping, and no thread-local stream issues.
  * /chat/stream: tokens are pushed to the event loop and coalesced, so each
    network write carries every token produced since the last write.
  * KV prompt-cache reuse, now including generated tokens (multi-turn chats
    re-prefill almost nothing).
  * Client disconnect cancels generation immediately (frees the GPU).
  * top_p sorting is skipped when top_p >= 1.0.
  * SmolLM3 thinking disabled by default; can be enabled per request.
  * Metal wired-memory limit, realistic kernel warmup, GC frozen after load.
  * uvloop + httptools are used automatically when installed.
  * /chat keeps the existing request/response schema.
  * Specialist agents (researcher / reranker / embedding / code) are added by
    agents_api.install() at the bottom; all original endpoints are unchanged.
"""

import argparse
import asyncio
import gc
import json
import os
import queue
import re
import threading
import time
import subprocess
import sys
import tempfile
from pathlib import Path
from io import BytesIO
from concurrent.futures import Future
from contextlib import asynccontextmanager, closing
from typing import List

import mlx.core as mx
from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from PIL import Image
import psutil
import uvicorn

from mlx_lm import load, stream_generate
from mlx_lm.models.cache import (
    can_trim_prompt_cache,
    make_prompt_cache,
    trim_prompt_cache,
)
from mlx_lm.sample_utils import make_sampler
from model_manager import MODEL_MANAGER

MODELS = {
    "smollm2": {
        "name": "SmolLM2-1.7B",
        "repo": "mlx-community/SmolLM2-1.7B-Instruct",
    },
    "smollm3": {
        "name": "SmolLM3-3B",
        "repo": "mlx-community/SmolLM3-3B-4bit",
    },
    "llama32": {
        "name": "Llama-3.2-3B",
        "repo": "mlx-community/Llama-3.2-3B-Instruct-4bit",
    },
    "lfm25": {
        "name": "LFM2.5-2.6B",
        "repo": "mlx-community/LFM2.5-2.6B-4bit",
    },
    "gemma2": {
        "name": "Gemma-2-2B",
        "repo": "mlx-community/gemma-2-2b-it-4bit",
    },
    "phi35": {
        "name": "Phi-3.5-mini",
        "repo": "mlx-community/Phi-3.5-mini-instruct-4bit",
    },
    "stablecode": {
        "name": "Stable Code 3B · Coding",
        "repo": "mlx-community/stable-code-3b-4bit",
    },
}

# Old ids that may still be saved or set in the environment.
MODEL_ALIASES = {"qwen3": "llama32"}

_requested_default = os.getenv("DEFAULT_MODEL", "smollm2")
DEFAULT_MODEL = MODEL_ALIASES.get(_requested_default, _requested_default)
MAX_CONTEXT_TOKENS = max(1024, min(int(os.getenv("MAX_CONTEXT_TOKENS", "8192")), 8192))
MAX_GENERATION_TOKENS = max(256, min(int(os.getenv("MAX_GENERATION_TOKENS", "4096")), 4096))
MAX_SYSTEM_PROMPT_CHARS = max(
    1024, min(int(os.getenv("MAX_SYSTEM_PROMPT_CHARS", "8192")), 8192)
)
PREFILL_STEP = int(os.getenv("PREFILL_STEP", "2048"))
KV_BITS = int(os.getenv("KV_BITS", "4"))
KV_QUANTIZED_START = int(os.getenv("KV_QUANTIZED_START", "1024"))

active_model = None
model_status = "starting"
model_error = None

# KV prompt cache. cached_tokens are the token IDs (prompt + generated)
# represented by the cache contents.
prompt_cache = None
cached_tokens: List[int] = []


# --------------------------------------------------------------------------
# Single worker thread (owns model, cache, GPU stream)
# --------------------------------------------------------------------------

_jobs: "queue.SimpleQueue" = queue.SimpleQueue()
_worker_thread = None


def _worker_loop():
    while True:
        item = _jobs.get()
        if item is None:
            return
        fn, fut = item
        if not fut.set_running_or_notify_cancel():
            continue
        try:
            fut.set_result(fn())
        except BaseException as exc:  # noqa: BLE001
            fut.set_exception(exc)


def submit(fn) -> Future:
    fut: Future = Future()
    _jobs.put((fn, fut))
    return fut


def start_worker():
    global _worker_thread
    if _worker_thread is None:
        _worker_thread = threading.Thread(
            target=_worker_loop, name="mlx-worker", daemon=True
        )
        _worker_thread.start()


# --------------------------------------------------------------------------
# Memory / cache helpers
# --------------------------------------------------------------------------

def tune_metal():
    memory_limit = int(max(0.5, min(float(os.getenv("MLX_MEMORY_LIMIT_GB", "2.5")),
                                    2.5)) * 1024**3)
    cache_limit = int(max(0.05, min(float(os.getenv("MLX_CACHE_LIMIT_GB", "0.25")),
                                    0.25)) * 1024**3)
    for name, value in (("set_memory_limit", memory_limit),
                        ("set_cache_limit", cache_limit)):
        setter = getattr(mx, name, None)
        if setter is None:
            raise RuntimeError(f"Installed MLX does not provide mx.{name}().")
        setter(value)
    print(
        f"[MLX] Allocation limits: active={memory_limit / 1024**3:.2f} GiB, "
        f"cache={cache_limit / 1024**3:.2f} GiB",
        flush=True,
    )
    try:
        try:
            info = mx.device_info()
        except AttributeError:
            info = mx.metal.device_info()
        limit = info.get("max_recommended_working_set_size")
        if limit:
            mx.set_wired_limit(min(limit, memory_limit + cache_limit))
    except Exception as exc:
        print(f"[MLX] Wired limit not set: {exc}", flush=True)


def clear_mx_cache():
    try:
        mx.clear_cache()
    except Exception:
        try:
            mx.metal.clear_cache()
        except Exception:
            pass


def reset_prompt_cache():
    global prompt_cache, cached_tokens
    prompt_cache = None
    cached_tokens = []


def clear_chat_cache_on_release(key):
    if key and key.startswith("chat:"):
        reset_prompt_cache()


MODEL_MANAGER.on_release = clear_chat_cache_on_release
MODEL_MANAGER.clear_cache = mx.clear_cache


def chat_runtime():
    if active_model is None:
        raise RuntimeError("No chat model is selected.")
    return MODEL_MANAGER.get(f"chat:{active_model}")


def cache_offset():
    try:
        return int(prompt_cache[0].offset)
    except Exception:
        return 0


def prepare_cache(tokens: List[int]):
    """Return a compatible cache and only the prompt tokens not yet cached."""
    global prompt_cache, cached_tokens
    active_model_instance, _ = chat_runtime()

    if prompt_cache is None or not can_trim_prompt_cache(prompt_cache):
        prompt_cache = make_prompt_cache(active_model_instance)
        cached_tokens = []

    # Always leave at least one token to feed.
    limit = min(len(cached_tokens), max(0, len(tokens) - 1))
    common = 0
    ct = cached_tokens
    while common < limit and ct[common] == tokens[common]:
        common += 1

    offset = cache_offset()
    if offset > common:
        try:
            trim_prompt_cache(prompt_cache, offset - common)
        except Exception:
            prompt_cache = make_prompt_cache(active_model_instance)
            common = 0
    elif offset < common:
        prompt_cache = make_prompt_cache(active_model_instance)
        common = 0

    cached_tokens = tokens[:common]
    return prompt_cache, tokens[common:]


# --------------------------------------------------------------------------
# Model loading (runs on the worker thread)
# --------------------------------------------------------------------------

def warmup(model_instance, tokenizer_instance):
    """Warm prefill + decode kernels with a realistic-length prompt."""
    try:
        cache = make_prompt_cache(model_instance)
        ids = tokenizer_instance.encode("Hello world, this is a warmup. " * 8,
                                       add_special_tokens=False) or [0]
        for _ in stream_generate(
            model_instance, tokenizer_instance, prompt=ids, max_tokens=8,
            prompt_cache=cache, kv_bits=KV_BITS,
            quantized_kv_start=KV_QUANTIZED_START,
        ):
            pass
        mx.eval(model_instance.parameters())
    except Exception as exc:
        print(f"[MLX] Warmup skipped: {exc}", flush=True)


def load_model(model_key: str):
    global active_model, model_status, model_error

    if model_key not in MODELS:
        raise ValueError(f"Unknown model: {model_key}")
    model_key_for_manager = f"chat:{model_key}"
    if active_model == model_key and MODEL_MANAGER.is_active(model_key_for_manager):
        model_status = "ready"
        return

    config = MODELS[model_key]
    model_status = "loading"
    model_error = None
    print(f"\n[MLX] Loading {config['name']} ({config['repo']})", flush=True)

    gc.unfreeze()
    gc.collect()
    clear_mx_cache()

    try:
        new_model, new_tokenizer = MODEL_MANAGER.activate(
            model_key_for_manager, lambda: load(config["repo"])
        )
        active_model = model_key
        warmup(new_model, new_tokenizer)
        gc.collect()
        gc.freeze()  # long-lived weights never need GC scanning
        model_status = "ready"
        print(f"[MLX] Ready: {config['name']}", flush=True)
    except Exception as exc:
        model_status = "error"
        model_error = str(exc)
        gc.collect()
        clear_mx_cache()
        raise


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if DEFAULT_MODEL not in MODELS:
        raise RuntimeError(
            f"DEFAULT_MODEL '{DEFAULT_MODEL}' is not in the model registry."
        )
    # Fewer GC pauses while generating.
    gc.set_threshold(100_000, 50, 50)
    start_worker()
    submit(tune_metal).result()
    await asyncio.wrap_future(submit(lambda: load_model(DEFAULT_MODEL)))
    yield
    _jobs.put(None)


app = FastAPI(
    title="Local Multi-Model MLX Server",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    max_tokens: int = Field(
        default=MAX_GENERATION_TOKENS, ge=1, le=MAX_GENERATION_TOKENS
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, gt=0.0, le=1.0)
    thinking: bool = False


class ModelRequest(BaseModel):
    model: str


class ChatResponse(BaseModel):
    content: str
    tokens: int
    prompt_tokens: int
    time_sec: float
    model: str
    context_limit: int


@app.get("/health")
def health():
    return {
        "status": model_status,
        "model": MODELS[active_model]["name"] if active_model else None,
        "model_id": active_model,
        "repo": MODELS[active_model]["repo"] if active_model else None,
        "error": model_error,
        "context_limit": MAX_CONTEXT_TOKENS,
    }


@app.get("/models")
def get_models():
    return {
        "models": [
            {"id": key, "name": value["name"], "repo": value["repo"]}
            for key, value in MODELS.items()
        ],
        "active": active_model,
        "status": model_status,
    }


@app.post("/select-model")
async def select_model(req: ModelRequest):
    req.model = MODEL_ALIASES.get(req.model, req.model)
    if req.model not in MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {req.model}")
    try:
        await asyncio.wrap_future(submit(lambda: load_model(req.model)))
        return {
            "success": True,
            "active": active_model,
            "name": MODELS[active_model]["name"],
        }
    except Exception as exc:
        print(f"[MLX] Model loading error: {exc}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Could not load {MODELS[req.model]['name']}: {exc}",
        )


# --------------------------------------------------------------------------
# Prompt building
# --------------------------------------------------------------------------

_LANGUAGE_PATTERNS = [
    ("Python", re.compile(r"\bpython\b|\.py\b", re.IGNORECASE)),
    ("JavaScript", re.compile(r"\bjavascript\b|\bjs\b|\.js\b", re.IGNORECASE)),
    ("TypeScript", re.compile(r"\btypescript\b|\bts\b|\.ts\b", re.IGNORECASE)),
    ("Lua", re.compile(r"\blua\b|\.lua\b", re.IGNORECASE)),
    ("HTML", re.compile(r"\bhtml\b|\.html?\b", re.IGNORECASE)),
    ("CSS", re.compile(r"\bcss\b|\.css\b", re.IGNORECASE)),
    ("Java", re.compile(r"\bjava\b|\.java\b", re.IGNORECASE)),
    ("C++", re.compile(r"\bc\+\+\b|\bcpp\b|\.cpp\b|\.hpp\b", re.IGNORECASE)),
    ("C#", re.compile(r"\bc#\b|\bcsharp\b|\.cs\b", re.IGNORECASE)),
    ("C", re.compile(r"\blanguage c\b|\bin c\b|\.c\b", re.IGNORECASE)),
    ("Rust", re.compile(r"\brust\b|\.rs\b", re.IGNORECASE)),
    ("Go", re.compile(r"\bgolang\b|\bin go\b|\.go\b", re.IGNORECASE)),
    ("SQL", re.compile(r"\bsql\b|\.sql\b", re.IGNORECASE)),
    ("PHP", re.compile(r"\bphp\b|\.php\b", re.IGNORECASE)),
    ("Ruby", re.compile(r"\bruby\b|\.rb\b", re.IGNORECASE)),
    ("Swift", re.compile(r"\bswift\b|\.swift\b", re.IGNORECASE)),
    ("Kotlin", re.compile(r"\bkotlin\b|\.kt\b", re.IGNORECASE)),
]

_CODE_HINT = re.compile(
    r"\b(def |class |function |const |let |var |import |from |return |local )"
)


def detect_code_language(request_text: str) -> str:
    for language, pattern in _LANGUAGE_PATTERNS:
        if pattern.search(request_text):
            return language
    return "Python"


def _latest_user_index(messages):
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "user":
            return index
    return None


def render_stable_code_prompt(messages):
    """Completion-style prompt for the base Stable Code model."""
    latest_index = _latest_user_index(messages)
    if latest_index is None:
        raise HTTPException(
            status_code=400,
            detail="Stable Code needs at least one user message.",
        )

    latest_request = messages[latest_index]["content"].strip()
    language = detect_code_language(latest_request)

    previous = messages[:latest_index]
    prior_user_requests = [
        item["content"].strip()
        for item in previous
        if item["role"] == "user" and item["content"].strip()
    ][-2:]
    prior_assistant_code = [
        item["content"].strip()
        for item in previous
        if item["role"] == "assistant"
        and item["content"].strip()
        and ("```" in item["content"] or _CODE_HINT.search(item["content"]))
    ][-1:]

    if language == "HTML":
        def comment(text):
            return f"<!-- {text} -->"
    else:
        comment_prefix = "#" if language == "Python" else "//"

        def comment(text):
            return f"{comment_prefix} {text}"

    lines = [comment(f"Language: {language}")]

    if prior_user_requests:
        lines.append(comment("Relevant earlier request(s):"))
        for request in prior_user_requests:
            lines.append(comment(" ".join(request.split())))

    if prior_assistant_code:
        lines.extend([
            comment("Existing implementation for context:"),
            prior_assistant_code[0],
            comment("End of existing implementation."),
        ])

    compact_request = "\n".join(
        comment(line) if line.strip() else comment("")
        for line in latest_request.splitlines()
    )
    lines.extend([
        comment("Task:"),
        compact_request,
        comment(f"Write a complete, runnable {language} implementation."),
        comment("If the request is vague, demonstrate with a small working example."),
        comment("Continue with implementation code; do not output links or unrelated text."),
        "",
    ])
    return "\n".join(lines)


# Remember whether a tokenizer's template accepts enable_thinking so we do not
# pay for a failed template render on every request.
_template_supports_thinking = {}


def render_prompt(tok, messages, thinking):
    if active_model == "stablecode":
        return render_stable_code_prompt(messages)

    # gemma2: its chat template rejects a system role; fold it into the first user turn.
    if active_model == "gemma2" and messages and messages[0]["role"] == "system":
        messages = [dict(m) for m in messages]
        system_text = messages.pop(0)["content"]
        for m in messages:
            if m["role"] == "user":
                m["content"] = system_text + "\n\n" + m["content"]
                break

    supports = _template_supports_thinking.get(active_model)
    if supports is not False:
        try:
            text = tok.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=thinking,
            )
            _template_supports_thinking[active_model] = True
            return text
        except Exception:
            if supports is True:
                raise
            _template_supports_thinking[active_model] = False

    try:
        return tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception as exc:
        raise RuntimeError(
            f"Chat template unavailable for {active_model}: {exc}"
        ) from exc


def coalesce_messages(messages):
    """Merge adjacent turns with the same role for templates that require alternation."""
    coalesced = []
    for message in messages:
        if coalesced and coalesced[-1]["role"] == message["role"]:
            coalesced[-1]["content"] += "\n\n" + message["content"]
        else:
            coalesced.append(dict(message))
    return coalesced


def build_prompt(tok, incoming_messages, max_new_tokens, thinking):
    """Return prompt token IDs, trimming oldest turns to fit the context."""
    messages = coalesce_messages([
        {"role": m.role, "content": m.content} for m in incoming_messages
    ])
    for message in messages:
        if message["role"] != "system" or len(message["content"]) <= MAX_SYSTEM_PROMPT_CHARS:
            continue
        content = message["content"]
        marker = "PROJECT FILES:"
        marker_index = content.find(marker)
        if marker_index >= 0:
            header_end = marker_index + len(marker)
            omitted = "\n[Oldest project files omitted to fit the local context budget]\n"
            tail_budget = max(0, MAX_SYSTEM_PROMPT_CHARS - header_end - len(omitted))
            message["content"] = content[:header_end] + omitted + (
                content[-tail_budget:] if tail_budget else ""
            )
        else:
            message["content"] = content[:MAX_SYSTEM_PROMPT_CHARS]

    allowed = MAX_CONTEXT_TOKENS - max_new_tokens
    if allowed < 1:
        raise HTTPException(
            status_code=400,
            detail="Generation limit leaves no room for the prompt.",
        )

    add_special = active_model == "stablecode"
    while True:
        prompt_text = render_prompt(tok, messages, thinking)
        tokens = tok.encode(prompt_text, add_special_tokens=add_special)
        if len(tokens) <= allowed:
            return tokens

        start = 1 if messages and messages[0]["role"] == "system" else 0
        latest_user = _latest_user_index(messages)

        if latest_user is None or len(messages) <= start + 1:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"This message is too long for the configured "
                    f"{MAX_CONTEXT_TOKENS}-token context window. "
                    "Shorten it or lower the response token limit."
                ),
            )
        if start == latest_user:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"The latest message is too long for the configured "
                    f"{MAX_CONTEXT_TOKENS}-token context window."
                ),
            )
        del messages[start]


def validate(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages cannot be empty.")
    allowed_roles = {"system", "user", "assistant"}
    if any(m.role not in allowed_roles for m in req.messages):
        raise HTTPException(
            status_code=400,
            detail="Only system, user, and assistant roles are supported.",
        )


# --------------------------------------------------------------------------
# Generation (worker thread only)
# --------------------------------------------------------------------------

_sampler_cache = {}


def kv_bits_for_model(model_key):
    # Gemma 2 attention expects array-valued KV entries; quantized caches store
    # packed values as lists, which mx.expand_dims cannot consume.
    return None if model_key == "gemma2" else KV_BITS


def get_sampler(temperature: float, top_p: float):
    key = (temperature, top_p)
    sampler = _sampler_cache.get(key)
    if sampler is None:
        if len(_sampler_cache) > 64:
            _sampler_cache.clear()
        # top_p=0.0 disables nucleus sorting entirely (a real per-token cost).
        sampler = make_sampler(
            temp=temperature, top_p=top_p if top_p < 1.0 else 0.0
        )
        _sampler_cache[key] = sampler
    return sampler


def token_stream(req: ChatRequest):
    """Generator; must run on the worker thread.

    Yields (prompt_length, MLX generation response) for each streamed chunk.
    """
    global cached_tokens

    if active_model is None:
        raise HTTPException(
            status_code=503,
            detail="No model is loaded. Select a model and try again.",
        )
    try:
        model, tokenizer = chat_runtime()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="The selected chat model is not resident. Try again shortly.",
        ) from exc
    prompt_ids = build_prompt(
        tokenizer, req.messages, req.max_tokens, req.thinking
    )
    cache, to_feed = prepare_cache(prompt_ids)
    sampler = get_sampler(req.temperature, req.top_p)

    generated: List[int] = []
    ok = False
    try:
        for response in stream_generate(
            model,
            tokenizer,
            prompt=to_feed,
            max_tokens=req.max_tokens,
            sampler=sampler,
            prompt_cache=cache,
            prefill_step_size=PREFILL_STEP,
            kv_bits=kv_bits_for_model(active_model),
            quantized_kv_start=KV_QUANTIZED_START,
        ):
            generated.append(response.token)
            yield len(prompt_ids), response
        ok = True
    except GeneratorExit:
        reset_prompt_cache()
        clear_mx_cache()
        raise
    except BaseException:
        reset_prompt_cache()
        raise
    finally:
        if ok and prompt_cache is not None:
            # Cache holds prompt + generated tokens (the last sampled token may
            # not have been fed). Record exactly what is inside it.
            full = prompt_ids + generated
            offset = cache_offset()
            valid = min(len(full), offset)
            if offset > valid:
                try:
                    trim_prompt_cache(prompt_cache, offset - valid)
                except Exception:
                    reset_prompt_cache()
                    valid = 0
            if prompt_cache is not None:
                cached_tokens = full[:valid]


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    validate(req)

    def job():
        mx.reset_peak_memory()
        started = time.perf_counter()
        parts = []
        prompt_len = 0
        gen_tokens = 0
        with closing(token_stream(req)) as gen:
            for prompt_len, response in gen:
                parts.append(response.text)
                gen_tokens = response.generation_tokens
        elapsed = time.perf_counter() - started
        return ChatResponse(
            content="".join(parts).strip(),
            tokens=gen_tokens,
            prompt_tokens=prompt_len,
            time_sec=round(elapsed, 2),
            model=MODELS[active_model]["name"],
            context_limit=MAX_CONTEXT_TOKENS,
        )

    try:
        return await asyncio.wrap_future(submit(job))
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[MLX] Generation error: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE stream: delta events followed by a final stats event."""
    validate(req)
    loop = asyncio.get_running_loop()

    async def generate_events():
        q: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()

        def push(item):
            loop.call_soon_threadsafe(q.put_nowait, item)

        def job():
            if cancel.is_set():
                push(None)
                return
            try:
                mx.reset_peak_memory()
                started = time.perf_counter()
                first = None
                prompt_len = 0
                last = None
                with closing(token_stream(req)) as gen:
                    for prompt_len, response in gen:
                        if cancel.is_set():
                            break
                        if first is None:
                            first = time.perf_counter() - started
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
                        "tokens_per_sec": (
                            round(last.generation_tps, 1) if last else 0
                        ),
                        "model": MODELS[active_model]["name"],
                        "context_limit": MAX_CONTEXT_TOKENS,
                    }))
            except HTTPException as exc:
                push(_sse({"error": exc.detail, "status": exc.status_code}))
            except Exception as exc:
                print(f"[MLX] Generation error: {exc}", flush=True)
                push(_sse({"error": f"Generation failed: {exc}", "status": 500}))
            finally:
                push(None)

        submit(job)
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                # Coalesce everything already queued into a single write.
                chunk = [item]
                done = False
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
            cancel.set()  # client gone or finished: stop the GPU work

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )




# --------------------------------------------------------------------------
# Vision support: isolated SmolVLM process
# --------------------------------------------------------------------------

VISION_MODEL = "mlx-community/SmolVLM-500M-Instruct-4bit"
VISION_MAX_IMAGES = 4
VISION_MAX_FILE_BYTES = 10 * 1024 * 1024
VISION_MAX_PIXELS = 25_000_000
VISION_MAX_PROCESS_RSS = int(float(os.getenv("VISION_MAX_PROCESS_RSS_GB", "3.5")) * 1024**3)
VISION_TIMEOUT_SECONDS = 300
SPEECH_MAX_FILE_BYTES = 20 * 1024 * 1024
SPEECH_MODEL = "mlx-community/whisper-base-mlx"


@app.post("/speech/transcribe")
async def transcribe_speech(audio: UploadFile = File(...)):
    if model_status not in {"ready", "loading"}:
        raise HTTPException(
            status_code=503,
            detail="The local MLX backend is not ready to transcribe audio.",
        )

    raw = await audio.read(SPEECH_MAX_FILE_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="The audio recording is empty.")
    if len(raw) > SPEECH_MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The audio recording exceeds 20 MB.")

    with tempfile.TemporaryDirectory(prefix="sxarf-speech-") as temp_dir:
        audio_path = Path(temp_dir) / "recording.webm"
        audio_path.write_bytes(raw)

        def transcribe():
            import mlx_whisper

            previous_model = active_model
            if previous_model and MODEL_MANAGER.is_active(f"chat:{previous_model}"):
                MODEL_MANAGER.release(f"chat:{previous_model}")
            try:
                result = mlx_whisper.transcribe(
                    str(audio_path),
                    path_or_hf_repo=SPEECH_MODEL,
                    language="en",
                )
                return str(result.get("text", "")).strip()
            finally:
                gc.collect()
                clear_mx_cache()
                if previous_model:
                    load_model(previous_model)

        try:
            text = await asyncio.wrap_future(submit(transcribe))
        except Exception as exc:
            print(f"[Speech] Transcription failed: {exc}", file=sys.stderr, flush=True)
            raise HTTPException(
                status_code=500,
                detail=(
                    "Local transcription failed. Check that ffmpeg is installed "
                    "and that the Whisper model can be downloaded."
                ),
            ) from exc

    return {"text": text}


def unload_chat_model_for_vision():
    """Release the active chat model before launching the vision process."""
    global active_model, model_status

    _sampler_cache.clear()
    if active_model:
        MODEL_MANAGER.release(f"chat:{active_model}")
    active_model = None
    model_status = "vision"

    gc.unfreeze()
    gc.collect()
    clear_mx_cache()


def run_vision_process(image_paths, prompt):
    """Run the VLM in a child process and monitor its process RSS."""
    worker_path = Path(__file__).with_name("vision_worker.py")

    if not worker_path.is_file():
        raise RuntimeError(f"Vision worker is missing: {worker_path}")

    command = [
        sys.executable,
        str(worker_path),
        "--prompt",
        prompt,
    ]

    for image_path in image_paths:
        command.extend(["--image", str(image_path)])

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        cwd=str(worker_path.parent),
    )

    root = psutil.Process(os.getpid())
    peak_rss = 0
    started = time.monotonic()
    exceeded_memory = False
    timed_out = False

    while process.poll() is None:
        try:
            tree = [root, *root.children(recursive=True)]
            current_rss = sum(proc.memory_info().rss for proc in tree)
            peak_rss = max(peak_rss, current_rss)
        except psutil.Error:
            pass

        if peak_rss > VISION_MAX_PROCESS_RSS:
            exceeded_memory = True
            process.kill()
            break

        if time.monotonic() - started > VISION_TIMEOUT_SECONDS:
            timed_out = True
            process.kill()
            break

        time.sleep(0.1)

    try:
        stdout, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, _ = process.communicate()

    if exceeded_memory:
        raise RuntimeError(
            "Vision was stopped because the server process tree exceeded its "
            "configured RSS budget. Metal allocations may not be fully reflected in RSS."
        )

    if timed_out:
        raise RuntimeError("Vision analysis timed out after five minutes.")

    if process.returncode != 0:
        raise RuntimeError(
            f"Vision worker exited with code {process.returncode}. "
            "Check the backend terminal for the MLX-VLM error."
        )

    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Vision worker returned invalid JSON: {exc}"
        ) from exc

    results = payload.get("results")

    if not isinstance(results, list) or len(results) != len(image_paths):
        raise RuntimeError("Vision worker returned incomplete results.")

    return results, round(peak_rss / (1024 * 1024), 1)


def analyze_images_on_worker(image_paths, prompt):
    """This function runs on the existing dedicated MLX worker thread."""
    previous_model = active_model
    had_model = bool(previous_model) and MODEL_MANAGER.is_active(f"chat:{previous_model}")

    if not had_model or previous_model not in MODELS:
        raise RuntimeError("No chat model is loaded to restore after vision.")

    try:
        unload_chat_model_for_vision()
        results, peak_mb = run_vision_process(image_paths, prompt)

        return {
            "results": results,
            "vision_peak_rss_mb": peak_mb,
        }

    finally:
        # Restore the exact model selected before vision analysis.
        try:
            gc.collect()
            clear_mx_cache()
            load_model(previous_model)
        except Exception as restore_error:
            print(
                "[MLX] Could not restore the chat model after vision: "
                f"{restore_error}",
                flush=True,
            )
            raise RuntimeError(
                "Vision processing ended, but the previous chat model "
                f"could not be restored: {restore_error}"
            ) from restore_error


@app.post("/vision/analyze")
async def vision_analyze(
    files: List[UploadFile] = File(...),
    prompt: str = Form(
        default=(
            "Describe the image accurately. Read visible text when possible. "
            "Explain important objects, layout, and context."
        )
    ),
):
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Attach at least one image.",
        )

    if len(files) > VISION_MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"You can attach up to {VISION_MAX_IMAGES} images.",
        )

    clean_prompt = (prompt or "").strip()[:1000]
    if not clean_prompt:
        clean_prompt = "Describe the image accurately."

    with tempfile.TemporaryDirectory(prefix="sxarf-vision-") as temp_dir:
        image_paths = []

        for index, upload in enumerate(files):
            raw = await upload.read(VISION_MAX_FILE_BYTES + 1)

            if not raw:
                raise HTTPException(
                    status_code=400,
                    detail="An attached image is empty.",
                )

            if len(raw) > VISION_MAX_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"{upload.filename or 'Image'} exceeds 10 MB.",
                )

            try:
                image = Image.open(BytesIO(raw))
                image_format = (image.format or "").upper()

                if image_format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError(
                        "Only JPEG, PNG, and WEBP images are supported."
                    )

                if image.width * image.height > VISION_MAX_PIXELS:
                    raise ValueError(
                        "Image is too large. Maximum size is 25 megapixels."
                    )

                image.verify()

            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid image {upload.filename or index + 1}: {exc}"
                    ),
                ) from exc

            suffix = {
                "JPEG": ".jpg",
                "PNG": ".png",
                "WEBP": ".webp",
            }[image_format]

            path = Path(temp_dir) / f"image_{index + 1}{suffix}"
            path.write_bytes(raw)
            image_paths.append(str(path))

        try:
            # Queue vision behind any current generation. All MLX model
            # operations remain serialized on the original worker thread.
            result = await asyncio.wrap_future(
                submit(
                    lambda: analyze_images_on_worker(
                        image_paths,
                        clean_prompt,
                    )
                )
            )
            return result

        except HTTPException:
            raise

        except Exception as exc:
            print(f"[Vision] Analysis failed: {exc}", flush=True)
            raise HTTPException(
                status_code=500,
                detail=f"Vision analysis failed: {exc}",
            ) from exc


# --------------------------------------------------------------------------
# Specialist agents (added in v4.1; every endpoint above is unchanged)
# --------------------------------------------------------------------------
try:
    import sys
    import agents_api
    agents_api.install(app, sys.modules[__name__])
except Exception as _exc:  # agents are optional: never stop the chat server
    print(f"[Agents] Disabled: {type(_exc).__name__}: {_exc}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8741)
    args = parser.parse_args()

    opts = {}
    try:
        import uvloop  # noqa: F401
        opts["loop"] = "uvloop"
    except ImportError:
        pass
    try:
        import httptools  # noqa: F401
        opts["http"] = "httptools"
    except ImportError:
        pass

    print(f"[MLX] Server: http://{args.host}:{args.port}", flush=True)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        **opts,
    )
