"""Run against a live server:  python bench_agents.py [--base http://127.0.0.1:8741]
Reports Qwen first-token latency / tok/s, agent pipeline time, and memory."""
import argparse, json, time, urllib.request


def call(base, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=600)


def stream(base, path, body):
    events, t0, first = [], time.perf_counter(), None
    with call(base, path, body) as r:
        for line in r:
            line = line.decode().strip()
            if line.startswith("data: "):
                e = json.loads(line[6:])
                if "delta" in e and first is None:
                    first = time.perf_counter() - t0
                events.append(e)
    done = next((e for e in events if e.get("done")), {})
    return {"wall_first_token_sec": round(first or 0, 3), "tokens_per_sec": done.get("tokens_per_sec"),
            "tokens": done.get("tokens"), "total_sec": done.get("time_sec"), "agents": done.get("agents"),
            "agent_events": [e["agent"] for e in events if "agent" in e]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="http://127.0.0.1:8741")
    b = ap.parse_args().base
    def mem(): return json.load(call(b, "/agents/status"))["memory"]
    print("health:", json.load(call(b, "/health")))
    print("memory before:", mem())
    chat = {"messages": [{"role": "user", "content": "Explain what a hash map is in 3 sentences."}], "max_tokens": 200}
    print("\n[1] plain /chat/stream (existing path):", stream(b, "/chat/stream", chat))
    print("[2] /chat/agent/stream, agents=off:", stream(b, "/chat/agent/stream", {**chat, "agents": "off"}))
    q = {"messages": [{"role": "user", "content": "Research how Fernet encryption works in Python."}], "max_tokens": 300, "agents": "on"}
    r = stream(b, "/chat/agent/stream", q)
    print("[3] agent research run:", json.dumps({k: v for k, v in r.items() if k != "agent_events"}, indent=1))
    for e in r["agent_events"]:
        if e.get("status") == "done": print("   stage", e["stage"], e["time_sec"], "s", e.get("memory"))
    st = json.load(call(b, "/agents/status"))
    for a in st["agents"]:
        print("  ", a["id"], a["status"], "load", a["load_time_sec"], "s  mem+", a["mem_delta_gb"], "GB", "err:", a["error"])
    print("resident after:", st["resident"], "memory after:", st["memory"])
