#!/usr/bin/env python3
"""Isolated framework acceptance, never a production research runner.

Uses native Deep Agents tools/loop and PostgreSQL checkpointer. Docker adapter
exists only for this disposable test; all model-written code runs without
network, credentials, Docker socket or repository mounts.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import base64
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from langchain_core.callbacks import BaseCallbackHandler
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from research_expression import validate


class Evidence(BaseCallbackHandler):
    """Store observable tools/text/usage, excluding prompts and private reasoning."""

    def __init__(self, root: Path, phase: str):
        self.path = root / f"{phase}-events.jsonl"
        self.records = []

    def record(self, kind, **values):
        row = {"at": time.time(), "kind": kind, **values}
        self.records.append(row)
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self.record(
            "tool_start",
            name=serialized.get("name"),
            call_id=str(run_id),
            arguments=input_str,
        )

    def on_tool_end(self, output, *, run_id, **kwargs):
        self.record(
            "tool_end",
            call_id=str(run_id),
            output=str(getattr(output, "content", output))[:12000],
        )

    def on_tool_error(self, error, *, run_id, **kwargs):
        self.record("tool_error", call_id=str(run_id), error_type=type(error).__name__)

    def on_llm_end(self, response, **kwargs):
        for group in response.generations:
            for result in group:
                msg = getattr(result, "message", None)
                if msg:
                    self.record(
                        "model_end",
                        usage=msg.usage_metadata,
                        finish=msg.response_metadata.get("finish_reason"),
                    )


class DisposableDockerSandbox(BaseSandbox):
    """Minimal standard backend adapter; one isolated container per command.

    ponytail: no daemon/job database; this is a bounded single-process test.
    Product code must use the existing managed job service for crash recovery.
    """

    def __init__(self, root: Path, evidence: Evidence):
        self.root, self.evidence = root, evidence
        self.active: set[str] = set()
        atexit.register(self.close)
        self.image = subprocess.check_output(
            ["docker", "image", "inspect", "python:3.11-slim", "--format", "{{.Id}}"],
            text=True,
        ).strip()

    @property
    def id(self):
        return "qm-spike-" + hashlib.sha256(str(self.root).encode()).hexdigest()[:12]

    def command(self, command):
        name = self.id + "-" + uuid.uuid4().hex[:8]
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            "quantmind.purpose=deepagents-validation",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "128m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "32",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,nosuid,size=16m",
            "-v",
            f"{self.root}:/workspace:rw",
            "-w",
            "/workspace",
            self.image,
            "sh",
            "-c",
            command,
        ]
        self.active.add(name)
        self.evidence.record(
            "container_submit",
            name=name,
            image=self.image,
            network="none",
            workspace=str(self.root),
        )
        return name, args

    def cleanup(self, name):
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
        probe = subprocess.run(
            ["docker", "inspect", name], capture_output=True, timeout=10
        )
        self.evidence.record(
            "container_cleanup", name=name, absent=probe.returncode != 0
        )
        self.active.discard(name)

    def close(self):
        for name in tuple(self.active):
            self.cleanup(name)

    def execute(self, command: str, *, timeout=None):
        name, args = self.command(command)
        try:
            p = subprocess.run(
                args, capture_output=True, timeout=min(timeout or 60, 60)
            )
            return ExecuteResponse(
                (p.stdout + p.stderr).decode(errors="replace")[:24000], p.returncode
            )
        finally:
            self.cleanup(name)

    async def aexecute(self, command: str, *, timeout=None):
        name, args = self.command(command)
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(), min(timeout or 60, 60)
            )
            return ExecuteResponse(
                output.decode(errors="replace")[:24000], process.returncode
            )
        finally:
            await asyncio.to_thread(self.cleanup, name)
            await process.wait()

    def upload_files(self, files):
        result = []
        for path, content in files:
            encoded = base64.b64encode(content).decode()
            code = f"import pathlib,base64;pathlib.Path({path!r}).write_bytes(base64.b64decode({encoded!r}))"
            response = self.execute("python -c " + shlex.quote(code))
            result.append(
                FileUploadResponse(
                    path=path,
                    error=None if response.exit_code == 0 else "permission_denied",
                )
            )
        return result

    def download_files(self, paths):
        result = []
        for path in paths:
            code = f"import pathlib,base64;print(base64.b64encode(pathlib.Path({path!r}).read_bytes()).decode())"
            response = self.execute("python -c " + shlex.quote(code))
            result.append(
                FileDownloadResponse(
                    path=path,
                    content=base64.b64decode(response.output.strip())
                    if response.exit_code == 0
                    else None,
                    error=None if response.exit_code == 0 else "file_not_found",
                )
            )
        return result


@tool
def validate_factor(expression: str) -> dict:
    """Use QuantMind's real causal expression validator with the price column.

    Returns a validation error as evidence, so the agent can correct its proposal.
    This validates syntax/causality only; no market data or backtest is run.
    """
    try:
        return {"valid": True, **validate(expression, ["price"])}
    except (ValueError, SyntaxError) as exc:
        return {"valid": False, "error": str(exc)}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def visible_text(message):
    if isinstance(message.content, str):
        return message.content
    return "".join(
        b.get("text", "") for b in message.content if b.get("type") == "text"
    )


async def run(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    workspace.chmod(0o777)  # Unprivileged disposable container writes only here.
    evidence = Evidence(root, args.phase)
    evidence.record(
        "invocation",
        phase=args.phase,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    credentials = json.loads(Path(args.credentials).read_text())
    # No API keys in env, subprocesses, serialized graph context or evidence.
    model = ChatOpenAI(
        model=args.model,
        api_key=credentials["api_key"],
        base_url=credentials["base_url"],
        use_responses_api=False,
        reasoning_effort="low",
        max_tokens=12000,
        timeout=90,
        max_retries=2,
        streaming=True,
        stream_usage=True,
    )
    register_harness_profile(
        "openai",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            excluded_tools=frozenset({"task"}),
        ),
    )
    sandbox = DisposableDockerSandbox(workspace, evidence)
    background_jobs = []

    @tool
    def start_waiting_job() -> dict:
        """Start one disposable 60-second fixture in the background; not a research job."""
        if background_jobs:
            return {"job_id": background_jobs[0], "reused": True}
        name, command = sandbox.command("python -c 'import time; time.sleep(60)'")
        command.insert(2, "--detach")
        subprocess.run(command, check=True, capture_output=True, timeout=15)
        background_jobs.append(name)
        return {
            "job_id": name,
            "status": "running",
            "purpose": "background-message-test",
        }

    @tool
    def waiting_job_status() -> dict:
        """Read the actual status of this test's background job; does not stop it."""
        if not background_jobs:
            return {"status": "not_started"}
        p = subprocess.run(
            ["docker", "inspect", background_jobs[0], "--format", "{{.State.Running}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"job_id": background_jobs[0], "running": p.stdout.strip() == "true"}

    extra_tools = (
        [start_waiting_job, waiting_job_status]
        if args.phase == "background_message"
        else []
    )
    config = {
        "configurable": {"thread_id": args.thread},
        "callbacks": [evidence],
        "recursion_limit": 40,
    }
    versions = {
        p: importlib.metadata.version(p)
        for p in [
            "deepagents",
            "langgraph",
            "langchain-openai",
            "langchain-core",
            "langgraph-checkpoint-postgres",
            "psycopg",
        ]
    }
    save(root / "versions.json", {"packages": versions, "image": sandbox.image})
    async with AsyncPostgresSaver.from_conn_string(args.database) as saver:
        await saver.setup()
        agent = create_deep_agent(
            model=model,
            tools=[validate_factor, *extra_tools],
            backend=sandbox,
            middleware=[TodoListMiddleware()],
            checkpointer=saver,
            interrupt_on={"validate_factor": True}
            if args.phase in {"approval", "approve_restart"}
            else None,
            system_prompt=(
                "You are a framework acceptance agent, not a market researcher. "
                "Use only /workspace for files. No networking, delegation or external data. "
                "Use actual tools; do not claim success before reading results. Keep replies brief. "
                "This test uses only synthetic numbers and the existing QuantMind validation function."
            ),
        )
        exposed_tools = sorted(agent.get_graph().nodes["tools"].data.tools_by_name)
        assert "task" not in exposed_tools and "write_todos" in exposed_tools
        evidence.record("exposed_tools", names=exposed_tools)

        async def stream(payload):
            chunks = 0
            async for mode, chunk in agent.astream(
                payload, config, stream_mode=["updates", "messages"]
            ):
                if mode == "messages":
                    msg, _ = chunk
                    text = visible_text(msg)
                    if text:
                        chunks += 1
                        evidence.record("text_delta", text=text)
                else:
                    evidence.record("state_update", nodes=list(chunk))
            state = await agent.aget_state(config)
            messages = state.values.get("messages", [])
            result = {
                "phase": args.phase,
                "model": args.model,
                "chunks": chunks,
                "next": state.next,
                "message_count": len(messages),
                "answer": visible_text(messages[-1]) if messages else "",
                "tool_calls": [
                    {"name": c["name"], "args": c["args"]}
                    for m in messages
                    for c in getattr(m, "tool_calls", [])
                ],
            }
            save(root / f"{args.phase}-result.json", result)
            return result

        if args.phase == "smoke":
            fixture = {"marker": uuid.uuid4().hex, "values": [2, 4, 8]}
            save(workspace / "fixture.json", fixture)
            result = await stream(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "Do this small acceptance task using actual tools. First make a todo list. "
                                "Validate lag(price,-1); read the error, then fix it to a causal lag and validate again. "
                                "Read /workspace/fixture.json. Write /workspace/analyze.py using standard Python; "
                                "it must load fixture.json and save /workspace/result.json containing marker, count, "
                                "sum, mean calculated from the values. Execute it and read the result. "
                                "Remember the fixture marker for a later conversation. End with the computed result."
                            )
                        )
                    ]
                }
            )
            actual = json.loads((workspace / "result.json").read_text())
            assert actual["marker"] == fixture["marker"]
            assert actual["count"] == 3 and actual["sum"] == 14
            assert abs(actual["mean"] - 14 / 3) < 1e-9
            names = {c["name"] for c in result["tool_calls"]}
            assert {"validate_factor", "write_file", "read_file", "execute"} <= names
            assert "task" not in names
            assert (
                sum(c["name"] == "validate_factor" for c in result["tool_calls"]) >= 2
            )
        elif args.phase == "resume":
            before = await agent.aget_state(config)
            assert before.values.get("messages"), (
                "No durable state from previous process"
            )
            result = await stream(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "We restarted the process. Without calling tools, recall the fixture marker and sum "
                                "from our earlier conversation. Then acknowledge this new instruction: next we will "
                                "investigate missing values, not optimize returns. Do not execute new work."
                            )
                        )
                    ]
                }
            )
            fixture = json.loads((workspace / "fixture.json").read_text())
            assert fixture["marker"] in result["answer"]
            assert result["message_count"] > len(before.values["messages"])
        elif args.phase == "approval":
            result = await stream(
                {
                    "messages": [
                        HumanMessage(
                            content="Validate lag(price,1) using validate_factor."
                        )
                    ]
                }
            )
            assert result["next"], "Native HITL did not pause"
            assert not any(
                r["kind"] == "tool_start" and r.get("name") == "validate_factor"
                for r in evidence.records
            )
        elif args.phase == "approve_restart":
            state = await agent.aget_state(config)
            assert state.next, (
                "Missing persisted approval checkpoint from earlier process"
            )
            result = await stream(Command(resume={"decisions": [{"type": "approve"}]}))
            assert not result["next"]
            assert any(
                r["kind"] == "tool_start" and r.get("name") == "validate_factor"
                for r in evidence.records
            )
        elif args.phase == "interrupt":
            marker = workspace / "running.txt"
            assert not marker.exists(), "Use a fresh output directory for interrupt"
            task = asyncio.create_task(
                stream(
                    {
                        "messages": [
                            HumanMessage(
                                content=(
                                    "Call execute immediately, no planning or other tools, to run Python that writes "
                                    "/workspace/running.txt with 'started', sleeps 45 seconds, then writes "
                                    "/workspace/should-not-exist.txt. This is a cancellation fixture."
                                )
                            )
                        ]
                    }
                )
            )
            async with asyncio.timeout(120):
                while not marker.exists() and not task.done():
                    await asyncio.sleep(0.05)
            assert marker.exists(), "Model did not start actual cancellable work"
            t0 = time.monotonic()
            evidence.record("interrupt_requested", active=sorted(sandbox.active))
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            assert (
                not sandbox.active and not (workspace / "should-not-exist.txt").exists()
            )
            save(
                root / "interrupt-proof.json",
                {
                    "seconds": time.monotonic() - t0,
                    "remaining_containers": sorted(sandbox.active),
                    "late_file_exists": False,
                },
            )
            # Native interrupted graph can retain a pending tool call. Feed an explicit
            # tool cancellation result through the normal graph state API before steering.
            state = await agent.aget_state(config)
            from langchain_core.messages import ToolMessage

            answered = {
                m.tool_call_id
                for m in state.values.get("messages", [])
                if isinstance(m, ToolMessage)
            }
            pending = [
                c
                for m in state.values.get("messages", [])
                for c in getattr(m, "tool_calls", [])
                if c["id"] not in answered
            ]
            if pending:
                await agent.aupdate_state(
                    config,
                    {
                        "messages": [
                            ToolMessage(
                                content="Execution cancelled by user; do not retry it.",
                                tool_call_id=c["id"],
                                name=c["name"],
                                status="error",
                            )
                            for c in pending
                        ]
                    },
                    as_node="tools",
                )
            result = await stream(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "I interrupted the sleep task. Do not restart it. Instead write /workspace/steered.txt "
                                "containing exactly 'check missing values next', then stop."
                            )
                        )
                    ]
                }
            )
            assert (
                workspace / "steered.txt"
            ).read_text().strip() == "check missing values next"
            assert not (workspace / "should-not-exist.txt").exists()
        elif args.phase == "background_message":
            await stream(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "First use write_todos to record two tasks: start the fixture, then await completion. "
                                "Call start_waiting_job exactly once, then return immediately with the job ID. "
                                "Do not wait, do not use execute. This tests discussion during background work."
                            )
                        )
                    ]
                }
            )
            assert len(background_jobs) == 1
            assert waiting_job_status.invoke({})["running"]
            evidence.record("user_message_received", message_id="mid-job-question")
            result = await stream(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "What is the job doing right now? Call waiting_job_status and explain that this "
                                "is a test fixture, not research. Keep it running and do not start anything else."
                            )
                        )
                    ]
                }
            )
            still_running = waiting_job_status.invoke({})["running"]
            evidence.record(
                "user_message_answered",
                message_id="mid-job-question",
                job_still_running=still_running,
            )
            assert still_running, "The reply waited until background work finished"
            assert len(background_jobs) == 1
            assert any(c["name"] == "write_todos" for c in result["tool_calls"])
            sandbox.close()
        elif args.phase == "model_interrupt":
            task = asyncio.create_task(
                stream(
                    {
                        "messages": [
                            HumanMessage(
                                content=(
                                    "No tools. Write a long tutorial of at least 1500 words about sorting algorithms. "
                                    "This is a streaming cancellation test."
                                )
                            )
                        ]
                    }
                )
            )
            async with asyncio.timeout(120):
                while (
                    not any(r["kind"] == "text_delta" for r in evidence.records)
                    and not task.done()
                ):
                    await asyncio.sleep(0.02)
            assert not task.done(), "No opportunity to interrupt a live response"
            t0 = time.monotonic()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            save(
                root / "model-interrupt-proof.json",
                {
                    "seconds": time.monotonic() - t0,
                    "stream_cancelled": True,
                    "provider_billing_stop": "unknown",
                },
            )
            result = await stream(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "I stopped the tutorial. Do not continue it. Reply only: cancellation acknowledged"
                            )
                        )
                    ]
                }
            )
            assert "cancellation acknowledged" in result["answer"].lower()
        else:
            raise ValueError(args.phase)
        save(
            root / f"{args.phase}-passed.json",
            {
                "passed": True,
                "model": args.model,
                "phase": args.phase,
                "versions": versions,
                "artifacts": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in workspace.iterdir()
                    if p.is_file()
                },
            },
        )
        print(
            json.dumps(
                {
                    "passed": True,
                    "phase": args.phase,
                    "model": args.model,
                    "output": str(root),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True)
    parser.add_argument(
        "--database", required=True, help="Disposable localhost PostgreSQL only"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument(
        "--phase",
        choices=[
            "smoke",
            "resume",
            "approval",
            "approve_restart",
            "interrupt",
            "model_interrupt",
            "background_message",
        ],
        required=True,
    )
    parser.add_argument("--model", default="glm-5.3-flash")
    args = parser.parse_args()
    if "@127.0.0.1:" not in args.database or not args.database.endswith(
        "/agent_validation"
    ):
        parser.error(
            "Only the disposable localhost agent_validation database is allowed"
        )
    asyncio.run(asyncio.wait_for(run(args), timeout=600))
