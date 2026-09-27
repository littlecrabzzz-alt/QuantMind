"""Serialize stock factor work on the SAME research compute queue as ETF work."""

import asyncio
import csv
import os
import time
from datetime import datetime, timezone
from backend.services.engine.qlib_app.celery_config import celery_app


def invalidate_result(bid, user, tenant):
    from backend.services.engine.qlib_app.cache_manager import get_cache_manager

    cache = get_cache_manager()
    cache.invalidate_user_history(f"{tenant}:{user}")
    cache.client.delete(
        *(
            cache.PREFIX_BACKTEST_RESULT + key
            for key in (bid, f"{tenant}:{bid}", f"{tenant}:{user}:{bid}")
        )
    )


@celery_app.task(
    name="engine.tasks.continuous_stock",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=240,
    time_limit=7500,
    soft_time_limit=7350,
)
def run_stock_research(self, bid, user, tenant):
    import redis
    from backend.services.engine.research import runtime
    from backend.services.engine.qlib_app.services.backtest_persistence import (
        BacktestPersistence,
    )
    from backend.services.engine.qlib_app.schemas.backtest import QlibBacktestResult

    client = redis.from_url(os.environ["REDIS_URL"])
    lock = client.lock(
        "quantmind:continuous-stock:" + bid, timeout=7500, blocking_timeout=0
    )
    if not lock.acquire(blocking=False):
        raise self.retry(countdown=30)

    async def run():
        bp = BacktestPersistence()
        row = await bp.get_run(bid, user, tenant)
        if not row:
            raise ValueError("owned_backtest_missing")
        if row["status"] in ("completed", "failed"):
            return row["status"]
        cfg = row["config_json"]
        contract = cfg["stock_contract"]
        config = cfg["experiment_config"]
        if any(v[1] > contract["boundary"] for v in config["split"].values()):
            raise ValueError("stock_holdout_boundary_violation")
        directory = runtime.case_directory(cfg["research_id"])
        experiment = {
            "id": bid,
            "container_name": "qm-glm-" + bid,
            "proposal": cfg["proposal"],
        }
        result = QlibBacktestResult(
            backtest_id=bid,
            user_id=user,
            tenant_id=tenant,
            status="running",
            config=cfg,
            annual_return=None,
            sharpe_ratio=None,
            max_drawdown=None,
        )
        await bp.save_run(bid, user, tenant, "running", row["created_at"], cfg, result)
        invalidate_result(bid, user, tenant)
        try:
            deadline = time.time() + 7200
            while time.time() < deadline:
                container = await asyncio.to_thread(
                    runtime.launch, directory, experiment, config, contract, deadline
                )
                if container:
                    break
                await asyncio.sleep(10)
            else:
                raise ValueError("heavy_compute_unavailable")
            while True:
                data = await asyncio.to_thread(
                    runtime.observe, directory, experiment, contract
                )
                if data is not None:
                    break
                await asyncio.sleep(10)
            metrics = data["summary"]["comparison"]["model"]
            out = directory / "experiments" / bid
            with (out / "model-equity.csv").open() as f:
                curve = [
                    {"date": r["date"], "value": float(r["account"])}
                    for r in csv.DictReader(f)
                ]
            if any(r["date"] > contract["boundary"] for r in curve):
                raise ValueError("returned_holdout_curve_rejected")
            with (out / "model-trades.csv").open() as f:
                trades = [
                    {
                        **r,
                        "quantity": float(r["adjusted_quantity"]),
                        "price": float(r["adjusted_price"]),
                        "commission": float(r["cost"]),
                        "amount": float(r["amount"]),
                        "totalAmount": float(r["amount"]),
                        "cash_after": float(r["cash_after"]),
                        "fee_basis": "total_execution_cost",
                        "quantity_price_basis": "adjusted",
                    }
                    for r in csv.DictReader(f)
                ]
            with (out / "model-positions.csv").open() as f:
                positions = list(csv.DictReader(f))
            high = float(config["portfolio"]["initial_capital"])
            drawdown = []
            for point in curve:
                high = max(high, point["value"])
                drawdown.append(
                    {"date": point["date"], "value": point["value"] / high - 1}
                )
            factor = data.get("factor_analysis") or {}
            compact = {
                name: {k: v for k, v in value.items() if k != "daily"}
                for name, value in factor.get("splits", {}).items()
            }
            result = QlibBacktestResult(
                backtest_id=bid,
                user_id=user,
                tenant_id=tenant,
                status="completed",
                config=cfg,
                created_at=row["created_at"],
                completed_at=datetime.now(timezone.utc),
                annual_return=None,
                sharpe_ratio=metrics.get("sharpe"),
                max_drawdown=metrics["max_drawdown"],
                total_return=metrics["total_return"],
                total_trades=metrics["trades"],
                equity_curve=curve,
                drawdown_curve=drawdown,
                trades=trades,
                positions=positions,
                benchmark_return=metrics.get("benchmark_return"),
                signal_lag_days=1,
                deal_price="close",
                benchmark_symbol=contract["base_config"]["portfolio"].get("benchmark"),
                long_short_is_theoretical=False,
                factor_metrics=factor,
                advanced_stats={
                    "verification": data["verification"],
                    "comparison": data["summary"]["comparison"],
                    "factor_summary": compact,
                    "artifacts": data["artifacts"],
                    "validation_status": "development_only_unreviewed",
                },
            )
        except Exception as exc:
            result.status = "failed"
            result.error_message = str(exc)[:1800]
        await bp.save_run(
            bid,
            user,
            tenant,
            result.status,
            row["created_at"],
            cfg,
            result,
            datetime.now(timezone.utc),
        )
        invalidate_result(bid, user, tenant)
        return result.status

    try:
        return asyncio.run(run())
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass
