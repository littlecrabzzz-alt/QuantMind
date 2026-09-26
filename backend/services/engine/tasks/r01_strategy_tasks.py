"""R01 adapter on the existing Celery queue and BacktestPersistence."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.services.engine.qlib_app.celery_config import celery_app


def refresh_forward_calendar(registry_path: Path) -> dict:
    """One bounded, observed calendar request per day; prices stay archive-only."""
    import hashlib
    import httpx
    from zoneinfo import ZoneInfo
    from backend.shared.runtime_secrets import get_secret
    from backend.shared.tushare_intake import capture_sample
    registry = json.loads(registry_path.read_text())
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    prior = registry.get("calendar_snapshot", {})
    if prior.get("checked_date") == today.isoformat():
        raw = Path(prior["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != prior["sha256"]:
            raise ValueError("calendar_snapshot_checksum_mismatch")
        return prior
    root = registry_path.parent / "calendar-observations"
    job = {"api_name": "trade_cal", "params": {"exchange": "SSE",
        "start_date": f"{today.year}0101", "end_date": f"{today.year+1}1231"},
        "fields": "exchange,cal_date,is_open,pretrade_date", "row_cap": 6000,
        "required_fields": ["exchange", "cal_date", "is_open"], "nullable_fields": ["pretrade_date"]}
    with httpx.Client(trust_env=False, timeout=30, follow_redirects=False) as client:
        observation = capture_sample(client, get_secret("TUSHARE_TOKEN"), job, root)
    if observation.get("status") != "sample_ok":
        raise ValueError("forward_calendar_" + str(observation.get("status")))
    sha = observation["object_sha256"]
    path = root / "objects" / (sha + ".json")
    payload = json.loads(path.read_bytes())["data"]
    rows = [dict(zip(payload["fields"], r)) for r in payload["items"]]
    days = {r["cal_date"]: r for r in rows if r["exchange"] == "SSE"}
    if today.strftime("%Y%m%d") not in days or not any(
        d > today.strftime("%Y%m%d") and int(r["is_open"]) == 1 for d, r in days.items()):
        raise ValueError("forward_calendar_not_extended")
    snapshot = {"path": str(path), "sha256": sha, "checked_date": today.isoformat(),
        "obtained_at": datetime.now(timezone.utc).isoformat(),
        "observation": observation, "last_date": max(days), "source": "tushare:trade_cal"}
    registry["calendar_snapshot"] = snapshot
    pending = registry_path.with_suffix(".pending")
    pending.write_text(json.dumps(registry, ensure_ascii=False, indent=2))
    os.replace(pending, registry_path)
    return snapshot


@celery_app.task(name="engine.tasks.r01_strategy_backtest", bind=True, acks_late=True,
                 reject_on_worker_lost=True, max_retries=32)
def run_strategy_backtest(self, backtest_id: str, user_id: str, tenant_id: str):
    import redis
    from backend.services.engine.qlib_app.services.backtest_persistence import BacktestPersistence
    from backend.services.engine.qlib_app.schemas.backtest import QlibBacktestResult
    from backend.shared.strategy_storage import get_strategy_storage_service
    client = redis.from_url(os.environ["REDIS_URL"])
    lock = client.lock(f"quantmind:r01:backtest:{backtest_id}", timeout=900, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        raise self.retry(countdown=30)

    async def execute():
        bp = BacktestPersistence()
        row = await bp.get_run(backtest_id, user_id, tenant_id)
        if not row:
            raise ValueError("owned_run_not_found")
        if row["status"] in ("completed", "failed"):
            return {"backtest_id": backtest_id, "status": row["status"]}
        cfg, created = row["config_json"], row["created_at"]
        result = QlibBacktestResult(backtest_id=backtest_id, user_id=user_id,
            tenant_id=tenant_id, status="running", config=cfg, created_at=created,
            annual_return=None, sharpe_ratio=None, max_drawdown=None)
        await bp.save_run(backtest_id, user_id, tenant_id, "running", created, cfg, result)
        try:
            revisions = await get_strategy_storage_service().revisions(
                cfg["strategy_id"], user_id, tenant_id, cfg["strategy_revision"])
            if not revisions:
                raise ValueError("published_revision_missing")
            payload = {"revision": revisions[0], "request": {**cfg, "backtest_id": backtest_id},
                       "package_root": os.environ["R01_PACKAGE_ROOT"]}
            root = Path(__file__).resolve().parents[4]
            # No DB, auth, Redis or provider credentials reach strategy code.
            env = {k: os.environ[k] for k in ("PATH", "LANG", "TZ") if k in os.environ}
            env.update(PYTHONPATH=str(root), OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
            completed = subprocess.run([sys.executable, "-m",
                "backend.services.simulation.replay.strategy_run"],
                input=json.dumps(payload), text=True, capture_output=True,
                cwd="/tmp", env=env, timeout=660, check=True)
            data = json.loads(completed.stdout)
            data.update(created_at=created, completed_at=datetime.now(timezone.utc))
            # Preserve the reservation's immutable request for idempotent retries.
            data["config"] = cfg | data["config"]
            result = QlibBacktestResult(**data)
        except Exception as exc:
            detail = str(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                detail = (exc.stderr or detail)[-1800:]
            result.status, result.error_message = "failed", detail
            result.completed_at = datetime.now(timezone.utc)
        await bp.save_run(backtest_id, user_id, tenant_id, result.status, created,
                          cfg, result, completed_at=result.completed_at)
        from backend.services.engine.qlib_app.cache_manager import get_cache_manager
        cache = get_cache_manager()
        cache.invalidate_user_history(f"{tenant_id}:{user_id}")
        cache.client.delete(*(cache.PREFIX_BACKTEST_RESULT + key for key in (
            backtest_id, f"{tenant_id}:{backtest_id}", f"{tenant_id}:{user_id}:{backtest_id}")))
        return {"backtest_id": backtest_id, "status": result.status,
                "error": result.error_message}

    try:
        async def scoped_execute():
            from backend.shared.database_manager_v2 import close_database
            try:
                return await execute()
            finally:
                await close_database()
        return asyncio.run(scoped_execute())
    finally:
        lock.release()


@celery_app.task(name="engine.tasks.r01_publish_daily_inputs", acks_late=True)
def publish_daily_inputs():
    """Adapt the existing verified archive publisher; never mutate the v2 baseline."""
    import redis
    import tempfile
    import shutil
    client = redis.from_url(os.environ["REDIS_URL"])
    status_key = "quantmind:r01:vr:publisher_status"
    lock = client.lock("quantmind:r01:vr:publisher_lock", timeout=1800, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "busy"}
    archive = Path(os.environ["R01_SOURCE_ARCHIVE"])
    registry_path = Path(os.environ["R01_VR_REGISTRY"])
    output = registry_path.parent / "daily"
    source_id = None
    try:
        calendar = refresh_forward_calendar(registry_path)
        source_id = json.loads((archive / "CURRENT.json").read_text())["release_id"]
        prior = json.loads(client.get(status_key) or "{}")
        if prior.get("source_release_id") == source_id and prior.get("status") == "published":
            prior["calendar_through"] = calendar["last_date"]
            prior["calendar_sha256"] = calendar["sha256"]
            client.set(status_key, json.dumps(prior, ensure_ascii=False))
            return prior
        registry = json.loads(registry_path.read_text())
        root = Path(__file__).resolve().parents[4]
        output.mkdir(parents=True, exist_ok=True)
        def publish_one(day=None):
            with tempfile.TemporaryDirectory(prefix="publish-", dir=output.parent) as temp:
                tmp = Path(temp)
                tmp_registry = tmp / "registry.json"
                tmp_registry.write_text(json.dumps(registry))
                args = [sys.executable, str(root / "scripts/publish_r01_daily_inputs.py"),
                    "--root", str(archive), "--release-id", source_id,
                    "--output-root", str(tmp / "packages"), "--registry", str(tmp_registry), "--workers", "2"]
                if day:
                    args += ["--decision-date", day.replace("-", "")]
                proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
                manifests = list((tmp / "packages").glob("*/manifest.json"))
                manifest = json.loads(manifests[0].read_text()) if manifests else {}
                if proc.returncode:
                    reasons = (manifest.get("quality_gate") or {}).get("blocked_reasons")
                    raise ValueError(json.dumps(reasons, ensure_ascii=False) if reasons else (proc.stderr or proc.stdout)[-1200:])
                uri = manifest["package_uri"]
                entry = json.loads(tmp_registry.read_text())["packages"][uri]
                from backend.services.simulation.replay.etf_input_package import verify_package_files
                entry["package_sums_sha256"] = verify_package_files(manifests[0].parent)
                # Published day inputs are immutable. A supplier revision needs a
                # separate explicit revision package; do not rewrite consumed data.
                if uri not in registry["packages"]:
                    target = output / entry["package_version"]
                    if target.exists():
                        raise ValueError("unregistered output exists; review before publication")
                    shutil.move(str(manifests[0].parent), target)
                    entry["absolute_path"] = str(target)
                    registry["packages"][uri] = entry
                    pending = registry_path.with_suffix(".pending")
                    pending.write_text(json.dumps(registry, ensure_ascii=False, indent=2))
                    os.replace(pending, registry_path)
                return manifest
        latest = publish_one()
        latest_date = latest["decision_date"]
        # Fill missed *input* days, never backdate decisions. Calendar comes from
        # the same published source release; each input still has obtained_at.
        import pandas as pd
        current_entry = registry["packages"][latest["package_uri"]]
        cal = pd.read_parquet(Path(current_entry["absolute_path"]) / "calendar.parquet")
        from backend.services.simulation.replay.etf_input_package import load_etf_input_package
        cutoff = load_etf_input_package(os.environ["R01_PACKAGE_ROOT"]).actual_max_input_date.isoformat()
        have = {e.get("decision_date") for e in registry["packages"].values()}
        missing = sorted(str(v) for v in cal.loc[cal["is_open"] == 1, "cal_date"]
            if cutoff.replace("-", "") < str(v) <= latest_date.replace("-", "")
            and f"{str(v)[:4]}-{str(v)[4:6]}-{str(v)[6:8]}" not in have)
        if len(missing) > 10:
            raise ValueError("more than 10 missing input days; bounded backfill required")
        for day in missing:
            publish_one(day)
        result = {"status": "published", "source_release_id": source_id,
            "calendar_through": calendar["last_date"], "calendar_sha256": calendar["sha256"],
            "input_source_release_id": current_entry.get("source_release_id"),
            "data_date": latest_date, "checked_at": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        result = {"status": "blocked", "source_release_id": source_id,
            "error": f"{type(exc).__name__}: {exc}", "checked_at": datetime.now(timezone.utc).isoformat()}
    finally:
        lock.release()
    client.set(status_key, json.dumps(result, ensure_ascii=False))
    return result
