"""Private, local observations; no model content or credentials are retained."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
import uuid

import requests

# Pi 0.87.1's zai-coding-cn/glm-5.3 map. Do not infer max from reasoning=True.
GLM_THINKING_MAP = {
    "off": None,
    "minimal": None,
    "low": "low",
    "medium": None,
    "high": "high",
    "xhigh": None,
    "max": "max",
}


def project_provider(source):
    if source.get("baseUrl") != "https://open.bigmodel.cn/api/coding/paas/v4":
        raise ValueError("unexpected_glm_endpoint")
    matches = [m for m in source.get("models", []) if m.get("id") == "glm-5.3"]
    if len(matches) != 1:
        raise ValueError("glm_model_ambiguous")
    fields = {
        "id",
        "name",
        "api",
        "reasoning",
        "input",
        "cost",
        "contextWindow",
        "maxTokens",
        "compat",
        "thinkingLevelMap",
    }
    model = {k: v for k, v in matches[0].items() if k in fields}
    model.setdefault("thinkingLevelMap", dict(GLM_THINKING_MAP))
    compat = model.get("compat", {})
    mapping = model["thinkingLevelMap"]
    if (
        not isinstance(mapping, dict)
        or mapping.get("max") != "max"
        or model.get("reasoning") is not True
        or compat.get("supportsReasoningEffort") is not True
        or compat.get("thinkingFormat") != "zai"
        or model.get("api", source.get("api")) != "openai-completions"
    ):
        raise ValueError("glm_max_mapping_required")
    return {
        "baseUrl": source["baseUrl"],
        "api": "openai-completions",
        "models": [model],
        "apiKey": "${QM_GLM_KEY}",
    }


def private_file(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
    ):
        os.close(fd)
        raise ValueError("unsafe_trace_file")
    os.fchmod(fd, 0o600)
    return fd


def write_private(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with os.fdopen(private_file(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL), "w") as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def digest(value):
    return hashlib.sha256(value).hexdigest()


class SafeQuotaSession(requests.Session):
    """Retain only the provider's small, explicitly allowed quota fields."""

    def __init__(self):
        super().__init__()
        self.safe_limits = []

    def get(self, *args, **kwargs):
        response = super().get(*args, **kwargs)
        if response.status_code == 200:
            payload = response.json()
            fields = {
                "unit",
                "number",
                "percentage",
                "currentValue",
                "remaining",
                "nextResetTime",
            }
            for row in payload.get("data", {}).get("limits", []):
                if not isinstance(row, dict) or row.get("type") not in (
                    "TOKENS_LIMIT",
                    "TIME_LIMIT",
                    "CREDIT_LIMIT",
                ):
                    continue
                safe = {"type": row["type"]}
                for key in fields:
                    value = row.get(key)
                    if key not in row:
                        continue
                    try:
                        if value is None or (
                            not isinstance(value, bool) and math.isfinite(float(value))
                        ):
                            safe[key] = value
                    except (TypeError, ValueError):
                        pass
                self.safe_limits.append(safe)
        return response


class RuntimeTrace:
    def __init__(self, root, programme):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("unsafe_trace_directory")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.programme = programme
        self.lock = threading.RLock()
        self.calls = self.root / "calls.jsonl"
        self.wire = self.root / "wire.jsonl"
        self.report = self.root / "quota-window.json"
        self.last_calls = {}
        self.last_errors = {}
        self.state = {
            "schema": 1,
            "programme": programme,
            "t0": None,
            "last_curve_bucket": None,
            "last_evaluation_bucket": None,
            "last_checkpoint": 0,
            "target_percent": 60,
            "minimum_percent": 50,
            "account_attribution": "shared_unknown",
        }
        if self.report.exists():
            with os.fdopen(private_file(self.report, os.O_RDONLY)) as f:
                self.state = json.load(f)
            if self.state.get("programme") != programme:
                raise ValueError("trace_programme_mismatch")
        else:
            write_private(self.report, self.state)
        for event in self.read_events(self.calls):
            if event["event"] == "call_start":
                self.last_calls[event["task_id"]] = event["call_id"]
                self.last_errors[event["call_id"]] = (
                    True  # no end = interrupted/unknown
                )
            elif event["event"] == "call_end":
                self.last_errors[event["call_id"]] = event.get("error") is not None
        # The append is durable before its report update; a crash must not let a
        # later, better quota overwrite an already failed checkpoint.
        for event in self.read_events(self.root / "quota-checkpoints.jsonl"):
            if event["index"] > self.state["last_checkpoint"]:
                self.state["last_checkpoint"] = event["index"]
                self.state["last_checkpoint_result"] = event
        self.wire_offset = 0
        self.wire_calls = set()
        self.sync_wire()

    def append(self, name, event):
        data = (json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n").encode()
        with os.fdopen(
            private_file(self.root / name, os.O_WRONLY | os.O_CREAT | os.O_APPEND), "ab"
        ) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def read_events(path):
        if not path.exists():
            return []
        with os.fdopen(private_file(path, os.O_RDONLY)) as f:
            # A crash may leave an incomplete final append; never parse it as an event.
            return [json.loads(line) for line in f if line.endswith("\n")]

    def sync_wire(self):
        with self.lock:
            if not self.wire.exists():
                return
            with os.fdopen(private_file(self.wire, os.O_RDONLY)) as f:
                f.seek(self.wire_offset)
                while True:
                    line = f.readline()
                    if not line or not line.endswith("\n"):
                        break
                    event = json.loads(line)
                    self.wire_offset = f.tell()
                    if event.get("event") == "wire_request":
                        self.wire_calls.add(event["call_id"])
                    if (
                        event.get("event") == "wire_request"
                        and self.state["t0"] is None
                    ):
                        self.state["t0"] = event["at"]
                        self.state["first_wire_call_id"] = event["call_id"]
                        self.state["first_checkpoint_due_at"] = event["at"] + 18000
                        write_private(self.report, self.state)

    def begin_call(self, task_id, input_bytes, system, now=None):
        now = time.time() if now is None else now
        with self.lock:
            call_id = uuid.uuid4().hex
            previous = self.last_calls.get(task_id)
            self.append(
                "calls.jsonl",
                {
                    "event": "call_start",
                    "at": now,
                    "call_id": call_id,
                    "task_id": task_id,
                    "requested_model": "glm-5.3",
                    "requested_effort": "max",
                    "input_sha256": digest(input_bytes),
                    "system_sha256": digest(system.encode()),
                    "previous_call_id": previous,
                    "retry_parent": previous
                    if self.last_errors.get(previous)
                    else None,
                },
            )
            self.last_calls[task_id] = call_id
            self.last_errors[call_id] = True
            return call_id

    def end_call(self, call_id, *, usage, stop_reason, action_kind, error, now=None):
        with self.lock:
            self.append(
                "calls.jsonl",
                {
                    "event": "call_end",
                    "at": time.time() if now is None else now,
                    "call_id": call_id,
                    "usage": usage,
                    "stop_reason": stop_reason,
                    "action_kind": action_kind,
                    "error": error,
                },
            )
            self.last_errors[call_id] = error is not None
            self.sync_wire()

    def observe(self, quota, state, safe_limits=(), now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.sync_wire()
            observed = quota.get("observed_at")
            used = quota.get("used_percent")
            valid = (
                quota.get("status") == "known"
                and type(observed) in (int, float)
                and -30 <= now - observed <= 180
                and type(used) in (int, float)
                and math.isfinite(used)
                and 0 <= used <= 100
            )
            counts = dict(Counter(t["status"] for t in state.get("tasks", {}).values()))
            supply_known = state.get("supply_known", True)
            sample = {
                "at": now,
                "observed_at": observed,
                "used_percent": used if valid else None,
                "quota_fresh": valid,
                "reset_hint": quota.get("reset_at"),
                "safe_limits": list(safe_limits),
                "task_status_counts": counts,
                "desired": state.get("desired"),
                "supply_empty": not any(
                    counts.get(k, 0)
                    for k in (
                        "queued",
                        "running",
                        "retrying",
                        "waiting_compute",
                        "waiting_quota",
                        "quota_unknown",
                    )
                )
                if supply_known
                else None,
                "supply_known": supply_known,
                "account_attribution": "shared_unknown",
            }
            curve_bucket = int(now // 300)
            if self.state["last_curve_bucket"] != curve_bucket:
                self.append("quota-curve.jsonl", {"event": "quota_sample", **sample})
                self.state["last_curve_bucket"] = curve_bucket
            t0 = self.state["t0"]
            elapsed = max(0, now - t0) if t0 is not None else None
            verdict = (
                "quota_unknown"
                if not valid
                else "target_met"
                if used >= 60
                else "minimum_met"
                if used >= 50
                else "below_minimum"
            )
            checkpoint = int(elapsed // 18000) if elapsed is not None else 0
            if checkpoint > self.state["last_checkpoint"]:
                for index in range(self.state["last_checkpoint"] + 1, checkpoint + 1):
                    due = t0 + index * 18000
                    on_time = 0 <= now - due <= 180
                    if on_time and valid and observed < due:
                        break  # Wait for the next actual provider observation, not a pre-deadline value.
                    result = {
                        "event": "five_hour_checkpoint",
                        "index": index,
                        "due_at": due,
                        "verdict": verdict if on_time else "missed_observation",
                        "passed": bool(on_time and valid and used >= 50),
                        "warmup_exemption": False,
                        **sample,
                    }
                    self.append("quota-checkpoints.jsonl", result)
                    self.state["last_checkpoint"] = index
                    self.state["last_checkpoint_result"] = result
            evaluation_bucket = int(elapsed // 900) if elapsed is not None else None
            if (
                evaluation_bucket is not None
                and evaluation_bucket != self.state["last_evaluation_bucket"]
            ):
                self.append(
                    "quota-evaluations.jsonl",
                    {
                        "event": "fifteen_minute_evaluation",
                        "elapsed_seconds": elapsed,
                        "verdict": verdict,
                        **sample,
                    },
                )
                self.state["last_evaluation_bucket"] = evaluation_bucket
            self.state.update(
                latest={"verdict": verdict, "elapsed_seconds": elapsed, **sample}
            )
            write_private(self.report, self.state)
            return {
                k: self.state[k]
                for k in (
                    "t0",
                    "target_percent",
                    "minimum_percent",
                    "latest",
                    "last_checkpoint",
                )
            }
