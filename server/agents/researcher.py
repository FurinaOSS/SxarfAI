"""Researcher: SmolLM2-360M. Generates queries and extracts *verifiable* facts."""
import re
from typing import Any, Dict, List

from .base import Agent

STOP = {"the", "a", "an", "how", "does", "do", "what", "is", "are", "in", "of", "to",
        "and", "for", "work", "works", "research", "explain", "me", "about", "with", "on",
        "it", "this", "that", "these", "those", "be", "was", "were", "can", "could",
        "would", "should", "will", "has", "have", "had", "from", "by", "or", "as",
        "when", "where", "why", "who", "which", "their", "they", "them", "its", "into",
        "using", "use", "used", "please", "tell", "show", "find", "look", "up"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def fallback_queries(question: str) -> List[str]:
    words = [w for w in re.findall(r"[\w\-\+\.#]+", question) if w.lower() not in STOP]
    core = " ".join(words[:8]) or question[:80]
    queries = [question.strip()[:120], core + " documentation", core + " official documentation"]
    return list(dict.fromkeys(q for q in queries if q))


def relevant_quotes(question: str, passage: str, max_quotes: int = 2) -> List[str]:
    """Select exact, question-relevant sentences without relying on a small model."""
    origin_terms = {"create", "created", "creator", "creators", "found", "founder",
                    "founders", "founded", "cofounder", "cofounders", "co-founded",
                    "establish", "established", "establishment"}

    def normalized_terms(text: str) -> set:
        words = [word.lower() for word in re.findall(r"[\w\-\+\.#]+", text)]
        terms = {word for word in words if len(word) > 1 and word not in STOP}
        if terms.intersection(origin_terms):
            terms.difference_update(origin_terms)
            terms.add("origin")
        terms.update("".join(pair) for pair in zip(words, words[1:])
                     if len(pair[0]) > 1 and len(pair[1]) > 1
                     and pair[0] not in STOP and pair[1] not in STOP)
        return terms

    terms = normalized_terms(question)
    if not terms:
        return []
    sentences = re.split(r"(?<=[.!?])\s+|\n+", passage)
    scored = []
    for index, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue
        words = normalized_terms(sentence)
        overlap = terms & words
        if overlap:
            scored.append((len(overlap) / len(terms), len(overlap), -index, sentence))
    scored.sort(reverse=True)
    return [entry[3] for entry in scored[:max_quotes]]


def parse_queries(text: str, question: str, limit: int = 4) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip().strip('"\'`')
        if 3 <= len(line) <= 120 and norm(line) not in {norm(q) for q in out}:
            out.append(line)
    for q in fallback_queries(question):
        if len(out) >= limit:
            break
        if norm(q) not in {norm(x) for x in out}:
            out.append(q)
    return out[:limit]


def verified_quotes(model_output: str, passage: str, max_quotes: int = 2) -> List[str]:
    """Keep only lines that literally appear in the passage (anti-fabrication)."""
    hay = norm(passage)
    keep: List[str] = []
    for line in model_output.splitlines():
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip().strip('"\u201c\u201d')
        if len(line) < 20 or line.upper().startswith("NONE"):
            continue
        if norm(line) in hay and line not in keep:
            keep.append(line)
        if len(keep) >= max_quotes:
            break
    return keep


class ResearcherAgent(Agent):
    id = "researcher"
    name = "Researcher (SmolLM2-360M)"
    role = "Generates search queries and extracts source-verified facts"
    repo = "mlx-community/SmolLM2-360M-Instruct-6bit"
    instructions = (
        "You are a research assistant. Never invent facts, URLs or citations. "
        "Copy text exactly from the supplied passage; if nothing is relevant, say NONE."
    )

    def _chat(self, user: str, max_tokens: int) -> str:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler
        msgs = [{"role": "system", "content": self.instructions},
                {"role": "user", "content": user}]
        prompt = self.tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True)
        ids = self.tokenizer.encode(prompt, add_special_tokens=False)
        text = ""
        for r in stream_generate(self.model, self.tokenizer, prompt=ids,
                                 max_tokens=max_tokens, sampler=make_sampler(temp=0.0)):
            text += r.text
        return text

    def _run(self, task: str, payload: Dict[str, Any]) -> Any:
        if task == "queries":
            q = payload["question"]
            raw = self._chat(
                "Write 3 short web search queries (max 8 words each), one per line, "
                "no numbering, to find official documentation that answers:\n" + q, 80)
            return {"queries": parse_queries(raw, q)}

        if task == "extract":
            q = payload["question"]
            facts, rejected = [], 0
            for p in payload["passages"]:
                text = p["text"][:900]
                raw = self._chat(
                    f"Question: {q}\n\nPassage:\n{text}\n\n"
                    "Copy up to 2 sentences from the passage that help answer the question, "
                    "exactly as written, one per line. If none help, write NONE.", 140)
                quotes = verified_quotes(raw, text)
                if not quotes and raw.strip() and not raw.strip().upper().startswith("NONE"):
                    rejected += 1
                for quote in quotes:
                    facts.append({"fact": quote, "source_url": p.get("url"),
                                  "title": p.get("title"), "origin": p.get("origin", "web"),
                                  "rerank_score": p.get("score"), "verified": True})
            return {"facts": facts, "rejected_unverifiable": rejected}
        raise ValueError(f"Unknown researcher task: {task}")
