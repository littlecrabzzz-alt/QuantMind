"""R01 external executor mode: envelope validation, idempotency and state application.

Contract sources (frozen copies, see contracts/README.md):
- data-contract.md / data-contract.schema.json  -> report envelope
- readiness.schema.json                         -> project admission object

Semantics implemented here follow report-api.md v2 sections 3-8 and must not be
weakened: three-level idempotency key, no-regression ordering, separated
source/received timestamps, hash-verified artifacts, honest failure states and
readiness gating for formal research display.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.validators import Draft7Validator
from psycopg.types.json import Jsonb

from .sandbox import read_file

CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"

WORKSTREAMS = ("P0", "A", "B1", "B2", "B3", "D", "N")
# execution_status one-way lattice; "stale" is platform-judged only (never from
# external envelopes) and "planned" can never follow an active/terminal state.
EXECUTION_RANK = {"planned": 0, "running": 1, "blocked": 1, "failed": 2, "completed": 2}
TERMINAL_STATUSES = ("failed", "completed")
EVIDENCE_ORDER = [
    "proposal",
    "data-check",
    "development-compare",
    "engineering-validation",
    "independent-verification",
    "forward-observation",
]
MAX_MIRROR = 200  # mirrors inside research_drafts.state; full audit stays in the table


class NodeMismatch(ValueError):
    """Envelope source_node differs from the case registration node (HTTP 409)."""


class ContractError(ValueError):
    """Validation failure that maps to HTTP 422 with a machine-readable code."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_iso(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive timestamp")
    return parsed


class Contracts:
    """Frozen contract copies loaded once; hash of the md file is canonical."""

    def __init__(self):
        self.envelope_schema = json.loads(
            (CONTRACTS_DIR / "data-contract.schema.json").read_text()
        )
        self.readiness_schema = json.loads(
            (CONTRACTS_DIR / "readiness.schema.json").read_text()
        )
        self.contract_text = (CONTRACTS_DIR / "data-contract.md").read_bytes()
        # Envelope contract_version -> canonical md bytes sha256 (v2.3, F3P2 sync).
        # Superseded versions (2/2.1/2.2) are not registered: unknown version => 422.
        self.contract_hashes = {"2.3": hashlib.sha256(self.contract_text).hexdigest()}
        self._envelope = Draft202012Validator(
            self.envelope_schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )
        self._readiness = Draft7Validator(
            self.readiness_schema, format_checker=Draft7Validator.FORMAT_CHECKER
        )

    def validate_envelope(self, envelope):
        errors = sorted(self._envelope.iter_errors(envelope), key=lambda e: list(e.path))
        if errors:
            detail = "; ".join(
                f"{'.'.join(map(str, e.path)) or 'envelope'}: {e.message}"
                for e in errors[:8]
            )
            raise ContractError("schema_violation", f"回报信封不符合合同：{detail}")

    def validate_readiness(self, obj):
        errors = sorted(self._readiness.iter_errors(obj), key=lambda e: list(e.path))
        if errors:
            detail = "; ".join(
                f"{'.'.join(map(str, e.path)) or 'readiness'}: {e.message}"
                for e in errors[:8]
            )
            raise ContractError("readiness_schema_violation", f"准入对象不符合合同：{detail}")

    def check_contract_hash(self, version, value):
        expected = self.contract_hashes.get(str(version))
        if expected is None:
            raise ContractError(
                "unknown_contract_version",
                f"合同版本 {version!r} 未登记；可用版本：{sorted(self.contract_hashes)}",
            )
        if expected != value:
            raise ContractError(
                "contract_hash_mismatch",
                "contract_hash 与所指合同版本文件的 sha256 不一致",
            )


def initial_external_state(project_key, workstream):
    return {
        "executor_kind": "external",
        "project_key": project_key,
        "workstream": workstream,
        "execution_status": "planned",
        "evidence_stage": "proposal",
        "runs": {},
        "progress": {},
        "steps_order": [],
        "checks": {},
        "gaps": {},
        "artifacts": [],
        "metrics": [],
        "news": None,
        "strategy_versions": {},
        "risk_pending": {},
        "risk_history": [],
        "stop_requested": None,
        "data": None,
        "attempts": 0,
        "events_applied": 0,
        "events_stale": 0,
        "events_error": 0,
        "last_event_at": None,
    }


def self_check_passes(obj):
    """P0 self-check level: all four gates true and no blocking gaps.

    Formal research admission additionally requires the independent
    acceptance verdict (see evaluate_formal_admission) — a passing self-check
    alone never unlocks formal comparisons (AC-06).
    """

    if not isinstance(obj, dict):
        return False
    return (
        obj.get("data_ready") is True
        and obj.get("execution_ready") is True
        and obj.get("accounting_verified") is True
        and obj.get("platform_ready") is True
        and obj.get("blocking_gaps") == []
    )


# Backwards-compatible alias for the self-check predicate only.
readiness_passes = self_check_passes


def independently_accepted(obj):
    return (
        isinstance(obj, dict)
        and obj.get("independent_acceptance", {}).get("status") == "passed"
    )


def acceptance_binding_from(readiness, contract_hash):
    """Server-side snapshot of what the acceptance verdict covers.

    The frozen readiness schema has no room for a binding block inside
    independent_acceptance (additionalProperties:false), so the platform
    snapshots the binding itself when it first observes status=="passed":
    the accepted code revision, input manifest and contract hash. Any later
    drift invalidates the verdict for formal admission (stale).
    """

    return {
        "commit": readiness.get("code_revision"),
        "manifest_sha256": (readiness.get("input_manifest") or {}).get("sha256"),
        "contract_hash": contract_hash,
        "accepted_at": readiness.get("independent_acceptance", {}).get("at"),
    }


def envelope_identity_vs_binding(envelope, readiness, binding):
    """G1P1: compare the envelope's actual code/data identity against the
    accepted binding snapshot at the real report ingress.

    Checked per-field (envelope vs accepted): source_revision vs commit,
    data.manifest_sha256 vs binding manifest, data.input_package_id vs
    readiness.input_manifest.package_id. Mismatched reports are kept as raw
    evidence with explicit identity_mismatch_* reasons (both sides' values)
    and never enter formal metrics/comparison aggregates. Returns (ok, reasons);
    ok=True when there is no binding to compare against (the formal gate
    blocks that case independently).
    """

    if not isinstance(binding, dict) or not binding.get("contract_hash"):
        return True, []
    reasons = []
    revision = envelope.get("source_revision")
    accepted_commit = binding.get("commit")
    if revision != accepted_commit:
        reasons.append(
            f"identity_mismatch_code: envelope source_revision={revision!r} "
            f"vs accepted commit={accepted_commit!r}"
        )
    data = envelope.get("data") or {}
    manifest = data.get("manifest_sha256")
    accepted_manifest = binding.get("manifest_sha256")
    if not manifest:
        reasons.append(
            "identity_mismatch_manifest: envelope data.manifest_sha256 缺失"
            "（正式准入回报必须携带）"
        )
    elif manifest != accepted_manifest:
        reasons.append(
            f"identity_mismatch_manifest: envelope={str(manifest)[:16]}… "
            f"vs accepted={str(accepted_manifest)[:16]}…"
        )
    package = data.get("input_package_id")
    accepted_package = (readiness or {}).get("input_manifest", {}).get("package_id")
    if package != accepted_package:
        reasons.append(
            f"identity_mismatch_package: envelope={package!r} "
            f"vs accepted={accepted_package!r}"
        )
    return (not reasons), reasons


def evaluate_formal_admission(readiness, binding, current_contract_hash):
    """Formal admission gate for non-P0 research results (AC-06).

    Returns (ready_for_research, reasons). ready=True requires: self-check
    gates pass AND blocking gaps empty AND independent acceptance passed AND
    the acceptance binding still matches the current context. pending/failed
    verdicts or version drift keep results as raw evidence only (not_ready).
    """

    if not isinstance(readiness, dict):
        return False, ["readiness_missing"]
    reasons = []
    for gate in ("data_ready", "execution_ready", "accounting_verified", "platform_ready"):
        if readiness.get(gate) is not True:
            reasons.append(f"gate_{gate}")
    if readiness.get("blocking_gaps"):
        reasons.append("blocking_gaps:" + ",".join(readiness["blocking_gaps"]))
    verdict = (readiness.get("independent_acceptance") or {}).get("status")
    if verdict != "passed":
        reasons.append(f"independent_acceptance_{verdict or 'missing'}")
        return False, reasons
    if not isinstance(binding, dict) or not binding.get("contract_hash"):
        return False, reasons + ["acceptance_binding_missing"]
    if binding.get("commit") != readiness.get("code_revision"):
        reasons.append("acceptance_stale_code")
    if binding.get("manifest_sha256") != (readiness.get("input_manifest") or {}).get("sha256"):
        reasons.append("acceptance_stale_manifest")
    if binding.get("contract_hash") != current_contract_hash:
        reasons.append("acceptance_stale_contract")
    return (not reasons), reasons


def normalize_submission(raw):
    """Platform owns received_at; client-supplied value is ignored for both
    storage and idempotency hashing (same client payload -> same hash)."""

    if not isinstance(raw, dict):
        raise ContractError("schema_violation", "回报信封必须是 JSON 对象")
    envelope = json.loads(json.dumps(raw))  # deep copy, no shared refs
    timestamps = envelope.get("timestamps")
    source_at = timestamps.get("source_at") if isinstance(timestamps, dict) else None
    if not source_at:
        raise ContractError("schema_violation", "缺少 timestamps.source_at")
    try:
        _parse_iso(source_at)
    except (ValueError, TypeError, AttributeError):
        raise ContractError("schema_violation", "timestamps.source_at 必须是带时区的时间") from None
    client_view = json.loads(json.dumps(envelope))
    if isinstance(client_view.get("timestamps"), dict):
        client_view["timestamps"].pop("received_at", None)
    received_at = _utc_now_iso()
    envelope.setdefault("timestamps", {})["received_at"] = received_at
    payload_hash = hashlib.sha256(
        json.dumps(client_view, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return envelope, payload_hash, received_at


def check_case_binding(envelope, ident, case_external, node):
    if envelope.get("case_id") != ident:
        raise ContractError("case_mismatch", "信封 case_id 与目标课题不一致")
    if envelope.get("source_node") != node:
        raise NodeMismatch("信封 source_node 与课题登记节点不一致")
    if envelope.get("workstream") != case_external.get("workstream"):
        raise ContractError(
            "workstream_mismatch", "信封 workstream 与课题登记的 workstream 不一致"
        )
    if envelope.get("project_key") != case_external.get("project_key"):
        raise ContractError(
            "project_mismatch", "信封 project_key 与课题登记的 project_key 不一致"
        )


def verify_artifacts(envelope, workspace_root):
    """Artifacts must already sit in the node-controlled case workspace.

    Accepts课题相对路径 (resolved under the workspace, no symlink escape) and
    node://<this-node>/workspace/<rel>. Raw absolute paths are rejected.
    """

    for artifact in envelope.get("artifacts") or []:
        uri = artifact.get("uri", "")
        if uri.startswith("node://"):
            parts = uri[len("node://") :].split("/", 1)
            if len(parts) != 2 or parts[0] != envelope.get("source_node"):
                raise ContractError(
                    "artifact_uri_uncontrolled", f"产物 uri 不属于本节点受控目录：{uri}"
                )
            relative = parts[1]
        else:
            relative = uri
        if relative.startswith("/") or not relative.strip():
            raise ContractError(
                "artifact_uri_uncontrolled", f"产物 uri 必须是课题相对路径：{uri}"
            )
        try:
            content = read_file(workspace_root, relative, 20_000_000)
        except (OSError, ValueError):
            raise ContractError(
                "artifact_missing", f"产物文件不存在或不可读（节点受控目录内）：{uri}"
            ) from None
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact.get("sha256"):
            raise ContractError(
                "hash_mismatch",
                f"产物 sha256 不符：{artifact.get('name')}（期望 {artifact.get('sha256')[:16]}…，实际 {digest[:16]}…）",
            )


def status_transition_allowed(current, proposed):
    if current == proposed:
        return True
    if current in TERMINAL_STATUSES:
        return False  # completed/failed are terminal for this run
    if proposed == "planned":
        return False  # planned can never follow running/blocked/terminal
    if current == "planned":
        return True
    # running <-> blocked, or to terminal
    return proposed in ("running", "blocked", "failed", "completed")


def evidence_transition_allowed(current, proposed):
    return EVIDENCE_ORDER.index(proposed) >= EVIDENCE_ORDER.index(current)


def apply_event(external, envelope, received_at, not_ready, not_ready_reason=None):
    """Apply one envelope to the mirrored case state; returns apply decision.

    Decision is 'applied' or 'stale_event' (kept verbatim, no regression).
    """

    run_id = envelope["source_run_id"]
    run = external["runs"].get(run_id)
    fresh_run = run is None
    if fresh_run:
        run = {
            "source_task": envelope["source_task"],
            "first_seq": envelope["seq"],
            "last_seq": -1,
            "execution_status": "planned",
            "evidence_stage": "proposal",
            "first_seen_at": received_at,
            "last_seen_at": received_at,
            "events": 0,
            "data": None,
            "errors": [],
            # H1-AC03：每 run 独立步骤状态（step_id 可跨 run 复用，归属显式）
            "steps": {},
            "steps_order": [],
        }
        external["runs"][run_id] = run
        external["attempts"] += 1
    notes = []
    if envelope["seq"] <= run["last_seq"]:
        external["events_stale"] += 1
        return "stale_event", "历史追加：seq 不高于该运行已应用最大 seq，状态不回退"
    run["last_seq"] = envelope["seq"]
    run["events"] += 1
    run["last_seen_at"] = received_at
    run["source_task"] = envelope["source_task"]
    proposed_status = envelope["execution_status"]
    if status_transition_allowed(run["execution_status"], proposed_status):
        run["execution_status"] = proposed_status
    else:
        notes.append(
            f"execution_status 回退被忽略（{run['execution_status']} → {proposed_status}）"
        )
    proposed_stage = envelope["evidence_stage"]
    if evidence_transition_allowed(run["evidence_stage"], proposed_stage):
        run["evidence_stage"] = proposed_stage
    else:
        notes.append(
            f"evidence_stage 回退被忽略（{run['evidence_stage']} → {proposed_stage}）"
        )
    run["errors"] = list(envelope.get("errors") or [])[-10:]
    data = envelope.get("data") or {}
    if data.get("input_package_id"):
        current_data = run["data"] or {}
        if not current_data.get("data_as_of") or data.get(
            "data_as_of", ""
        ) >= current_data.get("data_as_of", ""):
            run["data"] = {
                k: data.get(k)
                for k in ("input_package_id", "source_release_id", "data_as_of", "manifest_sha256")
            }
    external["data"] = run["data"] or external["data"]
    external["execution_status"] = run["execution_status"]
    external["evidence_stage"] = max(
        (r["evidence_stage"] for r in external["runs"].values()),
        key=EVIDENCE_ORDER.index,
    )
    kind = envelope["kind"]
    fixture = bool(envelope.get("fixture"))
    at = envelope["timestamps"]["source_at"]
    if kind == "progress":
        step = envelope["progress_step"]
        step_id = step["step_id"]
        entry = {
            "title": step["title"],
            "status": step["status"],
            "note": step.get("note", ""),
            "seq": envelope["seq"],
            "at": at,
            "source_run_id": run_id,
        }
        # 每 run 独立步骤状态（顺序=该 run 内首次回报顺序；seq 仅 run 内有效）
        if step_id not in run["steps"]:
            run["steps_order"].append(step_id)
        run["steps"][step_id] = entry
        # 兼容镜像（课题级最新应用事件覆盖；跨 run 不比 seq，记录归属 run）
        if step_id not in external["progress"]:
            external["steps_order"].append(step_id)
        external["progress"][step_id] = entry
    elif kind == "data-check-report":
        for check in envelope["checks"]:
            external["checks"][check["item"]] = {
                "result": check["result"],
                "evidence_ref": check["evidence_ref"],
                "seq": envelope["seq"],
                "at": at,
                "source_run_id": run_id,
            }
    elif kind == "gap-report":
        for gap in envelope["gaps"]:
            record = external["gaps"].setdefault(
                gap["gap_id"],
                {"desc": gap["desc"], "count": 0, "first_at": at, "last_at": at},
            )
            record["count"] += 1
            record["last_at"] = at
            record["desc"] = gap["desc"]
    elif kind == "artifact":
        for a in envelope["artifacts"]:
            external["artifacts"].append(
                {
                    "name": a["name"],
                    "kind": a["kind"],
                    "sha256": a["sha256"],
                    "uri": a["uri"],
                    "at": at,
                    "seq": envelope["seq"],
                    "fixture": fixture,
                    "not_ready": not_ready,
                    "not_ready_reason": not_ready_reason,
                    "source_run_id": run_id,
                }
            )
        external["artifacts"] = external["artifacts"][-MAX_MIRROR:]
    elif kind == "metrics":
        external["metrics"].append(
            {
                "strategy_id": envelope["strategy_id"],
                "metrics": envelope["metrics"],
                "data": run["data"],
                "at": at,
                "seq": envelope["seq"],
                "fixture": fixture,
                "not_ready": not_ready,
                "not_ready_reason": not_ready_reason,
                "source_run_id": run_id,
            }
        )
        external["metrics"] = external["metrics"][-MAX_MIRROR:]
    elif kind == "news-coverage":
        external["news"] = {**envelope["news_coverage"], "at": at, "seq": envelope["seq"]}
    elif kind == "risk-confirm-request":
        external["risk_pending"][envelope["event_id"]] = {
            **envelope["risk_confirm"],
            "at": at,
            "seq": envelope["seq"],
        }
    version = external["strategy_versions"].setdefault(
        envelope["strategy_id"], {"fixture": fixture, "first_at": at, "last_at": at, "events": 0}
    )
    version["last_at"] = at
    version["events"] += 1
    external["events_applied"] += 1
    external["last_event_at"] = received_at
    decision = "applied" if not notes else "applied_with_notes"
    return decision, "; ".join(notes) if notes else None


def _current_run(external):
    """当前运行=最近有回报的 run（last_seen_at 最大；不拿跨 run seq 当先后）。"""
    runs = external.get("runs") or {}
    if not runs:
        return None
    return max(runs.items(), key=lambda kv: kv[1].get("last_seen_at") or "")


def _run_steps(external, rid, run):
    """该 run 的步骤状态；旧数据无 run.steps 时按 source_run_id 从兼容镜像回填。"""
    steps = run.get("steps") or {}
    if steps or not run:
        return steps, run.get("steps_order", [s for s in steps])
    mirror = external.get("progress") or {}
    steps = {sid: row for sid, row in mirror.items()
             if row.get("source_run_id") == rid}
    order = [sid for sid in external.get("steps_order", []) if sid in steps]
    return steps, order


def _current_step(external):
    """当前步骤=当前运行内最近一次有效回报的步骤（run 内 seq 定先后）。"""
    current = _current_run(external)
    if not current:
        return None
    rid, run = current
    steps, _ = _run_steps(external, rid, run)
    if not steps:
        return None
    sid = max(steps, key=lambda s: steps[s].get("seq", -1))
    return {"step_id": sid, **steps[sid]}


def _next_step(external):
    """下一步=当前运行内首个未完成步骤（该 run 首次回报顺序）；全完成=>None。"""
    current = _current_run(external)
    if not current:
        return None
    rid, run = current
    steps, order = _run_steps(external, rid, run)
    for sid in order:
        row = steps.get(sid)
        if row and row.get("status") != "done":
            return {"step_id": sid, **row}
    return None


def _reported_usage(external):
    """Aggregate only runner-reported usage/cost metrics; None => 未统计."""
    values = []
    for entry in external.get("metrics") or []:
        for m in entry.get("metrics") or []:
            if m.get("metric", "").startswith(("usage.", "usage_", "cost.", "cost_")):
                values.append({**m, "source_run_id": entry.get("source_run_id"),
                               "at": entry.get("at")})
    if not values:
        return {"values": None,
                "note": "未统计：外部 runner 未按合同回报用量/费用（不以累计尝试冒充）"}
    return {"values": values, "note": "来源：外部回报 metrics（真实值）"}


def derive_summary(external, now=None, stale_after=21600.0):
    """Read-side derived fields (never persisted): staleness and rollups."""

    now = now or time.time()
    runs = sorted(
        external["runs"].values(), key=lambda r: r["last_seen_at"] or ""
    )
    latest = runs[-1] if runs else None
    stale = bool(
        latest
        and latest["execution_status"] in ("planned", "running", "blocked")
        and latest["last_seen_at"]
        and (
            now - _parse_iso(latest["last_seen_at"].replace("Z", "+00:00")).timestamp()
            > stale_after
        )
    )
    return {
        "workstream": external.get("workstream"),
        "project_key": external.get("project_key"),
        "execution_status": "stale" if stale else external.get("execution_status"),
        "stale": stale,
        "evidence_stage": external.get("evidence_stage"),
        "runs": [
            {
                "source_run_id": rid,
                **{
                    k: r[k]
                    for k in (
                        "source_task",
                        "first_seq",
                        "last_seq",
                        "execution_status",
                        "evidence_stage",
                        "first_seen_at",
                        "last_seen_at",
                        "events",
                        "data",
                        "errors",
                    )
                },
                # 每 run 独立步骤状态（H1-AC03；旧数据缺省时由读取侧回填）
                "steps": r.get("steps") or {
                    sid: row for sid, row in (external.get("progress") or {}).items()
                    if row.get("source_run_id") == rid
                },
                "steps_order": r.get("steps_order")
                or [sid for sid in external.get("steps_order", [])
                    if sid in (r.get("steps") or {})],
                # 恢复点：续报从 last_seq+1 起；同 run 重复事件幂等不新增实验
                "resume_after_seq": r["last_seq"],
            }
            for rid, r in external["runs"].items()
        ],
        "attempts": external.get("attempts", 0),
        "events_applied": external.get("events_applied", 0),
        "events_stale": external.get("events_stale", 0),
        "events_error": external.get("events_error", 0),
        "last_event_at": external.get("last_event_at"),
        "current_run_id": (_current_run(external) or (None,))[0],
        "current_step": _current_step(external),
        "next_step": _next_step(external),
        # 用量/费用只认外部回报的真实值；未回报=未统计，不以 attempts 冒充
        "usage": _reported_usage(external),
        "progress": [
            {"step_id": sid, **external["progress"][sid]} for sid in external["steps_order"]
        ],
        "checks": [
            {"item": item, **check} for item, check in external["checks"].items()
        ],
        "gaps": [
            {"gap_id": gap_id, **gap} for gap_id, gap in external["gaps"].items()
        ],
        "artifacts": external.get("artifacts", []),
        "metrics": external.get("metrics", []),
        "news": external.get("news"),
        "strategy_versions": [
            {"strategy_id": sid, **v}
            for sid, v in external.get("strategy_versions", {}).items()
        ],
        "risk_pending": external.get("risk_pending", {}),
        "risk_history": external.get("risk_history", []),
        "stop_requested": external.get("stop_requested"),
        "data": external.get("data"),
    }


def project_groups(summaries):
    """Comparison groups A/B1/B2/B3 (+D/N reserved): latest metrics per
    workstream, fixture/not_ready flagged, never fabricating numbers."""

    groups = {}
    for workstream in ("A", "B1", "B2", "B3", "D", "N"):
        rows = [s for s in summaries if s["workstream"] == workstream]
        metrics = [m for s in rows for m in s["metrics"]]
        group = {
            "workstream": workstream,
            "status": "pending-research" if not metrics else "reported",
            "cases": [s["case_id"] for s in rows],
            "metrics": metrics[-10:],
            "strategy_versions": [
                v for s in rows for v in s["strategy_versions"]
            ],
        }
        groups[workstream] = group
    return groups


def event_row_public(row):
    payload = row["payload"]
    return {
        "platform_seq": row["id"],
        "event_id": payload["event_id"],
        "source_task": payload["source_task"],
        "source_run_id": payload["source_run_id"],
        "seq": payload["seq"],
        "kind": payload["kind"],
        "execution_status": payload["execution_status"],
        "evidence_stage": payload["evidence_stage"],
        "fixture": bool(payload.get("fixture")),
        "source_at": payload["timestamps"]["source_at"],
        "received_at": row["received_at"].isoformat().replace("+00:00", "Z")
        if hasattr(row["received_at"], "isoformat")
        else row["received_at"],
        "apply_status": row["apply_status"],
        "apply_note": row["apply_note"],
        "confirmed_at": row["confirmed_at"].isoformat().replace("+00:00", "Z")
        if row.get("confirmed_at") and hasattr(row["confirmed_at"], "isoformat")
        else row.get("confirmed_at"),
        "confirmed_by": row.get("confirmed_by"),
        "payload": payload,
    }


class ExternalStore:
    """Durable audit + readiness persistence on top of the shared pool.

    research_external_events keeps every accepted envelope verbatim (the
    2000-entry state mirror is presentation-only); readiness objects are
    validated before every write.
    """

    def __init__(self, pool):
        self.pool = pool

    async def find_event(self, db, draft_id, source_task, source_run_id, event_id):
        return await (
            await db.execute(
                """SELECT * FROM research_external_events
                WHERE draft_id=%s AND source_task=%s AND source_run_id=%s AND event_id=%s""",
                (draft_id, source_task, source_run_id, event_id),
            )
        ).fetchone()

    async def insert_event(
        self, db, owner, node, draft_id, envelope, payload_hash, received_at,
        apply_status, apply_note=None,
    ):
        row = await (
            await db.execute(
                """INSERT INTO research_external_events
                (tenant_id,user_id,node_id,draft_id,project_key,workstream,
                 source_task,source_run_id,event_id,seq,kind,payload,payload_hash,
                 received_at,apply_status,apply_note,applied_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s='applied' OR %s='applied_with_notes' OR %s='not_ready' OR %s='stale_event' THEN now() END)
                RETURNING id""",
                (
                    owner[0], owner[1], node, draft_id,
                    envelope["project_key"], envelope["workstream"],
                    envelope["source_task"], envelope["source_run_id"],
                    envelope["event_id"], envelope["seq"], envelope["kind"],
                    Jsonb(envelope), payload_hash,
                    received_at, apply_status, apply_note,
                    apply_status, apply_status, apply_status, apply_status,
                ),
            )
        ).fetchone()
        return row["id"]

    async def bump_error_count(self, db, draft_id):
        await db.execute(
            """UPDATE research_drafts SET state=jsonb_set(state,
            '{external,events_error}', ((state->'external'->>'events_error')::int+1)::text::jsonb)
            WHERE draft_id=%s""", (draft_id,),
        )

    async def stream(self, owner, node, draft_id, since_seq=0, limit=500):
        async with self.pool.connection() as db:
            rows = await (
                await db.execute(
                    """SELECT * FROM research_external_events
                    WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND draft_id=%s AND id>%s
                    ORDER BY id LIMIT %s""",
                    (*owner, node, draft_id, since_seq, limit),
                )
            ).fetchall()
        return [event_row_public(r) for r in rows]

    async def find_event_by_event_id(self, owner, node, draft_id, event_id):
        async with self.pool.connection() as db:
            return await (
                await db.execute(
                    """SELECT * FROM research_external_events
                    WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND draft_id=%s AND event_id=%s""",
                    (*owner, node, draft_id, event_id),
                )
            ).fetchone()

    async def confirm_resume(self, owner, node, draft_id, event_id, user):
        async with self.pool.connection() as db, db.transaction():
            row = await (
                await db.execute(
                    """SELECT * FROM research_external_events
                    WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND draft_id=%s AND event_id=%s
                    FOR UPDATE""",
                    (*owner, node, draft_id, event_id),
                )
            ).fetchone()
            if row is None:
                return None
            if row["confirmed_at"]:
                return event_row_public(row), True
            row = await (
                await db.execute(
                    """UPDATE research_external_events
                    SET confirmed_at=now(), confirmed_by=%s WHERE id=%s RETURNING *""",
                    (user, row["id"]),
                )
            ).fetchone()
            return event_row_public(row), False

    async def get_readiness(self, owner, node, project_key):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    """SELECT object, updated_at FROM research_project_readiness
                    WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND project_key=%s""",
                    (*owner, node, project_key),
                )
            ).fetchone()
        if not row:
            return None
        return {**row["object"], "platform_updated_at": row["updated_at"].isoformat().replace("+00:00", "Z")}

    async def get_acceptance_binding(self, owner, node, project_key):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    """SELECT acceptance_binding FROM research_project_readiness
                    WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND project_key=%s""",
                    (*owner, node, project_key),
                )
            ).fetchone()
        return (row or {}).get("acceptance_binding")

    async def save_readiness(self, owner, node, project_key, obj, contract_hash=None):
        """Upsert readiness + maintain the server-side acceptance binding.

        The binding is snapshotted when the verdict first flips to "passed"
        (what was accepted: commit/manifest/contract hash). While the verdict
        stays "passed" across re-POSTs the original binding is kept, so later
        code/input drift is detected as a stale acceptance (AC-06). Verdicts
        other than "passed" clear the binding.
        """

        async with self.pool.connection() as db, db.transaction():
            prior = await (
                await db.execute(
                    """SELECT object, acceptance_binding FROM research_project_readiness
                    WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND project_key=%s
                    FOR UPDATE""",
                    (*owner, node, project_key),
                )
            ).fetchone()
            prior_status = (
                (prior["object"] or {}).get("independent_acceptance", {}).get("status")
                if prior
                else None
            )
            verdict = obj.get("independent_acceptance", {}).get("status")
            binding = prior.get("acceptance_binding") if prior else None
            if verdict == "passed":
                if prior_status != "passed" or not isinstance(binding, dict):
                    binding = acceptance_binding_from(obj, contract_hash)
            else:
                binding = None
            await db.execute(
                """INSERT INTO research_project_readiness
                (tenant_id,user_id,node_id,project_key,object,acceptance_binding,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(tenant_id,user_id,node_id,project_key)
                DO UPDATE SET object=EXCLUDED.object,
                acceptance_binding=EXCLUDED.acceptance_binding, updated_at=now()""",
                (*owner, node, project_key, Jsonb(obj), Jsonb(binding)),
            )
