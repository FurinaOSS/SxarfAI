#!/usr/bin/env python3
"""Measure live inference latency and process-tree memory.

Run with the server already running:
    python server/bench.py --pid SERVER_PID
The MLX peak is read from the existing /agents/status endpoint.
"""
import argparse
import json
import threading
import time
import urllib.request

import psutil


def request(base, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def find_server_pid(port, override=None):
    if override:
        return int(override)
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            args = proc.info["cmdline"] or []
            if any(arg.endswith("server.py") for arg in args) and (
                "--port" not in args or str(port) in args
            ):
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise RuntimeError(
        f"Could not find server.py for port {port}; rerun with --pid SERVER_PID."
    )


def process_tree_rss(root_pid):
    root = psutil.Process(root_pid)
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    total = 0
    for proc in processes:
        try:
            total += proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def memory_snapshot(base, pid, stop, peaks):
    while not stop.is_set():
        peaks["rss_bytes"] = max(peaks["rss_bytes"], process_tree_rss(pid))
        try:
            with request(base, "/agents/status", timeout=5) as response:
                status = json.load(response)
            peak = (status.get("memory") or {}).get("peak_gb")
            if isinstance(peak, (int, float)):
                peaks["mlx_peak_gb"] = max(peaks["mlx_peak_gb"] or 0, peak)
            peaks["resident"] = status.get("resident", [])
        except Exception as exc:
            peaks["status_error"] = f"{type(exc).__name__}: {exc}"
        stop.wait(0.5)


def run_stream(base, pid, label, path, body):
    peaks = {"rss_bytes": 0, "mlx_peak_gb": None, "resident": []}
    stop = threading.Event()
    monitor = threading.Thread(
        target=memory_snapshot, args=(base, pid, stop, peaks), daemon=True
    )
    monitor.start()

    started = time.perf_counter()
    first_token = None
    done = {}
    agent_events = []
    stream_errors = []
    try:
        with request(base, path, body) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if "delta" in event and first_token is None:
                    first_token = time.perf_counter() - started
                if "agent" in event:
                    agent_events.append(event["agent"])
                if "error" in event:
                    stream_errors.append(event)
                if event.get("done"):
                    done = event
    finally:
        stop.set()
        monitor.join(timeout=3)

    return {
        "scenario": label,
        "ttft_sec": round(first_token, 3) if first_token is not None else None,
        "tokens_per_sec": done.get("tokens_per_sec"),
        "tokens": done.get("tokens"),
        "time_sec": done.get("time_sec"),
        "process_tree_peak_rss_gb": round(peaks["rss_bytes"] / 1e9, 3),
        "mlx_peak_gb": peaks["mlx_peak_gb"],
        "resident_at_sample": peaks["resident"],
        "agent_events": agent_events,
        "stream_errors": stream_errors,
        "status_error": peaks.get("status_error"),
        "error": None if done else stream_errors or "No SSE done event received",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8741")
    parser.add_argument("--pid", help="Server PID; otherwise detected from process args")
    args = parser.parse_args()

    try:
        with request(args.base, "/health", timeout=5) as response:
            health = json.load(response)
    except Exception as exc:
        print(json.dumps({
            "error": f"{type(exc).__name__}: {exc}",
            "message": "Start the MLX server on a Metal-enabled macOS session, then rerun this benchmark.",
            "scenarios": [
                "short",
                "~2k-token context",
                "agent/research",
            ],
        }, indent=2))
        return 2
    pid = find_server_pid(8741, args.pid)
    print(json.dumps({"health": health, "server_pid": pid}, indent=2))

    short = {
        "messages": [{"role": "user", "content": "Explain a hash map in two sentences."}],
        "max_tokens": 128,
    }
    long_context = (
        "The local application stores conversation history and loads model weights on demand. "
        * 130
    ) + "\nSummarize the main idea in one sentence."
    context = {
        "messages": [{"role": "user", "content": long_context}],
        "max_tokens": 128,
    }
    research = {
        "messages": [{
            "role": "user",
            "content": "Research the current Python documentation for asyncio task groups and summarize how cancellation works.",
        }],
        "max_tokens": 180,
        "agents": "on",
    }

    for label, path, body in (
        ("short", "/chat/stream", short),
        ("~2k-token context", "/chat/stream", context),
        ("agent/research", "/chat/agent/stream", research),
    ):
        try:
            print(json.dumps(run_stream(args.base, pid, label, path, body), indent=2))
        except Exception as exc:
            print(json.dumps({
                "scenario": label,
                "error": f"{type(exc).__name__}: {exc}",
                "peak_rss_gb": round(process_tree_rss(pid) / 1e9, 3),
            }, indent=2))


if __name__ == "__main__":
    raise SystemExit(main() or 0)
