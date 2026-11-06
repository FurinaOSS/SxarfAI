"""Exclusive ownership for MLX model weights and tokenizers."""
import gc
from typing import Callable, Optional, Tuple


class ModelManager:
    def __init__(self):
        self.active_key: Optional[str] = None
        self._model = None
        self._tokenizer = None
        self.on_release = None
        self.clear_cache = None

    def is_active(self, key: str) -> bool:
        return self.active_key == key and self._model is not None

    def get(self, key: str) -> Tuple[object, object]:
        if not self.is_active(key):
            raise RuntimeError(f"Model {key!r} is not active.")
        return self._model, self._tokenizer

    def activate(self, key: str, loader: Callable[[], tuple]):
        if self.is_active(key):
            return self.get(key)
        self.release()
        try:
            model, tokenizer = loader()
        except Exception:
            self.release()
            raise
        self.active_key = key
        self._model = model
        self._tokenizer = tokenizer
        return model, tokenizer

    def release(self, key: Optional[str] = None):
        if key is not None and self.active_key != key:
            return
        released_key = self.active_key
        if released_key is None:
            return
        self._model = None
        self._tokenizer = None
        self.active_key = None
        if self.on_release is not None:
            self.on_release(released_key)
        gc.collect()
        if self.clear_cache is not None:
            self.clear_cache()


MODEL_MANAGER = ModelManager()
