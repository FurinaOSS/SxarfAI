"""Shared infrastructure for Sxarf specialist agents.

Specialists are *separate MLX models* (not prompts to Qwen). They are loaded
lazily, kept resident only while useful, and always run on the server's single
MLX worker thread (they never touch the main model's KV cache).
"""
import gc
import time
from typing import Any, Dict, List, Optional

from model_manager import MODEL_MANAGER


class AgentError(RuntimeError):
    pass


def _mx():
    import mlx.core as mx
    return mx


def _mem(name: str):
    mx = _mx()
    fn = getattr(mx, name, None) or getattr(getattr(mx, "metal", None), name, None)
    return fn() if fn else None


def mem_info() -> Dict[str, float]:
    """Unified-memory usage as seen by MLX (GB)."""
    try:
        out = {}
        for key, name in (("active_gb", "get_active_memory"),
                          ("peak_gb", "get_peak_memory"),
                          ("cache_gb", "get_cache_memory")):
            val = _mem(name)
            if val is not None:
                out[key] = round(val / 1e9, 3)
        return out
    except Exception:
        return {}


def clear_cache():
    try:
        _mx().clear_cache()
    except Exception:
        try:
            _mx().metal.clear_cache()
        except Exception:
            pass


class Agent:
    id = "base"
    name = "Base agent"
    role = ""
    repo = ""
    optional = False
    default_enabled = True
    instructions = ""

    def __init__(self, repo: Optional[str] = None, enabled: Optional[bool] = None,
                 model_manager=None):
        self.repo = repo or self.repo
        self.enabled = self.default_enabled if enabled is None else enabled
        self.model_manager = model_manager or MODEL_MANAGER
        self.status = "unloaded"      # unloaded | loading | ready | error
        self.error: Optional[str] = None
        self.load_time_sec: Optional[float] = None
        self.mem_delta_gb: Optional[float] = None
        self.runs = 0
        self.last_used = 0.0
        self.last_run: Optional[Dict[str, Any]] = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self.model_manager.is_active(self.id)

    @property
    def model(self):
        return self.model_manager.get(self.id)[0] if self.loaded else None

    @property
    def tokenizer(self):
        return self.model_manager.get(self.id)[1] if self.loaded else None

    def _load_impl(self):
        from mlx_lm import load
        return load(self.repo)

    def load(self):
        if self.loaded:
            return
        self.status = "loading"
        before = mem_info().get("active_gb")
        t0 = time.perf_counter()
        try:
            self.model_manager.activate(self.id, self._load_impl)
            self.load_time_sec = round(time.perf_counter() - t0, 2)
            after = mem_info().get("active_gb")
            self.mem_delta_gb = (round(after - before, 3)
                                 if before is not None and after is not None else None)
            self.status, self.error = "ready", None
        except Exception as exc:  # never let a specialist take the server down
            self.model_manager.release(self.id)
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"
            gc.collect()
            clear_cache()
            raise AgentError(f"{self.name} failed to load: {self.error}") from exc

    def unload(self):
        self.model_manager.release(self.id)
        if self.status != "error":
            self.status = "unloaded"
        gc.collect()
        clear_cache()

    # -- execution ---------------------------------------------------------
    def _run(self, task: str, payload: Dict[str, Any]) -> Any:
        raise NotImplementedError

    def run(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Uniform envelope: {ok, agent, task, result, error, time_sec, load_time_sec}."""
        t0 = time.perf_counter()
        rec: Dict[str, Any] = {"agent": self.id, "task": task, "ok": False,
                               "error": None, "load_time_sec": 0.0}
        result = None
        try:
            if not self.enabled:
                raise AgentError(f"{self.name} is disabled")
            if not self.loaded:
                l0 = time.perf_counter()
                self.load()
                rec["load_time_sec"] = round(time.perf_counter() - l0, 3)
            result = self._run(task, payload)
            rec["ok"] = True
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["time_sec"] = round(time.perf_counter() - t0, 3)
        self.runs += 1
        self.last_used = time.time()
        self.last_run = dict(rec)
        out = dict(rec)
        out["result"] = result
        return out

    def describe(self) -> Dict[str, Any]:
        status = self.status
        if status == "ready" and not self.loaded:
            status = "unloaded"
        return {
            "id": self.id, "name": self.name, "role": self.role, "repo": self.repo,
            "optional": self.optional, "enabled": self.enabled, "status": status,
            "loaded": self.loaded, "error": self.error,
            "load_time_sec": self.load_time_sec, "mem_delta_gb": self.mem_delta_gb,
            "runs": self.runs, "last_run": self.last_run,
        }


class AgentRegistry:
    """Owns the specialists; keeps at most `max_resident` loaded (LRU eviction)."""

    def __init__(self, agents: List[Agent], max_resident: int = 1, model_manager=None):
        self.model_manager = model_manager or MODEL_MANAGER
        self.agents = {a.id: a for a in agents}
        self.max_resident = min(1, max_resident)
        for agent in self.agents.values():
            agent.model_manager = self.model_manager

    def get(self, agent_id: str) -> Agent:
        if agent_id not in self.agents:
            raise KeyError(agent_id)
        return self.agents[agent_id]

    def list(self) -> List[Dict[str, Any]]:
        for agent in self.agents.values():
            if not agent.loaded and agent.status == "ready":
                agent.status = "unloaded"
        return [a.describe() for a in self.agents.values()]

    def resident(self) -> List[Agent]:
        active = self.model_manager.active_key
        return [self.agents[active]] if active in self.agents else []

    def run(self, agent_id: str, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        agent = self.get(agent_id)
        if agent.enabled and not agent.loaded:
            resident = self.resident()
            while len(resident) >= self.max_resident:
                lru = min(resident, key=lambda a: a.last_used)
                lru.unload()
                resident.remove(lru)
        return agent.run(task, payload)

    def release_all(self):
        if self.model_manager.active_key in self.agents:
            self.model_manager.release()
