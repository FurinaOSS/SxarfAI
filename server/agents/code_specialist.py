"""Experimental code specialist: SmallCoder-303M. Disabled by default; if the
checkpoint cannot be loaded by mlx-lm, it reports 'error' and nothing else
is affected. No other model is substituted."""
import ast
from typing import Any, Dict, List

from .base import Agent


def static_issues(code: str) -> List[str]:
    """Deterministic Python checks used alongside the model for 'common mistakes'."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError line {exc.lineno}: {exc.msg}"]
    out = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.args.defaults + n.args.kw_defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    out.append(f"line {n.lineno}: mutable default argument in {n.name}()")
        if isinstance(n, ast.ExceptHandler) and n.type is None:
            out.append(f"line {n.lineno}: bare except")
        if isinstance(n, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in n.ops):
            if any(isinstance(c, ast.Constant) and c.value is None for c in n.comparators):
                out.append(f"line {n.lineno}: compare to None with 'is', not '=='")
    return out


class CodeSpecialistAgent(Agent):
    id = "code_specialist"
    name = "Code Specialist (SmallCoder-303M, experimental)"
    role = "Small code completions and common-mistake checks"
    repo = "Beebey/smallcoder-303m"
    optional = True
    default_enabled = False

    def _run(self, task: str, payload: Dict[str, Any]) -> Any:
        if task == "check":
            return {"issues": static_issues(payload["code"])}
        if task != "complete":
            raise ValueError(f"Unknown code task: {task}")
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler
        ids = self.tokenizer.encode(payload["prefix"])
        text = ""
        for r in stream_generate(self.model, self.tokenizer, prompt=ids,
                                 max_tokens=int(payload.get("max_tokens", 160)),
                                 sampler=make_sampler(temp=0.2)):
            text += r.text
        return {"completion": text}
