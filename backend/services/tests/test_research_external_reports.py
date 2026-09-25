"""R01 external executor mode (P0.4)：登记、回报、幂等、乱序、readiness。

纯逻辑与路由行为都用 sidecar app 直测（不起 lifespan，DB 层替换为内存实现）。
全链 SQL/持久化验证见 artifacts/p04 的本地服务 API 序列证据。
"""

from __future__ import annotations

import sys
import types
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# ---- Stub heavy third-party imports unavailable on the host test env ----
for _name in (
    "deepagents",
    "deepagents.backends",
    "deepagents.backends.sandbox",
    "deepagents.backends.protocol",
    "deepagents.profiles",
    "langgraph",
    "langgraph.checkpoint",
    "langgraph.checkpoint.postgres",
    "langgraph.checkpoint.postgres.aio",
    "langchain",
    "langchain.agents",
    "langchain.agents.middleware",
    "psycopg",
    "psycopg.types",
    "psycopg.types.json",
    "psycopg.rows",
    "psycopg.conninfo",
    "psycopg_pool",
):
    if _name not in sys.modules:
        sys.modules[_name] = types.ModuleType(_name)
        sys.modules[_name].__path__ = []
sys.modules["deepagents"].create_deep_agent = MagicMock()
sys.modules["deepagents.profiles"].GeneralPurposeSubagentProfile = MagicMock()
sys.modules["deepagents.profiles"].HarnessProfile = MagicMock()
sys.modules["deepagents.profiles"].register_harness_profile = MagicMock()
sys.modules["deepagents.backends.sandbox"].BaseSandbox = object
sys.modules["deepagents.backends.protocol"].ExecuteResponse = MagicMock
sys.modules["deepagents.backends.protocol"].FileUploadResponse = MagicMock
sys.modules["deepagents.backends.protocol"].FileDownloadResponse = MagicMock
sys.modules["langchain.agents.middleware"].AgentMiddleware = object
sys.modules["langchain.agents.middleware"].TodoListMiddleware = object
sys.modules["langgraph.checkpoint.postgres.aio"].AsyncPostgresSaver = MagicMock()
sys.modules["psycopg"].AsyncConnection = MagicMock()
sys.modules["psycopg.types.json"].Jsonb = lambda value: value
sys.modules["psycopg.rows"].dict_row = lambda cursor: None
sys.modules["psycopg.conninfo"].make_conninfo = lambda **kw: ""
sys.modules["psycopg_pool"].AsyncConnectionPool = MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

from backend.services.research_agent import external  # noqa: E402
from backend.services.research_agent.app import app  # noqa: E402
from backend.services.research_agent.store import digest, enqueue, event  # noqa: E402

OWNER = ("default", "10000001")
NODE = "mac"


class FakeSettings:
    node = NODE
    internal_secret = "test-internal"
    external_stale_after = 21600.0
    external_contract_node = NODE
    models = ["glm-5.3-flash"]

    def workspace(self, ident):
        return pytest.workspace_root

    def inventory(self):
        return {"note": "test"}


class FakeCursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class FakeDB:
    """Minimal psycopg-alike: only the statements the sidecar routes issue."""

    def __init__(self, store):
        self.store = store

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, sql, params=None):
        if "FROM research_drafts WHERE draft_id=%s FOR UPDATE" in sql:
            row = self.store.rows.get(params[0])
            return FakeCursor(dict(row) if row else None)
        if sql.startswith("UPDATE research_drafts"):
            return FakeCursor(None)
        raise AssertionError(f"unexpected SQL in fake: {sql[:80]}")


class FakePool:
    def __init__(self, store):
        self.store = store

    @asynccontextmanager
    async def connection(self):
        yield FakeDB(self.store)


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.pool = FakePool(self)

    async def get(self, ident, owner=None, node=None):
        row = self.rows.get(ident)
        if (
            not row
            or (owner and (row["tenant_id"], row["user_id"]) != owner)
            or (node and row["node_id"] != node)
        ):
            raise KeyError
        return row

    async def list(self, owner, node):
        return [r for r in self.rows.values() if (r["tenant_id"], r["user_id"]) == owner]

    @asynccontextmanager
    async def edit(self, ident, owner=None, node=None):
        row = await self.get(ident, owner, node)
        yield row["state"]

    async def create(self, owner, node, data, inventory, engine="deepagents", external=None):
        hashed = digest([engine, data["key"]])
        for row in self.rows.values():
            if (row["tenant_id"], row["user_id"], row["node_id"], row["input_hash"]) == (*owner, node, hashed):
                if row["state"]["payload_hash"] != digest(data):
                    raise ValueError("重复请求的内容不同")
                return row["draft_id"]
        ident = uuid.uuid4().hex
        s = {
            "engine": engine, "input": data, "payload_hash": digest(data),
            "node_id": node, "inventory": inventory, "status": "idle",
            "generation": 0, "messages": [], "inbox": [], "plans": [],
            "approval": None, "jobs": {}, "outcomes": [], "events": [],
            "sequence": 0, "requests": {}, "todos": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "created_at": 0.0, "error": None,
        }
        if engine == "external":
            s["status"] = "registered"
            s["external"] = external
        self.rows[ident] = {
            "draft_id": ident, "tenant_id": owner[0], "user_id": owner[1],
            "node_id": node, "input_hash": hashed, "state": s,
        }
        return ident


class FakeExternalStore(external.ExternalStore):
    def __init__(self):
        super().__init__(None)
        self.events = {}  # (draft, task, run, event_id) -> record
        self.readiness = {}
        self.bindings = {}
        self.contract_hash = external.Contracts().contract_hashes["2.3"]

    async def find_event(self, db, draft_id, source_task, source_run_id, event_id):
        return self.events.get((draft_id, source_task, source_run_id, event_id))

    async def insert_event(self, db, owner, node, draft_id, envelope, payload_hash,
                           received_at, apply_status, apply_note=None):
        key = (draft_id, envelope["source_task"], envelope["source_run_id"], envelope["event_id"])
        self.events[key] = {
            "id": len(self.events) + 1, "kind": envelope["kind"], "payload": envelope,
            "payload_hash": payload_hash,
            "received_at": datetime.now(timezone.utc), "apply_status": apply_status,
            "apply_note": apply_note, "confirmed_at": None, "confirmed_by": None,
        }
        return len(self.events)

    async def stream(self, owner, node, draft_id, since_seq=0, limit=500):
        rows = [
            external.event_row_public(r)
            for (d, *_), r in sorted(self.events.items(), key=lambda kv: kv[1]["id"])
            if d == draft_id and r["id"] > since_seq
        ]
        return rows[:limit]

    async def find_event_by_event_id(self, owner, node, draft_id, event_id):
        for (d, _, _, eid), r in self.events.items():
            if d == draft_id and eid == event_id:
                return r
        return None

    async def confirm_resume(self, owner, node, draft_id, event_id, user):
        for (d, _, _, eid), r in self.events.items():
            if d == draft_id and eid == event_id:
                if r["confirmed_at"]:
                    return external.event_row_public(r), True
                r["confirmed_at"] = datetime.now(timezone.utc)
                r["confirmed_by"] = user
                return external.event_row_public(r), False
        return None

    async def get_readiness(self, owner, node, project_key):
        return self.readiness.get((owner, node, project_key))

    async def get_acceptance_binding(self, owner, node, project_key):
        return self.bindings.get((owner, node, project_key))

    async def save_readiness(self, owner, node, project_key, obj, contract_hash=None):
        key = (owner, node, project_key)
        prior = self.readiness.get(key)
        prior_status = (
            (prior or {}).get("independent_acceptance", {}).get("status")
        )
        verdict = obj.get("independent_acceptance", {}).get("status")
        binding = self.bindings.get(key)
        if verdict == "passed":
            if prior_status != "passed" or not isinstance(binding, dict):
                binding = external.acceptance_binding_from(
                    obj, contract_hash or self.contract_hash
                )
        else:
            binding = None
        self.readiness[key] = obj
        self.bindings[key] = binding


@pytest.fixture()
def env(tmp_path):
    (tmp_path / "external").mkdir()
    pytest.workspace_root = tmp_path
    store, xstore = FakeStore(), FakeExternalStore()
    app.state.settings = FakeSettings()
    app.state.store = store
    app.state.external = xstore
    app.state.contracts = external.Contracts()
    client = TestClient(app)
    client.headers.update(
        {
            "x-internal-call": "test-internal",
            "x-user-id": OWNER[1],
            "x-tenant-id": OWNER[0],
            "x-research-node": NODE,
        }
    )
    client.store, client.xstore = store, xstore
    yield client
    pytest.workspace_root = None


def envelope(client, **over):
    base = {
        "schema_version": 2,
        "project_key": "r01",
        "workstream": "P0",
        "case_id": client.case_id,
        "source_task": "R01P0-W2P",
        "source_run_id": "run-1",
        "strategy_id": "fixture-risk-line-demo",
        "contract_version": "2.3",
        "contract_hash": external.Contracts().contract_hashes["2.3"],
        "source_node": NODE,
        "source_revision": "abc123",
        "event_id": "ev-1",
        "seq": 0,
        "kind": "progress",
        "data": {"input_package_id": "none", "data_as_of": "2026-09-24"},
        "timestamps": {"source_at": "2026-09-25T10:00:00Z"},
        "execution_status": "running",
        "evidence_stage": "proposal",
        "fixture": True,
        "progress_step": {"step_id": "s1", "title": "回报路由", "status": "in_progress"},
    }
    base.update(over)
    return base


def register_case(client, workstream="P0", key="case-key-0001"):
    response = client.post(
        "/cases",
        json={
            "key": key,
            "question": "R01 P0 平台通路开发",
            "subject": "external reports",
            "executor_kind": "external",
            "project_key": "r01",
            "workstream": workstream,
        },
    )
    assert response.status_code == 200, response.text
    client.case_id = response.json()["id"]
    return response.json()


def submit(client, payload):
    return client.post(f"/cases/{client.case_id}/external-reports", json=payload)


class TestExternalRegistration:
    def test_create_external_case_enqueues_nothing(self, env):
        body = register_case(env)
        assert body["executor_kind"] == "external"
        assert body["status"] == "registered"
        assert body["external"]["workstream"] == "P0"
        state = env.store.rows[env.case_id]["state"]
        assert state["engine"] == "external"
        assert state["inbox"] == [] and state["messages"] == []
        assert state["approval"] is None
        assert state["jobs"] == {}

    def test_builtin_create_still_enqueues_model_discussion(self, env):
        response = env.post(
            "/cases",
            json={"key": "builtin-key-1", "question": "普通课题", "model": "glm-5.3-flash"},
        )
        assert response.status_code == 200
        state = env.store.rows[response.json()["id"]]["state"]
        assert state["engine"] == "deepagents"
        assert state["inbox"] and state["status"] == "queued"  # regression guard

    def test_builtin_routes_reject_external_case(self, env):
        register_case(env)
        for path, payload in (
            ("/messages", {"key": "msg-key-01", "content": "hi"}),
            ("/approve", {"key": "appr-key1", "version": 1, "reviewed": True}),
        ):
            assert env.post(f"/cases/{env.case_id}{path}", json=payload).status_code == 409

    def test_approval_window_still_capped_at_8h(self):
        import pydantic

        from backend.services.research_agent.app import Approval

        with pytest.raises(pydantic.ValidationError):
            Approval(key="k12345678", version=1, reviewed=True, hours=9)
        Approval(key="k12345678", version=1, reviewed=True, hours=8)  # 单窗口上限不变
        # 外部课题不走该窗口：登记即用，无 approval 对象（见 create 测试）


class TestReportValidation:
    def test_valid_progress_report_applies(self, env):
        register_case(env)
        response = submit(env, envelope(env))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "applied"
        assert body["received_at"].endswith("Z")
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["execution_status"] == "running"
        assert state["external"]["progress"]["s1"]["title"] == "回报路由"

    def test_case_and_workstream_binding(self, env):
        register_case(env)
        assert submit(env, envelope(env, case_id="other-case")).status_code == 422
        assert submit(env, envelope(env, workstream="A")).status_code == 422

    def test_node_mismatch_rejected(self, env):
        register_case(env)
        response = submit(env, envelope(env, source_node="cloud"))
        assert response.status_code == 409
        assert response.json()["code"] == "node_mismatch"

    def test_schema_violations(self, env):
        register_case(env)
        # D/N workstream must carry news_coverage
        env_case = register_case(env, workstream="N", key="case-key-0002")
        env.case_id = env_case["id"]
        payload = envelope(env, workstream="N")
        payload.pop("progress_step")
        assert submit(env, payload).status_code == 422
        # metrics null value needs null_reason
        payload = envelope(env, kind="metrics", seq=1, event_id="ev-m1")
        payload.pop("progress_step")
        payload["metrics"] = [
            {"metric": "annual_return", "value": None, "unit": "ratio", "basis": "x"}
        ]
        response = submit(env, payload)
        assert response.status_code == 422
        assert "null_reason" in response.json()["detail"]
        # wrong schema_version
        assert submit(env, envelope(env, schema_version=1)).status_code == 422

    def test_contract_hash_mismatch(self, env):
        register_case(env)
        response = submit(env, envelope(env, contract_hash="0" * 64))
        assert response.status_code == 422
        assert response.json()["code"] == "contract_hash_mismatch"

    def test_superseded_contract_versions_rejected(self, env):
        # F3P2: canonical is v2.3; superseded "2"/"2.2" (old bytes) must be refused explicitly
        legacy_v2_hash = "780046e7d0662c58d6ca0c69cfaa8966ad66d49071461ea4b730f8d592016659"
        legacy_v22_hash = "5337b291b8d1ba5faac6f10290bb86b1b27a2a62016aa6282a9bbdc26961c39e"
        register_case(env)
        response = submit(env, envelope(env, contract_version="2", contract_hash=legacy_v2_hash))
        assert response.status_code == 422
        assert response.json()["code"] == "unknown_contract_version"
        response = submit(env, envelope(env, contract_version="2.2", contract_hash=legacy_v22_hash))
        assert response.status_code == 422
        assert response.json()["code"] == "unknown_contract_version"
        # v2.3 with a superseded hash is also refused (hash pins exact bytes)
        response = submit(env, envelope(env, contract_hash=legacy_v22_hash))
        assert response.status_code == 422
        assert response.json()["code"] == "contract_hash_mismatch"

    def test_external_cannot_report_stale(self, env):
        register_case(env)
        response = submit(env, envelope(env, execution_status="stale"))
        assert response.status_code == 422
        assert response.json()["code"] == "stale_is_platform_judged"

    def test_artifact_hash_mismatch_kept_as_validation_error(self, env):
        register_case(env)
        payload = envelope(env, kind="artifact", event_id="ev-a1")
        payload.pop("progress_step")
        payload["artifacts"] = [
            {"name": "curve.json", "kind": "fixture-curve", "sha256": "1" * 64,
             "uri": "external/curve.json"}
        ]
        (pytest.workspace_root / "external/curve.json").write_text("{}")
        response = submit(env, payload)
        assert response.status_code == 422
        assert response.json()["code"] == "hash_mismatch"
        stored = list(env.xstore.events.values())
        assert len(stored) == 1 and stored[0]["apply_status"] == "validation_error"
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["events_error"] == 1

    def test_artifact_must_stay_in_controlled_workspace(self, env):
        register_case(env)
        payload = envelope(env, kind="artifact", event_id="ev-a2")
        payload.pop("progress_step")
        payload["artifacts"] = [
            {"name": "x", "kind": "x", "sha256": "2" * 64, "uri": "/etc/passwd"}
        ]
        response = submit(env, payload)
        assert response.status_code == 422
        assert response.json()["code"] == "artifact_uri_uncontrolled"


class TestIdempotencyAndOrdering:
    def test_same_key_same_content_replays(self, env):
        register_case(env)
        first = submit(env, envelope(env))
        second = submit(env, envelope(env))
        assert first.status_code == 201 and second.status_code == 200
        body = second.json()
        assert body["reused"] is True
        assert body["event"]["received_at"]  # platform-written received_at returned
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["events_applied"] == 1

    def test_same_key_different_content_conflicts(self, env):
        register_case(env)
        assert submit(env, envelope(env)).status_code == 201
        response = submit(env, envelope(env, execution_status="completed"))
        assert response.status_code == 409
        assert response.json()["code"] == "idempotency_conflict"
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["execution_status"] == "running"  # first kept

    def test_late_seq_is_historical_append_only(self, env):
        register_case(env)
        submit(env, envelope(env, seq=3, execution_status="running"))
        response = submit(env, envelope(env, seq=1, event_id="ev-late", execution_status="planned"))
        assert response.status_code == 201 and response.json()["status"] == "stale_event"
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["execution_status"] == "running"
        assert state["external"]["events_stale"] == 1

    def test_terminal_status_and_stage_regressions_ignored(self, env):
        register_case(env)
        submit(env, envelope(env, seq=0, execution_status="completed",
                             evidence_stage="data-check"))
        response = submit(env, envelope(env, seq=1, event_id="ev-r1",
                                        execution_status="running",
                                        evidence_stage="proposal"))
        assert response.status_code == 201
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["execution_status"] == "completed"
        assert state["external"]["evidence_stage"] == "data-check"
        assert "回退被忽略" in (response.json()["apply_note"] or "")


class TestReadinessGating:
    @staticmethod
    def _readiness(**over):
        obj = {
            "schema_version": 2, "project_key": "r01",
            "data_ready": True, "execution_ready": True,
            "accounting_verified": True, "platform_ready": True,
            "blocking_gaps": [], "checked_by": "p02",
            "evidence_refs": ["node://mac/docs/r01-p0/coverage-matrix.md"],
            "input_manifest": {"package_id": "r01-etf-daily", "sha256": "3" * 64, "release_id": "r"},
            "etf_input": {"package_id": "pkg", "package_version": "v1",
                          "manifest_sha256": "4" * 64, "node": "mac",
                          "uri": "node://mac/r01-etf-daily/v1"},
            "code_revision": "deadbee",
            "contract_versions": {"data": 2, "ledger": 2, "report": 2},
            "self_check_at": "2026-09-25T00:00:00Z",
            "independent_acceptance": {"status": "pending", "at": None, "by": None},
        }
        obj.update(over)
        return obj

    def test_readiness_validation(self, env):
        response = env.post("/projects/r01/readiness", json={"schema_version": 2})
        assert response.status_code == 422
        response = env.post("/projects/r01/readiness", json=self._readiness(data_ready=False))
        assert response.status_code == 200
        assert response.json()["ready_for_research"] is False
        assert env.get("/projects/r01/readiness").status_code == 200
        assert env.get("/projects/r02/readiness").status_code == 404

    def test_readiness_rejects_invalid_datetime_format(self, env):
        # format_checker: self_check_at / independent_acceptance.at must be RFC3339
        response = env.post(
            "/projects/r01/readiness",
            json=self._readiness(self_check_at="2026-09-25 00:00:00"),  # naive, no T/Z
        )
        assert response.status_code == 422
        assert "self_check_at" in response.json()["detail"]
        response = env.post(
            "/projects/r01/readiness",
            json=self._readiness(
                independent_acceptance={"status": "passed", "at": "not-a-date", "by": "x"}
            ),
        )
        assert response.status_code == 422

    def _b1_metrics(self, env, event_id, seq, **over):
        payload = envelope(env, workstream="B1", kind="metrics", fixture=False,
                           strategy_id="b1-momentum-v1", event_id=event_id, seq=seq,
                           source_revision="deadbee",
                           data={"input_package_id": "r01-etf-daily",
                                 "source_release_id": "r", "data_as_of": "2026-09-24",
                                 "manifest_sha256": "3" * 64})
        payload.pop("progress_step")
        payload["metrics"] = [
            {"metric": "total_return", "value": 0.12, "unit": "ratio", "basis": "30万·2025"},
        ]
        payload.update(over)
        return payload

    def _submit_b1(self, env, key, event_id, seq=0):
        case = register_case(env, workstream="B1", key=key)
        env.case_id = case["id"]
        return submit(env, self._b1_metrics(env, event_id, seq))

    def test_non_p0_metrics_not_ready_until_formal_admission(self, env):
        # 自检门未过 => not_ready（原始证据保留）
        env.post("/projects/r01/readiness", json=self._readiness(data_ready=False))
        response = self._submit_b1(env, "case-key-0003", "ev-m1")
        assert response.status_code == 201 and response.json()["status"] == "not_ready"
        assert "gate_data_ready" in response.json()["not_ready_reason"]
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["metrics"][0]["not_ready"] is True
        assert state["external"]["metrics"][0]["not_ready_reason"]

        # 自检全过但独立验收 pending => 仍 not_ready（AC-06）
        env.post("/projects/r01/readiness", json=self._readiness())
        response = self._submit_b1(env, "case-key-0003", "ev-m2", seq=1)
        assert response.json()["status"] == "not_ready"
        assert "independent_acceptance_pending" in response.json()["not_ready_reason"]

        # 独立验收 passed 且版本一致 => applied（正式比较放行）
        env.post("/projects/r01/readiness", json=self._readiness(
            independent_acceptance={"status": "passed", "at": "2026-09-25T00:00:00Z", "by": "w1r"}))
        response = self._submit_b1(env, "case-key-0003", "ev-m3", seq=2)
        assert response.json()["status"] == "applied"
        assert env.store.rows[env.case_id]["state"]["external"]["metrics"][2]["not_ready"] is False

    def test_formal_admission_rejects_failed_verdict(self, env):
        env.post("/projects/r01/readiness", json=self._readiness(
            independent_acceptance={"status": "failed", "at": "2026-09-25T00:00:00Z", "by": "w1r"}))
        response = self._submit_b1(env, "case-key-0004", "ev-f1")
        assert response.json()["status"] == "not_ready"
        assert "independent_acceptance_failed" in response.json()["not_ready_reason"]

    def test_formal_admission_rejects_code_drift_after_acceptance(self, env):
        accepted = self._readiness(
            independent_acceptance={"status": "passed", "at": "2026-09-25T00:00:00Z", "by": "w1r"})
        env.post("/projects/r01/readiness", json=accepted)
        # 验收后代码版本变更，verdict 未重做（仍 passed）=> 绑定漂移，拒绝正式比较
        drifted = self._readiness(code_revision="newcommit9999")
        drifted["independent_acceptance"] = accepted["independent_acceptance"]
        env.post("/projects/r01/readiness", json=drifted)
        response = self._submit_b1(env, "case-key-0005", "ev-d1")
        assert response.json()["status"] == "not_ready"
        assert "acceptance_stale_code" in response.json()["not_ready_reason"]

    def test_formal_admission_rejects_manifest_drift_after_acceptance(self, env):
        accepted = self._readiness(
            independent_acceptance={"status": "passed", "at": "2026-09-25T00:00:00Z", "by": "w1r"})
        env.post("/projects/r01/readiness", json=accepted)
        drifted = self._readiness()
        drifted["independent_acceptance"] = accepted["independent_acceptance"]
        drifted["input_manifest"] = {**accepted["input_manifest"], "sha256": "9" * 64}
        env.post("/projects/r01/readiness", json=drifted)
        response = self._submit_b1(env, "case-key-0006", "ev-d2")
        assert response.json()["status"] == "not_ready"
        assert "acceptance_stale_manifest" in response.json()["not_ready_reason"]

    def _accept_readiness(self, env):
        env.post("/projects/r01/readiness", json=self._readiness(
            independent_acceptance={"status": "passed", "at": "2026-09-25T00:00:00Z", "by": "w1r"}))

    def test_g1_identity_mismatch_single_field_repros(self, env):
        # 复验报告 F-AC06 三反例：仅改 envelope 单字段，readiness/绑定不动
        self._accept_readiness(env)
        self._submit_b1(env, "case-key-g1", "ev-g1-warm")  # register B1 case
        base = self._b1_metrics(env, "ev-g1-ok", 1)
        response = submit(env, base)
        assert response.json()["status"] == "applied"  # 匹配正例先 applied
        # ① source_revision 改动
        response = submit(env, self._b1_metrics(env, "ev-g1-code", 2, source_revision="b" * 40))
        assert response.json()["status"] == "not_ready"
        assert "identity_mismatch_code" in response.json()["not_ready_reason"]
        assert "b" * 40 in response.json()["not_ready_reason"]  # 双方值显式
        # ② manifest_sha256 改动
        response = submit(env, self._b1_metrics(env, "ev-g1-man", 3,
                                                data={"input_package_id": "r01-etf-daily",
                                                      "data_as_of": "2026-09-24",
                                                      "manifest_sha256": "c" * 64}))
        assert response.json()["status"] == "not_ready"
        assert "identity_mismatch_manifest" in response.json()["not_ready_reason"]
        # ③ input_package_id 改动
        response = submit(env, self._b1_metrics(env, "ev-g1-pkg", 4,
                                                data={"input_package_id": "wrong-input-package",
                                                      "data_as_of": "2026-09-24",
                                                      "manifest_sha256": "3" * 64}))
        assert response.json()["status"] == "not_ready"
        assert "identity_mismatch_package" in response.json()["not_ready_reason"]
        assert "wrong-input-package" in response.json()["not_ready_reason"]
        # 未进正式聚合：三条反例镜像带 not_ready 标记（含原因），正例保持 applied
        state = env.store.rows[env.case_id]["state"]["external"]
        for m in state["metrics"][2:]:
            assert m["not_ready"] is True and "identity_mismatch" in m["not_ready_reason"]
        assert all(m["not_ready"] is False for m in state["metrics"][:2])

    def test_g1_missing_manifest_treated_as_mismatch(self, env):
        self._accept_readiness(env)
        self._submit_b1(env, "case-key-g1b", "ev-g1b-warm")
        response = submit(env, self._b1_metrics(env, "ev-g1-noman", 1,
                                                data={"input_package_id": "r01-etf-daily",
                                                      "data_as_of": "2026-09-24"}))
        assert response.json()["status"] == "not_ready"
        assert "identity_mismatch_manifest" in response.json()["not_ready_reason"]

    def test_g1_p0_reports_exempt_from_identity_gate(self, env):
        # P0 工程回报不进正式比较，identity 门控不适用（input_package_id=none 等）
        self._accept_readiness(env)
        register_case(env)  # P0 case
        response = submit(env, envelope(env, event_id="ev-p0-g1", seq=0))
        assert response.status_code == 201
        assert response.json().get("not_ready") is False

    def test_formal_admission_rejects_contract_drift_or_missing_binding(self, env):
        owner = (("default", "10000001"), "mac", "r01")
        accepted = self._readiness(
            independent_acceptance={"status": "passed", "at": "2026-09-25T00:00:00Z", "by": "w1r"})
        env.post("/projects/r01/readiness", json=accepted)
        # 合同 hash 漂移（绑定快照被改）=> 拒绝
        saved = env.xstore.bindings[owner]
        env.xstore.bindings[owner] = {**saved, "contract_hash": "0" * 64}
        response = self._submit_b1(env, "case-key-0007", "ev-c1")
        assert response.json()["status"] == "not_ready"
        assert "acceptance_stale_contract" in response.json()["not_ready_reason"]
        # 绑定缺失（如历史行无快照）=> 拒绝且原因显式
        env.xstore.bindings[owner] = None
        response = self._submit_b1(env, "case-key-0007", "ev-c2", seq=1)
        assert response.json()["status"] == "not_ready"
        assert "acceptance_binding_missing" in response.json()["not_ready_reason"]
        # readiness 未登记 => readiness_missing
        env.xstore.readiness.pop(owner, None)
        response = self._submit_b1(env, "case-key-0007", "ev-c3", seq=2)
        assert response.json()["status"] == "not_ready"
        assert "readiness_missing" in response.json()["not_ready_reason"]


class TestLongTermRuns:
    def test_multiple_bounded_runs_and_audit_stream(self, env):
        register_case(env)
        submit(env, envelope(env, seq=0, source_run_id="run-1",
                             execution_status="completed"))
        submit(env, envelope(env, seq=0, event_id="ev-2", source_run_id="run-2",
                             execution_status="running"))
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["attempts"] == 2  # 累计尝试
        assert set(state["external"]["runs"]) == {"run-1", "run-2"}
        assert state["external"]["execution_status"] == "running"  # latest run
        stream = env.get(f"/cases/{env.case_id}/external-reports").json()
        assert stream["count"] == 2  # durable audit, not the capped mirror
        again = env.get(
            f"/cases/{env.case_id}/external-reports",
            params={"since_seq": stream["events"][0]["platform_seq"]},
        ).json()
        assert again["count"] == 1

    def test_platform_stale_derived_not_reported(self, env):
        register_case(env)
        submit(env, envelope(env, execution_status="running"))
        state = env.store.rows[env.case_id]["state"]
        run = state["external"]["runs"]["run-1"]
        run["last_seen_at"] = "2020-01-01T00:00:00Z"  # simulate long silence
        detail = env.get(f"/cases/{env.case_id}").json()
        assert detail["external"]["stale"] is True
        assert detail["external"]["execution_status"] == "stale"

    def test_risk_confirm_and_stop_semantics(self, env):
        register_case(env)
        payload = envelope(env, kind="risk-confirm-request", event_id="ev-risk1", seq=0)
        payload.pop("progress_step")
        payload["risk_confirm"] = {
            "ledger_run_id": "lr-1", "risk_line": "loss_line",
            "risk_event_id": "re-1", "action": "request-confirm",
        }
        assert submit(env, payload).status_code == 201
        state = env.store.rows[env.case_id]["state"]
        assert "ev-risk1" in state["external"]["risk_pending"]
        response = env.post(
            f"/cases/{env.case_id}/external-reports/ev-risk1/confirm-resume"
        )
        assert response.status_code == 200 and response.json()["reused"] is False
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["risk_pending"] == {}
        assert state["external"]["risk_history"][0]["risk_line"] == "loss_line"
        reused = env.post(
            f"/cases/{env.case_id}/external-reports/ev-risk1/confirm-resume"
        ).json()
        assert reused["reused"] is True
        # stop request ≠ stopped for external cases
        stop = env.post(f"/cases/{env.case_id}/stop").json()
        assert stop["status"] == "stop_requested"
        state = env.store.rows[env.case_id]["state"]
        assert state["external"]["stop_requested"]
        assert state["status"] == "registered"  # not faked into stopping


class TestPureLogic:
    def test_status_lattice(self):
        assert external.status_transition_allowed("planned", "running")
        assert external.status_transition_allowed("running", "blocked")
        assert external.status_transition_allowed("blocked", "running")
        assert not external.status_transition_allowed("completed", "running")
        assert not external.status_transition_allowed("failed", "running")
        assert not external.status_transition_allowed("running", "planned")

    def test_evidence_lattice(self):
        assert external.evidence_transition_allowed("proposal", "data-check")
        assert not external.evidence_transition_allowed("data-check", "proposal")

    def test_fixture_prefix_rule_enforced_by_schema(self, env):
        register_case(env)
        response = submit(env, envelope(env, fixture=False))
        assert response.status_code == 422  # fixture-* prefix requires fixture=true

    def test_contract_node_required_for_external_routes(self, env):
        # node_id outside contract enum (mac|cloud) without explicit config =>
        # registration and reports refuse explicitly instead of silent mapping
        register_case(env)
        payload = envelope(env)
        saved = env.app.state.settings.external_contract_node
        env.app.state.settings.external_contract_node = None
        try:
            response = env.post(
                "/cases",
                json={
                    "key": "case-key-0009", "question": "q",
                    "executor_kind": "external", "project_key": "r01",
                    "workstream": "P0",
                },
            )
            assert response.status_code == 409
            assert response.json()["code"] == "node_not_contract_named"
            response = submit(env, payload)
            assert response.status_code == 409
            assert response.json()["code"] == "node_not_contract_named"
        finally:
            env.app.state.settings.external_contract_node = saved

    def test_groups_never_fabricate_numbers(self):
        groups = external.project_groups(
            [{"case_id": "c1", "workstream": "A", "metrics": [],
              "strategy_versions": []}]
        )
        assert groups["A"]["status"] == "pending-research"
        assert groups["D"]["status"] == "pending-research"  # reserved group
