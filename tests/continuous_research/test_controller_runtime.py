"""Synthetic only: no Pi launch, credential access, provider traffic or services."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.continuous_research import controller
from scripts.continuous_research.runtime_trace import (
    GLM_THINKING_MAP,
    RuntimeTrace,
    SafeQuotaSession,
    project_provider,
)


def source():
    return {
        "baseUrl": "https://open.bigmodel.cn/api/coding/paas/v4",
        "api": "openai-completions",
        "apiKey": "must-not-copy",
        "models": [
            {
                "id": "glm-5.3",
                "reasoning": True,
                "maxTokens": 131072,
                "compat": {"supportsReasoningEffort": True, "thinkingFormat": "zai"},
            }
        ],
    }


def quota(now, used=60):
    return {
        "status": "known",
        "used_percent": used,
        "remaining_percent": 100 - used,
        "observed_at": now,
        "reset_at": now + 100,
    }


class ControllerRuntimeTests(unittest.TestCase):
    def test_projection_keeps_max_and_refuses_clamping_configuration(self):
        original = source()
        projected = project_provider(original)
        self.assertEqual(projected["models"][0]["thinkingLevelMap"], GLM_THINKING_MAP)
        self.assertNotIn("must-not-copy", json.dumps(projected))
        self.assertNotIn("thinkingLevelMap", original["models"][0])
        original["models"][0]["thinkingLevelMap"] = {"max": "max", "high": "high"}
        self.assertEqual(
            project_provider(original)["models"][0]["thinkingLevelMap"],
            original["models"][0]["thinkingLevelMap"],
        )
        for edit in (
            lambda s: s["models"][0].update(thinkingLevelMap={"max": "high"}),
            lambda s: s["models"][0]["compat"].update(supportsReasoningEffort=False),
            lambda s: s.update(baseUrl="https://example.invalid"),
        ):
            broken = copy.deepcopy(original)
            edit(broken)
            with self.assertRaises(ValueError):
                project_provider(broken)

    def test_private_call_trace_retry_and_restart_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            first = trace.begin_call("task", b"PRIVATE-PROMPT", "PRIVATE-SYSTEM", 1000)
            self.assertIsNone(trace.state["t0"])
            trace.end_call(
                first,
                usage={"input": 7, "cacheRead": 11, "cacheWrite": 2, "output": 3},
                stop_reason="error",
                action_kind=None,
                error="retrying",
                now=1002,
            )
            restored = RuntimeTrace(trace.root, "programme")
            second = restored.begin_call(
                "task", b"PRIVATE-PROMPT", "PRIVATE-SYSTEM", 1003
            )
            events = trace.read_events(trace.calls)
            self.assertEqual(events[-1]["retry_parent"], first)
            self.assertNotEqual(second, first)
            self.assertNotIn("PRIVATE", trace.calls.read_text())
            self.assertEqual(trace.calls.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                RuntimeTrace(trace.root, "another-programme")

    def test_installed_pi_pure_clamp_supports_projected_max(self):
        ai = Path(
            "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist"
        )
        if not (ai / "models.js").exists():
            self.skipTest(
                "Pi not installed; pure-function verification runs on the Pi host"
            )
        js = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const base = process.argv[1];
const source = fs.readFileSync(base + '/models.js', 'utf8');
const start = source.indexOf('const EXTENDED_THINKING_LEVELS =');
const end = source.indexOf('/**', start);
assert.ok(start >= 0 && end > start);
const functions = vm.runInNewContext(source.slice(start,end).replaceAll('export function ', 'function ') +
 '\n({clampThinkingLevel})', Object.create(null), {timeout:1000});
const model = JSON.parse(process.argv[2]);
const builtin = JSON.parse(fs.readFileSync(base + '/providers/data/zai-coding-cn.json','utf8'))['openai-completions']['glm-5.3'];
assert.deepEqual(model.thinkingLevelMap,builtin.thinkingLevelMap);
assert.equal(functions.clampThinkingLevel(model,'max'),'max');
delete model.thinkingLevelMap;
assert.equal(functions.clampThinkingLevel(model,'max'),'high');
"""
        result = subprocess.run(
            [
                "node",
                "-e",
                js,
                str(ai),
                json.dumps(project_provider(source())["models"][0]),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_spawn_failure_has_no_t0_and_retry_preserves_call_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = controller.Controller.__new__(controller.Controller)
            worker.trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            worker.credential = lambda: (_ for _ in ()).throw(RuntimeError("no_auth"))
            worker.home = Path(tmp)
            with self.assertRaises(RuntimeError):
                worker.model({}, {"id": "task"})
            self.assertIsNone(worker.trace.state["t0"])
            events = worker.trace.read_events(worker.trace.calls)
            self.assertEqual([e["event"] for e in events], ["call_start", "call_end"])
            self.assertEqual(events[-1]["error"], "controller_interrupted")

    def test_wire_hook_actual_fetch_whitelist_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            call = trace.begin_call("task", b"context", "system", 10)
            hook = Path(controller.__file__).with_name("wire_trace.cjs")
            js = r"""
const assert = require('node:assert/strict');
let forwarded = 0;
globalThis.fetch = async (_url, _init) => { forwarded++; return {ok:true}; };
require(process.argv[1]);
(async () => {
 for (const body of [{model:'glm-5.3',reasoning_effort:'high'},
                     {model:'glm-5.3'}, {model:'other',reasoning_effort:'max'}]) {
   await assert.rejects(fetch('https://open.bigmodel.cn/api/coding/paas/v4/chat/completions',
                             {body:JSON.stringify(body)}), /glm_wire_model_effort_mismatch/);
 }
 assert.equal(forwarded,0);
 const unrelated = {get body() { throw Error('must not inspect other fetch body'); }};
 await fetch('https://example.invalid/metadata', unrelated);
 await fetch('https://open.bigmodel.cn/api/coding/paas/v4/chat/completions',
   {headers:{Authorization:'SECRET-KEY'}, body:JSON.stringify({model:'glm-5.3',
    reasoning_effort:'max', max_tokens:131072,messages:['PRIVATE-PROMPT'],thinking:'PRIVATE-THINKING'})});
 assert.equal(forwarded,2);
})().catch(() => {process.exitCode=1;});
"""
            result = subprocess.run(
                ["node", "-e", js, str(hook)],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "QM_TRACE_CALL_ID": call,
                    "QM_TRACE_WIRE_FILE": str(trace.wire),
                },
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            trace.sync_wire()
            (event,) = trace.read_events(trace.wire)
            self.assertEqual(event["model"], "glm-5.3")
            self.assertEqual(event["reasoning_effort"], "max")
            self.assertEqual(event["max_tokens"], 131072)
            self.assertEqual(trace.state["t0"], event["at"])
            self.assertNotIn("PRIVATE", trace.wire.read_text())
            self.assertNotIn("SECRET", trace.wire.read_text())
            self.assertEqual(trace.wire.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                RuntimeTrace(trace.root, "programme").state["t0"], event["at"]
            )

    def test_controller_preload_launches_with_unicode_and_spaces_in_path(self):
        with tempfile.TemporaryDirectory(prefix="GLM 研究 ") as tmp:
            root = Path(tmp)
            (root / "wire_trace.cjs").write_bytes(
                Path(controller.__file__).with_name("wire_trace.cjs").read_bytes()
            )
            worker = controller.Controller.__new__(controller.Controller)
            worker.home = root
            worker.pi = "not-executed"
            worker.trace = RuntimeTrace(root / "trace", "programme")
            worker.credential = lambda: "synthetic-not-a-key"
            worker.children = {}
            worker.child_lock = threading.Lock()
            original_popen = subprocess.Popen
            started = []

            def offline_node(_argv, **kwargs):
                # Execute the real NODE_OPTIONS parser and preload, without Pi,
                # a provider request, or any credential access.
                process = original_popen(["node", "--version"], **kwargs)
                started.append(process)
                return process

            with (
                patch.object(controller, "__file__", str(root / "controller.py")),
                patch.object(controller.subprocess, "Popen", side_effect=offline_node),
            ):
                worker.model({}, {"id": "task"})
            self.assertEqual(started[0].returncode, 0)
            self.assertFalse(worker.trace.wire.exists())
            self.assertIsNone(worker.trace.state["t0"])

    def test_rolling_checkpoint_empty_supply_unknown_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            trace.append(
                "wire.jsonl",
                {"event": "wire_request", "call_id": "natural", "at": 1000},
            )
            trace.sync_wire()
            empty = {"desired": "running", "tasks": {}}
            trace.observe(quota(1000, 70), empty, now=1000)
            trace.observe(quota(1010, 69), empty, now=1010)
            self.assertEqual(
                len(trace.read_events(trace.root / "quota-curve.jsonl")), 1
            )
            trace = RuntimeTrace(trace.root, "programme")
            trace.observe(quota(19000, 49), empty, now=19000)
            (checkpoint,) = trace.read_events(trace.root / "quota-checkpoints.jsonl")
            self.assertFalse(checkpoint["passed"])
            self.assertFalse(checkpoint["warmup_exemption"])
            self.assertTrue(checkpoint["supply_empty"])
            self.assertEqual(checkpoint["verdict"], "below_minimum")
            trace.observe({"status": "unknown"}, empty, now=37000)
            self.assertEqual(
                trace.read_events(trace.root / "quota-checkpoints.jsonl")[-1][
                    "verdict"
                ],
                "quota_unknown",
            )
            trace.observe(quota(55000, 60), empty, now=55000)
            self.assertTrue(
                trace.read_events(trace.root / "quota-checkpoints.jsonl")[-1]["passed"]
            )
            self.assertEqual(trace.state["t0"], 1000)
            self.assertEqual(
                trace.state["latest"]["account_attribution"], "shared_unknown"
            )
            trace.observe(quota(74000, 70), empty, now=74000)
            self.assertEqual(
                trace.read_events(trace.root / "quota-checkpoints.jsonl")[-1][
                    "verdict"
                ],
                "missed_observation",
            )

    def test_no_success_from_pre_deadline_or_stale_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            trace.append(
                "wire.jsonl",
                {"event": "wire_request", "call_id": "natural", "at": 1000},
            )
            trace.observe(quota(18990, 90), {"tasks": {}}, now=19000)
            self.assertFalse((trace.root / "quota-checkpoints.jsonl").exists())
            trace.observe(quota(19010, 60), {"tasks": {}}, now=19010)
            self.assertTrue(
                trace.read_events(trace.root / "quota-checkpoints.jsonl")[-1]["passed"]
            )
            trace.observe(quota(36000, 90), {"tasks": {}}, now=37000)
            self.assertFalse(
                trace.read_events(trace.root / "quota-checkpoints.jsonl")[-1]["passed"]
            )

    def test_crash_after_checkpoint_append_cannot_upgrade_failed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            trace.append(
                "wire.jsonl",
                {"event": "wire_request", "call_id": "natural", "at": 1000},
            )
            trace.sync_wire()
            # Crash between fsynced checkpoint append and latest-report replacement.
            trace.append(
                "quota-checkpoints.jsonl",
                {"index": 1, "passed": False, "verdict": "below_minimum"},
            )
            restarted = RuntimeTrace(trace.root, "programme")
            restarted.observe(quota(19010, 90), {"tasks": {}}, now=19010)
            self.assertFalse(restarted.state["last_checkpoint_result"]["passed"])
            self.assertEqual(
                len(restarted.read_events(trace.root / "quota-checkpoints.jsonl")), 1
            )

    def test_model_json_usage_is_split_and_no_wire_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = controller.Controller.__new__(controller.Controller)
            worker.trace = RuntimeTrace(Path(tmp) / "trace", "programme")
            worker.home = Path(tmp)
            worker.pi = "must-not-execute"
            worker.credential = lambda: "SECRET-KEY"
            worker.children = {}
            worker.child_lock = threading.Lock()
            msg = {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "usage": {
                        "input": 7,
                        "cacheRead": 11,
                        "cacheWrite": 2,
                        "output": 3,
                    },
                    "content": [
                        {"type": "thinking", "thinking": "PRIVATE-THINKING"},
                        {
                            "type": "text",
                            "text": '{"action":"report","text":"PRIVATE-RESULT"}',
                        },
                    ],
                },
            }
            wire_enabled = True

            class Child:
                def __init__(self, argv, **kwargs):
                    self.env = kwargs["env"]
                    self.pid = 123
                    self.asserted = (
                        "--thinking" in argv
                        and argv[argv.index("--thinking") + 1] == "max"
                    )

                def communicate(self, data, timeout):
                    if wire_enabled:
                        worker.trace.append(
                            "wire.jsonl",
                            {
                                "event": "wire_request",
                                "at": 1000,
                                "call_id": self.env["QM_TRACE_CALL_ID"],
                            },
                        )
                    return json.dumps(msg).encode(), None

            with patch.object(controller.subprocess, "Popen", Child):
                action, error, usage = worker.model(
                    {"context": "PRIVATE-PROMPT"}, {"id": "task"}
                )
                self.assertIsNone(error)
                self.assertEqual(action["action"], "report")
                self.assertEqual(usage["input"], 20)
                end = worker.trace.read_events(worker.trace.calls)[-1]
                self.assertEqual(end["usage"]["input"], 7)
                self.assertEqual(end["usage"]["cacheRead"], 11)
                self.assertNotIn("PRIVATE", worker.trace.calls.read_text())
                self.assertNotIn("SECRET", worker.trace.calls.read_text())
                wire_enabled = False
                self.assertEqual(
                    worker.model({}, {"id": "task2"})[1], "wire_observation_missing"
                )

    def test_quota_raw_fields_drop_unrelated_payload(self):
        class Response:
            status_code = 200

            def json(self):
                return {
                    "data": {
                        "secret": "SECRET",
                        "limits": [
                            {
                                "type": "TOKENS_LIMIT",
                                "unit": 3,
                                "number": 5,
                                "percentage": 1,
                                "nextResetTime": 19000,
                                "credential": "SECRET",
                            }
                        ],
                    }
                }

        with patch("requests.Session.get", return_value=Response()):
            with SafeQuotaSession() as s:
                s.get("https://example.invalid")
                self.assertNotIn("SECRET", json.dumps(s.safe_limits))
                self.assertEqual(s.safe_limits[0]["percentage"], 1)


if __name__ == "__main__":
    unittest.main()
