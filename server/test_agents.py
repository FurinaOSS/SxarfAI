"""Offline tests (no MLX/model weights needed): python -m unittest test_agents -v"""
import unittest

import agents.base as agent_base
import agents.orchestrator as orchestrator_module
from agents.base import Agent, AgentRegistry
from agents.code_specialist import static_issues
from agents.orchestrator import ResearchPipeline, chunk_text, decide, format_for_main, is_official, parse_json_obj
from agents.researcher import fallback_queries, parse_queries, relevant_quotes, verified_quotes
from agents.tools import FallbackSearch, SearchTool, html_to_text, parse_ddg_html
from model_manager import ModelManager

agent_base.mem_info = lambda: {}
agent_base.clear_cache = lambda: None
orchestrator_module.mem_info = lambda: {}


class Fake(Agent):
    def __init__(self, id, fail=False, **kw):
        self.id, self.name, self.fail = id, id, fail
        super().__init__(repo="x", **kw)

    def _load_impl(self):
        if self.fail:
            raise RuntimeError("unsupported architecture")
        return object(), object()

    def _run(self, task, payload):
        return {"ok": 1}


class TestCore(unittest.TestCase):
    def test_model_manager_keeps_only_one_model_resident(self):
        manager = ModelManager()
        chat = (object(), object())
        agent = (object(), object())
        manager.activate("chat:gemma2", lambda: chat)
        manager.activate("reranker", lambda: agent)
        self.assertFalse(manager.is_active("chat:gemma2"))
        self.assertTrue(manager.is_active("reranker"))
        self.assertEqual(manager.get("reranker"), agent)
        manager.release()
        self.assertIsNone(manager.active_key)

    def test_agent_status_tracks_shared_model_residency(self):
        manager = ModelManager()
        agent = Fake("test-agent", model_manager=manager)
        agent.load()
        self.assertTrue(agent.describe()["loaded"])
        manager.activate("chat:gemma2", lambda: (object(), object()))
        self.assertFalse(agent.describe()["loaded"])
        self.assertEqual(agent.describe()["status"], "unloaded")

    def test_failed_load_is_contained(self):
        a = Fake("a", fail=True)
        r = a.run("t", {})
        self.assertFalse(r["ok"]); self.assertEqual(a.status, "error"); self.assertIn("unsupported", r["error"])

    def test_disabled(self):
        self.assertFalse(Fake("a", enabled=False).run("t", {})["ok"])

    def test_lru_eviction(self):
        reg = AgentRegistry([Fake("a"), Fake("b"), Fake("c")], max_resident=2)
        for i in "abc":
            reg.run(i, "t", {})
        self.assertEqual(len(reg.resident()), 1)
        self.assertFalse(reg.get("a").loaded)
        reg.release_all(); self.assertEqual(reg.resident(), [])

    def test_verbatim_filter(self):
        src = "Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key."
        out = "1. Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key.\nFernet uses ROT13 internally and is unbreakable."
        self.assertEqual(len(verified_quotes(out, src)), 1)
        self.assertEqual(verified_quotes("NONE", src), [])

    def test_relevant_quotes_are_verbatim(self):
        passage = ("Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key. "
                   "The library also supports key rotation with MultiFernet.")
        quotes = relevant_quotes("How does Fernet protect encrypted messages?", passage)
        self.assertEqual(len(quotes), 1)
        self.assertIn(quotes[0], passage)

    def test_founder_question_matches_foundation_wording(self):
        passage = "Founded in 2022 by Safi, the enterprise was established to serve clients."
        quotes = relevant_quotes(
            "Research stegroup and tell me who created and is the founder", passage)
        self.assertEqual(quotes, [passage])

    def test_queries(self):
        qs = parse_queries("1. fernet python docs\n2. fernet python docs\n- cryptography fernet", "How does Fernet work in Python?")
        self.assertEqual(len(set(q.lower() for q in qs)), len(qs))
        self.assertTrue(fallback_queries("How does Fernet work?"))

    def test_chunk_and_html(self):
        self.assertTrue(all(len(c) <= 760 for c in chunk_text("Sentence number one is here. " * 200)))
        self.assertNotIn("alert", html_to_text("<script>alert(1)</script><p>Hello docs world</p>"))

    def test_ddg_parse(self):
        page = ('<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&rut=x" class="result__a">Py <b>docs</b></a>'
                '<a class="result__snippet" href="#">The <b>official</b> docs</a>')
        r = parse_ddg_html(page)
        self.assertEqual(r[0]["url"], "https://docs.python.org/3/"); self.assertTrue(is_official(r[0]["url"]))
        self.assertEqual(r[0]["title"], "Py docs")
        self.assertEqual(r[0]["snippet"], "The official docs")

    def test_ddg_lite_parse(self):
        page = ("<td><a rel=\"nofollow\" href=\"//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdoc%2F&amp;rut=x\" "
                "class='result-link'>Our Documentation | Python.org</a></td>"
                "<td class='result-snippet'>The <b>official</b> home of the <b>Python</b> Programming Language</td>")
        results = parse_ddg_html(page)
        self.assertEqual(results, [{
            "title": "Our Documentation | Python.org",
            "url": "https://www.python.org/doc/",
            "snippet": "The official home of the Python Programming Language",
        }])

    def test_yahoo_search_parse(self):
        page = ("<div class='dd algo algo-sr'><div class='compTitle'><a href='https://r.search.yahoo.com/RU=https%3a%2f%2fwww.stegroup.co%2fabout/RK=x'>"
                "<h3>Leadership &amp; Vision | STE Group</h3></a></div>"
                "<div class='compText'><p>Founded in 2022 by Safi.</p></div></div>")
        from agents.tools import _YahooResults
        parser = _YahooResults()
        parser.feed(page)
        self.assertEqual(parser.results, [{
            "title": "Leadership & Vision | STE Group",
            "url": "https://www.stegroup.co/about",
            "snippet": "Founded in 2022 by Safi.",
        }])

    def test_bing_search_parse(self):
        page = ("<li class='b_algo'><h2><a href='https://www.bing.com/ck/?u=a1aHR0cHM6Ly93d3cuc3RlZ3JvdXAuY28vYWJvdXQ'>"
                "Leadership &amp; Vision | STE Group</a></h2>"
                "<p class='b_lineclamp2'>Founded in 2022 by Safi.</p></li>")
        from agents.tools import _BingResults
        parser = _BingResults()
        parser.feed(page)
        self.assertEqual(parser.results, [{
            "title": "Leadership & Vision | STE Group",
            "url": "https://www.stegroup.co/about",
            "snippet": "Founded in 2022 by Safi.",
        }])

    def test_search_fallback_when_ddg_is_blocked(self):
        class BlockedSearch(SearchTool):
            name = "blocked"
            def available(self): return True
            def search(self, query, n=5): raise RuntimeError("bot check")

        class WorkingSearch(SearchTool):
            name = "working"
            def available(self): return True
            def search(self, query, n=5): return [{"title": "result", "url": "https://example.com", "snippet": "text"}]

        result = FallbackSearch([BlockedSearch(), WorkingSearch()]).search("question")
        self.assertEqual(result[0]["title"], "result")

    def test_decide(self):
        self.assertFalse(decide("hi, tell me a joke", "auto", None)["research"])
        gen = lambda s, u, n: '{"research": true, "topic": "fernet"}'
        decision = decide("Research how Fernet encryption works", "auto", gen)
        self.assertTrue(decision["research"])
        self.assertEqual(decision["by"], "heuristic")
        self.assertTrue(decide("Why is Fernet secure against tampering?", "auto", None)["research"])
        self.assertTrue(decide("Who founded STE Group?", "auto", None)["research"])
        self.assertTrue(decide("x", "on", None)["research"]); self.assertFalse(decide("research x", "off", None)["research"])
        self.assertIsNone(parse_json_obj("nope"))

    def test_code_checks(self):
        self.assertTrue(static_issues("def f(x=[]):\n  try:\n    pass\n  except:\n    pass"))
        self.assertTrue(static_issues("def (:"))


class StubRegistry:
    def __init__(self, searchless=False): self.released = False
    def get(self, i): return type("A", (), {"enabled": False})()
    def release_all(self): self.released = True
    def run(self, aid, task, payload):
        if aid == "researcher" and task == "queries":
            return {"ok": True, "result": {"queries": ["fernet docs"]}, "error": None, "agent": aid, "task": task, "time_sec": 0, "load_time_sec": 0}
        if aid == "reranker":
            n = len(payload["documents"]); return {"ok": True, "result": {"scores": [0.9] * n, "ranking": list(range(n))}, "error": None, "agent": aid, "task": task, "time_sec": 0, "load_time_sec": 0}
        if aid == "researcher":
            p = payload["passages"][0]
            return {"ok": True, "result": {"rejected_unverifiable": 0, "facts": [{"fact": p["text"][:80], "source_url": p["url"], "title": "t", "origin": "web", "rerank_score": .9, "verified": True}]}, "error": None, "agent": aid, "task": task, "time_sec": 0, "load_time_sec": 0}


class FakeSearch:
    name = "fake"
    def __init__(self, ok=True, empty=False): self.ok, self.empty = ok, empty
    def available(self): return True
    def search(self, q, n=5):
        if not self.ok: raise OSError("offline")
        if self.empty: return []
        return [{"title": "Fernet", "url": "https://cryptography.io/en/latest/fernet/", "snippet": "symmetric encryption"}]


class FakeFetch:
    def fetch(self, url): return "Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key. " * 3


class TestPipeline(unittest.TestCase):
    def test_happy(self):
        reg = StubRegistry()
        rep = ResearchPipeline(reg, FakeSearch(), FakeFetch()).run("how does fernet work")
        self.assertTrue(rep["searched"]); self.assertTrue(rep["facts"]); self.assertTrue(reg.released)
        self.assertIn("cryptography.io", format_for_main(rep))

    def test_offline_does_not_claim_search(self):
        rep = ResearchPipeline(StubRegistry(), FakeSearch(ok=False), FakeFetch()).run("q")
        self.assertFalse(rep["searched"]); self.assertEqual(rep["facts"], [])
        self.assertIn("Web search performed: NO", format_for_main(rep))

    def test_empty_search_does_not_claim_search(self):
        rep = ResearchPipeline(StubRegistry(), FakeSearch(empty=True), FakeFetch()).run("q")
        self.assertFalse(rep["searched"])
        self.assertIn("returned no results", " ".join(rep["gaps"]))

    def test_original_question_is_searched_before_agent_suggestions(self):
        class CaptureSearch(FakeSearch):
            def __init__(self):
                super().__init__()
                self.queries = []
            def search(self, q, n=5):
                self.queries.append(q)
                return super().search(q, n)

        search = CaptureSearch()
        rep = ResearchPipeline(StubRegistry(), search, FakeFetch()).run("How does Fernet work?")
        self.assertEqual(rep["queries"][0], "How does Fernet work?")
        self.assertEqual(rep["queries"][1], "Fernet documentation")
        self.assertEqual(search.queries[0], "How does Fernet work?")

    def test_low_rank_fallback_keeps_best_evidence(self):
        class LowRankRegistry(StubRegistry):
            def run(self, aid, task, payload):
                result = super().run(aid, task, payload)
                if aid == "reranker":
                    result["result"]["scores"] = [0.01] * len(payload["documents"])
                return result

        rep = ResearchPipeline(LowRankRegistry(), FakeSearch(), FakeFetch()).run("how does fernet work")
        self.assertTrue(rep["facts"])


if __name__ == "__main__":
    unittest.main()
