#!/usr/bin/env python3
"""Call the running QuantBot agent and retain its actual SSE tool transcript.

Run inside qwenpaw, whose localhost API uses the configured workspace/model.
This deliberately does not use `qwenpaw task`: the inspected headless builder
had no workspace tools. No automatic POST retry (a disconnected run may live on).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.request


def summarize_events(path):
    """Summarize observable actions/usage, not private reasoning text."""
    calls = {}
    usage = {}
    response_status = None
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:])
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "turn_usage":
                usage = event.get("usage", {})
            if event.get("object") == "response":
                response_status = event.get("status")
            if event.get("type") == "plugin_call" and event.get("status") == "completed":
                for content in event.get("content", []):
                    call = content.get("data", {})
                    if isinstance(call, dict) and call.get("call_id"):
                        calls[call["call_id"]] = call
    return {"agent_response_status": response_status, "tool_call_count": len(calls),
            "tool_names": sorted({c.get("name", "unknown") for c in calls.values()}),
            "model_usage": usage}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instruction", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8088")
    p.add_argument("--timeout", type=int, default=7200)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    instruction = args.instruction.read_text()
    (args.output / "instruction.md").write_text(instruction)
    payload = {
        "input": [{"role": "user", "content": [{"type": "text", "text": instruction}]}],
        "session_id": args.session, "user_id": "quantmind-research",
        "channel": "console", "stream": True,
    }
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/console/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    meta = {"session_id": args.session, "started_at": datetime.now(timezone.utc).isoformat(),
            "transport_status": "submitted", "note": "Transport success is not research success"}
    meta_path = args.output / "transport.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    t0 = time.monotonic()
    events = 0
    messages = {}
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response, \
                (args.output / "events.sse").open("w") as log:
            meta["http_status"] = response.status
            for raw in response:
                line = raw.decode("utf-8")
                log.write(line)
                log.flush()
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if not value or value == "[DONE]":
                    continue
                try:
                    event = json.loads(value)
                except json.JSONDecodeError:
                    continue
                events += 1
                if isinstance(event, dict):
                    ident = event.get("id") or event.get("msg_id")
                    if ident:
                        messages[ident] = event
                    kind = event.get("type") or event.get("object")
                    status = event.get("status")
                    if kind in ("plugin_call", "plugin_call_output", "response") and status in ("completed", "failed", "cancelled"):
                        print(json.dumps({"event": events, "type": kind, "status": status}, ensure_ascii=False), flush=True)
            meta["transport_status"] = "stream_closed"
    except Exception as exc:
        meta["transport_status"] = "error"
        meta["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        meta.update(elapsed_seconds=round(time.monotonic() - t0, 2), events=events)
        meta.update(summarize_events(args.output / "events.sse"))
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        (args.output / "messages.json").write_text(json.dumps(list(messages.values()), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
