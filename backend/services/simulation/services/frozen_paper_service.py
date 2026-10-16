"""Owner-scoped ashare ledgers, authorized through native strategy_storage versions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
VENDOR = ROOT / "vendor" / "ashare-lab" / "src"


def paper_runtime():
    if not VENDOR.is_dir():
        raise RuntimeError("Vendored ashare runtime is not installed")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    from ashare_lab import paper_runtime as runtime
    if not Path(runtime.__file__).resolve().is_relative_to(VENDOR.resolve()):
        raise RuntimeError("Refusing non-vendored ashare runtime")
    return runtime


def ledger_root() -> Path:
    return Path(os.environ.get("ASHARE_PAPER_ROOT", str(ROOT / "output" / "ashare-paper"))).resolve()


def scoped_ledger_root(user_id: str, tenant_id: str, base: Path | None = None) -> Path:
    scope = json.dumps({"user_id": str(user_id), "tenant_id": str(tenant_id)},
                       sort_keys=True, separators=(",", ":"))
    return (base or ledger_root()) / hashlib.sha256(scope.encode()).hexdigest()


async def validate_bindings(bindings: dict, user_id: str, tenant_id: str, names=None):
    """No admin/global bypass: native owner lookup plus immutable code/parameter identity."""
    from backend.shared.strategy_storage import get_strategy_storage_service
    runtime = paper_runtime()
    if not isinstance(bindings, dict):
        raise PermissionError("Frozen-paper bindings must be an owner-scoped object")
    if bindings.get("user_id") != str(user_id) or bindings.get("tenant_id") != str(tenant_id):
        raise PermissionError("Frozen-paper owner/tenant does not match authenticated scope")
    storage = get_strategy_storage_service()
    current_hash = runtime._source_hash()
    for name in names or runtime.ACCOUNTS:
        binding = bindings.get("accounts", {}).get(name)
        if not binding:
            raise PermissionError(f"Missing registered frozen strategy binding for {name}")
        if not isinstance(binding, dict) or not {
                "strategy_id", "frozen_source_id", "runtime_code_sha256", "strategy_code_sha256"
        }.issubset(binding):
            raise PermissionError(f"Incomplete registered version binding for {name}")
        strategy = await storage.get(binding["strategy_id"], user_id=str(user_id), resolve_code=True)
        if strategy is None:
            raise PermissionError(f"No native strategy ownership permission for {name}")
        params = strategy.get("parameters") or {}
        expected = {"account_id": name, "frozen_source_id": binding["frozen_source_id"],
                    "tenant_id": str(tenant_id), "runtime_code_sha256": current_hash,
                    "frozen": True, "observation_only": True, "trading_permission": False}
        if any(params.get(key) != value for key, value in expected.items()):
            raise PermissionError(f"Registered frozen strategy identity/tenant changed for {name}")
        actual_code = hashlib.sha256((strategy.get("code") or "").encode()).hexdigest()
        if (binding["runtime_code_sha256"] != current_hash or
                actual_code != binding.get("strategy_code_sha256")):
            raise PermissionError(f"Registered strategy code version changed for {name}")
    return bindings


async def get_accounts(user_id: str, tenant_id: str) -> dict:
    runtime = paper_runtime()
    root = scoped_ledger_root(user_id, tenant_id)
    binding_path = root / "bindings.json"
    if not binding_path.exists():
        return {"accounts": [{"name": name, "state": "not_initialized",
                              "spec": runtime.frozen_specs()[name]} for name in runtime.ACCOUNTS],
                "disclaimer": runtime.DISCLAIMER, "trading_permission": False}
    bindings = json.loads(binding_path.read_text())
    await validate_bindings(bindings, user_id, tenant_id)
    view = runtime.snapshot(root)
    for item in view["accounts"]:
        identity = item.get("identity")
        if identity and (identity.get("owner") != {"user_id": str(user_id), "tenant_id": str(tenant_id)} or
                         identity.get("registry") != bindings["accounts"][item["name"]]):
            raise PermissionError("Persisted ledger identity does not match native registered owner/version")
    return {**view, "disclaimer": runtime.DISCLAIMER, "trading_permission": False}
