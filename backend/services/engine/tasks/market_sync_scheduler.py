"""市场定时同步调度器。

前端每个市场 tab 可配置每天 HH:MM 定时同步上游数据（精确到分钟）。
配置存 Redis（db 0，key: quantmind:sync_schedule:{market}），
Celery beat 每分钟触发 dispatch_market_sync 检查是否有市场到点，
到点则派发对应市场同步任务（Redis 记录 last_run 防止重复触发）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from backend.shared.quantdb_sync_jobs import has_sync_errors as _has_sync_errors

logger = logging.getLogger(__name__)

_SCHEDULE_KEY = "quantmind:sync_schedule:{market}"
_LAST_RUN_KEY = "quantmind:sync_schedule_last_run:{market}:{date}"

# market -> (标签, 同步任务名)
MARKETS = {
    "A": "QuantDB A股",
    "US": "QuantUS 美股",
    "HK": "QuantHK 港股",
    "BC": "QuantBC 区块链",
    "FUTURES": "QuantFutures 期货",
}

DEFAULT_SCHEDULE = {
    "enabled": False,
    "time": "03:00",
    "days": 5,
    "datasets": [],
    "with_qlib": False,
}

# 各市场在无 Redis 配置时的默认定时（显式保存的配置总是覆盖这里的值）。
# 未列入的市场保持 enabled=False，需要在前端手动开启。
# A 股与其他市场统一走 Redis 配置；旧独立 daily-data-sync 已移除。
# 各海外市场默认时间：
#   HK       23:50  雅虎/akshare/CCASS 晚间陆续就绪，晚间错峰
#   US       05:30  美股收盘(北京约 04:00/05:00)后，EOD 数据已稳定
#   BC       08:15  UTC 日线于北京时间 08:00 闭合，随后拉取
#   US       05:30  美股收盘(北京约 04:00/05:00)后，EOD 数据已稳定
MARKET_SUGGESTED_TIMES: dict[str, str] = {
    "A": "01:00",
    "HK": "02:00",
    "FUTURES": "03:00",
    "BC": "08:15",
    "US": "05:30",
}


def _redis():
    import redis

    return redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"), socket_timeout=3
    )


def _normalize(cfg: dict[str, Any] | None, market: str | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_SCHEDULE)
    # 建议时间只用于预填，不会把 enabled 置为 True
    if market is not None and market in MARKET_SUGGESTED_TIMES:
        out["time"] = MARKET_SUGGESTED_TIMES[market]
    for k in out:
        if k in (cfg or {}):
            out[k] = cfg[k]
    # 校验 time 格式 HH:MM；非法时回退到全局默认时间
    t = str(out["time"]).strip()
    try:
        datetime.strptime(t, "%H:%M")
        out["time"] = t
    except ValueError:
        out["time"] = DEFAULT_SCHEDULE["time"]
    return out


def get_schedule(market: str) -> dict[str, Any]:
    r = _redis()
    raw = r.get(_SCHEDULE_KEY.format(market=market))
    cfg = json.loads(raw) if raw else None
    return _normalize(cfg, market)


def get_all_schedules() -> dict[str, dict[str, Any]]:
    return {m: get_schedule(m) for m in MARKETS}


def save_schedule(market: str, cfg: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize(cfg, market)
    r = _redis()
    r.set(
        _SCHEDULE_KEY.format(market=market),
        json.dumps(normalized, ensure_ascii=False),
    )
    return normalized


def _last_run_today(market: str, date_str: str) -> bool:
    r = _redis()
    return r.exists(_LAST_RUN_KEY.format(market=market, date=date_str)) > 0


def _mark_run(market: str, date_str: str, ttl: int = 2 * 24 * 3600) -> None:
    r = _redis()
    r.set(
        _LAST_RUN_KEY.format(market=market, date=date_str),
        "1",
        ex=ttl,
    )


def run_market_sync(market: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """执行指定市场的同步（按配置的数据集/天数）。"""
    days = int(cfg.get("days") or 5)
    datasets = cfg.get("datasets") or []
    with_qlib = bool(cfg.get("with_qlib"))

    result: dict[str, Any] = {"market": market, "started": datetime.now().isoformat()}

    if market == "A":
        from backend.scripts.quantdb_daily_sync import run_daily_sync

        from uuid import uuid4
        from backend.shared.quantdb_sync_jobs import (
            acquire_lock, release_lock, new_celery_job, celery_progress_cb,
            upsert_job, _now_iso,
        )

        token = uuid4().hex
        key = "quantmind:daily_sync:lock"
        if not acquire_lock(key, token, ttl=7200):
            # Publishing a snapshot must not consume today's acquisition slot.
            _mark_run(market, datetime.now().strftime("%Y-%m-%d"), ttl=900)
            return {"market": market, "status": "skipped", "reason": "sync busy or Redis unavailable"}
        job_id = None
        try:
            job_id = new_celery_job(datasets=datasets or None, with_pg=True, with_qlib=with_qlib)["job_id"]
            data = run_daily_sync(datasets=datasets or None, skip_pg=False,
                                  skip_qlib=not with_qlib,
                                  progress_cb=celery_progress_cb(job_id))
            failed = _has_sync_errors(data)
            result.update(result=data, job_id=job_id,
                          status="partial" if failed else "completed",
                          finished=datetime.now().isoformat())
            upsert_job(job_id, status="failed" if failed else "completed",
                       stage="done", finished_at=_now_iso())
            return result
        except Exception:
            if job_id:
                upsert_job(job_id, status="failed", finished_at=_now_iso())
            raise
        finally:
            release_lock(key, token)

    if market == "US":
        from backend.scripts.quantus_daily_sync import run
    elif market == "HK":
        from backend.scripts.quanthk_daily_sync import run
    elif market == "BC":
        from backend.scripts.quantbc_daily_sync import run
    elif market == "FUTURES":
        from backend.scripts.quantfutures_daily_sync import run
    else:
        return {"market": market, "error": f"未知市场: {market}"}

    kwargs: dict[str, Any] = {"days": days}
    if datasets:
        kwargs["datasets"] = list(datasets)
    result["result"] = run(**kwargs)

    if with_qlib:
        # 数据拉取阶段若被上游限流拖长，再重建 qlib 缓存会超出任务硬超时被 SIGKILL。
        # 这里按已耗时判断剩余时间是否够用，不够则跳过并在结果里标记 skipped。
        elapsed = (datetime.now() - datetime.fromisoformat(result["started"])).total_seconds()
        budget = float(os.getenv("MARKET_SYNC_SOFT_TIME_LIMIT", "1800"))
        if elapsed > budget * 0.5:
            logger.error(
                "[SyncSchedule] %s 数据拉取已耗时 %.0fs，超过预算 %.0fs 的一半，跳过 qlib 缓存重建",
                market,
                elapsed,
                budget,
            )
            result["qlib"] = {
                "status": "skipped",
                "reason": f"data stage took {elapsed:.0f}s, too long to rebuild qlib cache",
            }
        else:
            try:
                from backend.services.engine.qlib_data_builder import ensure_qlib_cache

                qlib_market = {
                    "US": "US",
                    "HK": "HK",
                    "BC": "CRYPTO",
                    "FUTURES": "FUTURES",
                }[market]
                if market == "BC":
                    from backend.scripts.quantbc_daily_sync import prepare_research_data
                    prepared = prepare_research_data(result["result"]["data_dir"])
                    result["qlib"] = {"status": "ok", "provider_uri": prepared["qlib_dir"], "research_data": prepared}
                else:
                    result["qlib"] = {
                        "status": "ok",
                        "provider_uri": ensure_qlib_cache(market=qlib_market),
                    }
            except Exception as exc:  # noqa: BLE001
                logger.error("%s 定时同步 qlib 缓存失败: %s", market, exc, exc_info=True)
                result["qlib"] = {"status": "error", "reason": str(exc)}

    research_incomplete = (
        market == "BC" and with_qlib and (result.get("qlib") or {}).get("status") != "ok"
    )
    result["status"] = "partial" if research_incomplete or _has_sync_errors(result) else "completed"
    result["finished"] = datetime.now().isoformat()
    return result


def dispatch_due_syncs() -> dict[str, Any]:
    """检查所有市场定时配置，到点或错过时间且今天未派发的同步任务。"""
    from backend.services.engine.qlib_app.celery_config import celery_app

    now = datetime.now()
    now_hm = now.strftime("%H:%M")
    date_str = now.strftime("%Y-%m-%d")
    dispatched: list[str] = []

    for market in MARKETS:
        cfg = get_schedule(market)
        if not cfg.get("enabled"):
            continue
        if cfg.get("time") > now_hm:
            continue
        if _last_run_today(market, date_str):
            continue
        celery_app.send_task(
            "engine.tasks.run_market_scheduled_sync",
            args=[market, cfg],
            queue="market_sync",
        )
        _mark_run(market, date_str)
        dispatched.append(market)
        logger.info("[SyncSchedule] %s 到点 %s，已派发同步任务", MARKETS[market], now_hm)

    return {"now": now_hm, "dispatched": dispatched}
