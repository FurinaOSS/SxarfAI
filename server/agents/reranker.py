"""Evidence ranker: Qwen3-Reranker-0.6B. Uses the real yes/no logit scoring
interface (P(yes) at the final position), NOT chat generation."""
from typing import Any, Dict, List

from .base import Agent

PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on '
          'the Query and the Instruct provided. Note that the answer can only be "yes" or '
          '"no".<|im_end|>\n<|im_start|>user\n')
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
DEFAULT_INSTRUCT = ("Given a research question, judge whether the document contains "
                    "information useful for answering it")


class RerankerAgent(Agent):
    id = "reranker"
    name = "Evidence Ranker (Qwen3-Reranker-0.6B)"
    role = "Scores documents against the research question (P(relevant))"
    repo = "mlx-community/Qwen3-Reranker-0.6B-mxfp8"
    instructions = DEFAULT_INSTRUCT
    MAX_DOC_CHARS = 1800

    def _load_impl(self):
        out = super()._load_impl()
        tok = out[1]
        self._yes = tok.encode("yes", add_special_tokens=False)[-1]
        self._no = tok.encode("no", add_special_tokens=False)[-1]
        return out

    def score(self, query: str, doc: str, instruction: str = DEFAULT_INSTRUCT) -> float:
        import mlx.core as mx
        body = (f"<Instruct>: {instruction}\n<Query>: {query}\n"
                f"<Document>: {doc[:self.MAX_DOC_CHARS]}")
        ids = self.tokenizer.encode(PREFIX + body + SUFFIX, add_special_tokens=False)
        logits = self.model(mx.array([ids]))[:, -1, :]
        pair = mx.stack([logits[:, self._no], logits[:, self._yes]], axis=1)
        prob = mx.softmax(pair.astype(mx.float32), axis=1)[:, 1]
        mx.eval(prob)
        return float(prob.item())

    def _run(self, task: str, payload: Dict[str, Any]) -> Any:
        if task != "score":
            raise ValueError(f"Unknown reranker task: {task}")
        query = payload["query"]
        docs: List[str] = payload["documents"]
        instr = payload.get("instruction") or DEFAULT_INSTRUCT
        scores = [round(self.score(query, d, instr), 4) for d in docs]
        ranking = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)
        return {"scores": scores, "ranking": ranking}
