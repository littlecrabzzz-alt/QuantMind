"""Register frozen observation identities using the existing strategy storage.

No balance/position mirror: the filesystem paper ledger remains authoritative.
This module never starts a worker, changes a strategy parameter, or grants live
permission. Registration is explicitly invoked by the deployment owner.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .bridge import import_ashare_lab

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "output/ashare-takeover"


def _evidence(relative):
    path = ARCHIVE / "trees" / relative
    content = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(content).hexdigest()}


def registrations(user_id, tenant_id="default"):
    """Build native-engine code and immutable identities; no database access."""
    import_ashare_lab()
    from ashare_lab.paper_runtime import ACCOUNTS, frozen_specs, _source_hash

    assembly = json.loads((ROOT / "vendor/ashare-lab/frozen-source.json").read_text())
    archive_identity = hashlib.sha256((ARCHIVE / "identity.json").read_bytes()).hexdigest()
    if archive_identity != assembly["archive_identity_sha256"]:
        raise ValueError("Frozen archive identity changed")
    specs = frozen_specs()
    runtime_code_sha256 = _source_hash()
    owner = {"user_id": str(user_id), "tenant_id": str(tenant_id)}
    owner_key = hashlib.sha256(json.dumps(
        owner, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    original_doc = "ashare-lab-paper/docs/11-虚拟盘.md"
    ideas_doc = "ashare-lab-ideas/reports/ideas/SUMMARY.md"
    decisions = {
        "lowvol": ("original-frozen-paper-account", original_doc),
        "b2_lowvol_vt": ("original-frozen-paper-account", original_doc),
        "b3_lqv_buf_vt": ("original-frozen-paper-account", original_doc),
        "i7_turn_of_month": ("original-research-pass; DSR caution preserved", ideas_doc),
        "s1_invvol_etf": (
            "ETF observation, not research-pass; index variant passed, ETF correlation 0.5026 failed strict 0.5 bound",
            "ashare-lab-expansion/reports/s1/S1-股债金配置.md"),
        "cb_double_low": ("not-passed; post-result N20 observation only",
                          "ashare-lab-ideas/docs/14-转债双低前向观察预登记.md"),
        "cta_combined": ("not-passed; preregistered candidate PBO 0.94 observation only",
                         "ashare-lab-ideas/docs/15-商品CTA前向观察预登记.md"),
        "cta_trend": ("not-passed; post-result trend observation only",
                      "ashare-lab-ideas/docs/15-商品CTA前向观察预登记.md"),
    }
    result = []
    for account in ACCOUNTS:
        decision, document = decisions[account]
        original = {"research_decision": decision, "evidence": [_evidence(document)]}
        if account in ACCOUNTS[:3]:
            path = f"ashare-lab-paper/paper/{account}/meta.json"
            original["meta"] = json.loads((ARCHIVE / "trees" / path).read_text())
            original["evidence"].append(_evidence(path))
        spec = specs[account]
        frozen_identity = {"account_id": account, "spec": spec,
                           "runtime_code_sha256": runtime_code_sha256,
                           "source_assembly_id": assembly["assembly_id"],
                           "archive_identity_sha256": archive_identity,
                           "original_identity": original}
        source_id = hashlib.sha256(json.dumps(frozen_identity, sort_keys=True,
                                              ensure_ascii=False).encode()).hexdigest()
        config = {**frozen_identity, "frozen_source_id": source_id,
                  "engine": "ashare_lab", "frozen": True,
                  "observation_only": True, "trading_permission": False,
                  "owner": owner,
                  "authoritative_ledger": f"output/ashare-paper/{owner_key}/{account}",
                  "paper_api": "/simulation/frozen-paper"}
        # This is the native paper entry point, not a fake Qlib strategy class.
        # Executing it explicitly reuses the sole runtime/ledger and engine.
        code = (
            '"""Frozen ashare observation; not a live or Qlib execution strategy."""\n'
            f"ACCOUNT_ID = {account!r}\n"
            f"FROZEN_SOURCE_ID = {source_id!r}\n"
            f"STRATEGY_CONFIG = {config!r}\n\n"
            "async def run(manifest, ledger_root, preserved_source, bindings):\n"
            "    from pathlib import Path\n"
            "    from backend.services.simulation.services import frozen_paper_service\n"
            "    owner = STRATEGY_CONFIG['owner']\n"
            "    await frozen_paper_service.validate_bindings(\n"
            "        bindings, owner['user_id'], owner['tenant_id'], names=(ACCOUNT_ID,))\n"
            "    root = frozen_paper_service.scoped_ledger_root(\n"
            "        owner['user_id'], owner['tenant_id'], Path(ledger_root))\n"
            "    runtime = frozen_paper_service.paper_runtime()\n"
            "    return runtime.update(root, preserved_source, manifest,\n"
            "                          names=(ACCOUNT_ID,), bindings=bindings)\n"
        )
        result.append({"account_id": account, "name": f"ashare frozen observation / {account}",
                       "code": code, "metadata": {
                           "status": "DRAFT", "strategy_type": "CUSTOM",
                           "is_verified": False, "is_public": False,
                           "description": "Frozen paper observation only. " + decision,
                           "tags": ["ashare-lab", "frozen-paper", "observation-only", account],
                           "config": config,
                           "parameters": {"account_id": account, "frozen_source_id": source_id,
                                          "tenant_id": str(tenant_id),
                                          "runtime_code_sha256": runtime_code_sha256,
                                          "engine": "ashare_lab", "frozen": True,
                                          "observation_only": True, "trading_permission": False},
                           "execution_config": {"paper_only": True, "live_enabled": False,
                                                "trading_permission": False},
                       }})
    return result


async def register(user_id, tenant_id="default"):
    """Idempotent per owner and frozen code version; never mutate old versions."""
    from backend.shared.strategy_storage import get_strategy_storage_service

    user_id, tenant_id = str(user_id), str(tenant_id)
    planned = registrations(user_id, tenant_id)
    storage = get_strategy_storage_service()
    existing = storage.list(user_id, tags=["frozen-paper"], include_templates=False)
    identities = {}
    for row in existing:
        params = row.get("parameters") or {}
        source_id = params.get("frozen_source_id")
        if source_id and params.get("tenant_id") == tenant_id:
            identities[source_id] = row
    accounts = {}
    for item in planned:
        params = item["metadata"]["parameters"]
        source_id = params["frozen_source_id"]
        strategy_code_sha256 = hashlib.sha256(item["code"].encode()).hexdigest()
        prior = identities.get(source_id)
        if prior:
            if prior["status"] != "DRAFT" or prior.get("is_verified"):
                raise ValueError(f"Observation identity has unauthorized lifecycle: {item['account_id']}")
            registered = await storage.get(prior["id"], user_id=user_id, resolve_code=True)
            if not registered or hashlib.sha256(
                registered["code"].encode()).hexdigest() != strategy_code_sha256:
                raise ValueError(f"Registered frozen code changed: {item['account_id']}")
            if registered["parameters"] != params:
                raise ValueError(f"Registered frozen binding changed: {item['account_id']}")
            strategy_id = prior["id"]
        else:
            saved = await storage.save(user_id=user_id, name=item["name"], code=item["code"],
                                       metadata=item["metadata"])
            strategy_id = saved["id"]
        accounts[item["account_id"]] = {
            "strategy_id": str(strategy_id), "frozen_source_id": source_id,
            "runtime_code_sha256": params["runtime_code_sha256"],
            "strategy_code_sha256": strategy_code_sha256,
        }
    return {"user_id": user_id, "tenant_id": tenant_id, "accounts": accounts}
