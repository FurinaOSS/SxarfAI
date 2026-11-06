"""Memory retriever: Qwen3-Embedding-0.6B (last-token pooling, L2-normalised)."""
import json
import os
import threading
from typing import Any, Callable, Dict, List

from .base import Agent

QUERY_TASK = "Given a search query, retrieve relevant documentation passages"


class EmbeddingAgent(Agent):
    id = "embedding"
    name = "Memory Retriever (Qwen3-Embedding-0.6B)"
    role = "Embeds text for semantic search over stored knowledge"
    repo = "mlx-community/Qwen3-Embedding-0.6B-8bit"
    instructions = QUERY_TASK
    MAX_TOKENS = 512

    def embed_one(self, text: str, is_query: bool) -> List[float]:
        import mlx.core as mx
        tok = self.tokenizer
        if is_query:
            text = f"Instruct: {QUERY_TASK}\nQuery:{text}"
        ids = tok.encode(text, add_special_tokens=False)[: self.MAX_TOKENS]
        eos = tok.convert_tokens_to_ids("<|endoftext|>")
        ids.append(eos if isinstance(eos, int) and eos >= 0 else tok.eos_token_id)
        hidden = self.model.model(mx.array([ids]))      # [1, T, D] backbone, no lm_head
        vec = hidden[0, -1, :].astype(mx.float32)
        vec = vec / mx.linalg.norm(vec)
        mx.eval(vec)
        return vec.tolist()

    def _run(self, task: str, payload: Dict[str, Any]) -> Any:
        if task != "embed":
            raise ValueError(f"Unknown embedding task: {task}")
        vecs = [self.embed_one(t, bool(payload.get("is_query"))) for t in payload["texts"]]
        return {"embeddings": vecs, "dim": len(vecs[0]) if vecs else 0}


class MemoryStore:
    """Persistent semantic store. Embeddings come from the EmbeddingAgent."""

    def __init__(self, path: str):
        self.path = os.path.expanduser(path)
        self._lock = threading.Lock()
        self.items: List[Dict[str, Any]] = []
        try:
            with open(self.path) as f:
                self.items = json.load(f)
        except Exception:
            self.items = []

    def count(self) -> int:
        return len(self.items)

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.items, f)
        os.replace(tmp, self.path)

    def add(self, docs: List[Dict[str, str]], embed: Callable[[List[str], bool], List[List[float]]]):
        vecs = embed([d["text"] for d in docs], False)
        with self._lock:
            for d, v in zip(docs, vecs):
                self.items.append({"id": len(self.items), "text": d["text"],
                                   "source": d.get("source", ""), "embedding": v})
            self._save()
        return len(docs)

    def search(self, query: str, k: int, embed) -> List[Dict[str, Any]]:
        import numpy as np
        if not self.items:
            return []
        q = np.array(embed([query], True)[0], dtype=np.float32)
        m = np.array([i["embedding"] for i in self.items], dtype=np.float32)
        sims = m @ q
        top = np.argsort(-sims)[:k]
        return [{"id": self.items[i]["id"], "text": self.items[i]["text"],
                 "source": self.items[i]["source"], "similarity": round(float(sims[i]), 4)}
                for i in top]
