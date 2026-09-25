"""R01 虚拟运行调度器（H2.2 任务5：复用 market_sync_scheduler 模式）。

- 调度配置存 Redis db0 ``quantmind:r01:vr:schedule:{ledger_run_id}``
  （JSON：enabled + 冻结运行配置字段）；**无内置默认调度**——未配置或
  未启用即不派发任何任务（对齐 AGENTS「市场数据同步不内置默认调度」
  的既有模式），平台显示 pending_activation；
- Celery beat 每几分钟触发 ``dispatch_due_runs``（见 celery 配置
  ``r01-virtual-run-dispatch`` 条目），到点派发幂等任务
  ``engine.tasks.r01_virtual_run_daily``（队列=default，由既有唯一
  celery worker 消费；不新增 worker）；
- 任务幂等由流水线阶段键+日锁保证：重复派发/双 worker 安全；
- 派发去重键 ``quantmind:r01:vr:dispatch:{run}:{date}:{phase}``（TTL 2 天）。

真实日增量包联调（待 p02 D1/D2 合入）：当前 provider=StaticPackageProvider
fixture stub，见 virtual_run/gating.py 注记。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

from backend.services.simulation.virtual_run.states import (
    VirtualRunConfig,
    get_redis_schedule,
    list_redis_schedules,
    save_redis_schedule,
)

logger = logging.getLogger(__name__)

_DISPATCH_KEY = "quantmind:r01:vr:dispatch:{run}:{date}:{phase}"
_TASK_NAME = "engine.tasks.r01_virtual_run_daily"


def _redis():
    import redis

    return redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"), socket_timeout=3
    )


# ---------------------------------------------------------------------------
# 调度配置读写（无默认开启）
# ---------------------------------------------------------------------------


def get_run_config(ledger_run_id: str) -> tuple[VirtualRunConfig, dict] | None:
    """读调度配置 → (冻结运行配置, 原始调度 JSON)；未配置返回 None。"""
    cfg = get_redis_schedule(_redis(), ledger_run_id)
    if cfg is None:
        return None
    return VirtualRunConfig.from_dict(cfg), cfg


def save_run_config(
    ledger_run_id: str, config: VirtualRunConfig, *, enabled: bool = False
) -> dict:
    """保存运行配置+调度开关（默认不启用；启用候选来自研究冻结方案）。"""
    payload = {**config.to_dict(), "enabled": enabled}
    return save_redis_schedule(_redis(), ledger_run_id, payload)


def list_run_ids() -> list[str]:
    return sorted(list_redis_schedules(_redis()))


# ---------------------------------------------------------------------------
# 流水线构建（生产入口：SystemClock + Redis 锁/状态 + PG 检查点）
# ---------------------------------------------------------------------------


def build_pipeline(config: VirtualRunConfig, schedule_cfg: dict | None = None):
    """生产/沙盒构建（重导入以避免 celery 进程早绑定）。

    J6R4 #1：构建入口接真实包源与平台回报（与 dispatcher 同一接法）——
    DailyIncrementProvider（v2 基线+日增量注册表，逐项哈希复验/迟到过滤）
    + reporter（R01_VR_AGENT_BASE 未配置则仅状态键+心跳，不外报）。
    """
    from backend.services.simulation.virtual_run.gating import (
        DailyIncrementProvider,
    )
    from backend.services.simulation.virtual_run.locks import RedisLockBackend
    from backend.services.simulation.virtual_run.pipeline import VirtualRunPipeline
    from backend.services.simulation.virtual_run.recovery import DbCheckpointStore
    from backend.services.simulation.virtual_run.states import (
        RedisRunStateStore,
        post_platform_status,
    )

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    provider = DailyIncrementProvider(
        config.package_root,
        baseline_manifest_sha256=config.manifest_sha256,
        registry_path=os.getenv("R01_VR_REGISTRY") or None,
        cache_dir=os.getenv("R01_VR_MERGE_CACHE") or None,
    )
    dsn = os.getenv("DATABASE_URL") or _pg_dsn_from_env()

    agent_base = os.getenv("R01_VR_AGENT_BASE")
    reporter = None
    if agent_base:
        secret = os.getenv("INTERNAL_CALL_SECRET", "")

        def reporter(payload: dict) -> dict:  # noqa: F811
            return post_platform_status(
                payload,
                base_url=agent_base,
                internal_secret=secret,
                node=os.getenv("R01_VR_NODE") or None,
            )

    return VirtualRunPipeline(
        config,
        provider,
        lock_backend=RedisLockBackend(redis_url),
        state_store=RedisRunStateStore(redis_url),
        checkpoint_store=DbCheckpointStore(dsn),
        schedule_cfg=schedule_cfg,
        platform_reporter=reporter,
    )


def _pg_dsn_from_env() -> str:
    user = os.getenv("DB_USER", "quantmind")
    pwd = os.getenv("DB_PASSWORD", "quantmind")
    host = os.getenv("DB_HOST", "db")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "quantmind")
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{name}"


# ---------------------------------------------------------------------------
# 到点派发（beat 周期调用；无配置=no-op）
# ---------------------------------------------------------------------------


def dispatch_due_runs(
    now: datetime | None = None, *, r=None, store=None
) -> dict[str, Any]:
    """检查全部已配置运行：决策截止到点 / 执行窗口到点 → 派发幂等任务。

    ``r``/``store`` 可注入（测试）；默认真实 Redis db0。J4R2 #3：包源统一
    走 DailyIncrementProvider（真实日增量注册表，含日历/哈希复验），
    不再用 fixture stub。
    """
    from backend.services.simulation.virtual_run.clock import (
        SystemClock,
        local_wall,
        parse_hhmm,
    )
    from backend.services.simulation.virtual_run.gating import (
        DailyIncrementProvider,
    )
    from backend.services.simulation.virtual_run.states import RedisRunStateStore

    now = now or SystemClock().now()
    r = r or _redis()
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    store = store or RedisRunStateStore(redis_url)
    dispatched: list[str] = []
    skipped: list[str] = []

    for run_id, sched in list_redis_schedules(r).items():
        if not sched.get("enabled"):
            continue
        try:
            config = VirtualRunConfig.from_dict(sched)
        except Exception as exc:  # noqa: BLE001
            logger.error("[R01VR] %s 调度配置非法：%s", run_id, exc)
            skipped.append(f"{run_id}(bad_config)")
            continue
        tz = config.tz
        wall = local_wall(now, tz)
        today = wall.date()
        wall_hm = wall.strftime("%H:%M")

        provider = DailyIncrementProvider(
            config.package_root,
            baseline_manifest_sha256=config.manifest_sha256,
            registry_path=os.getenv("R01_VR_REGISTRY") or None,
            cache_dir=os.getenv("R01_VR_MERGE_CACHE") or None,
        )
        pkg = provider.package

        # -- 决策相位：今天是包交易日、过决策截止、当日未收口 --------
        if pkg.is_trade_date(today) and wall_hm >= config.decision_cutoff:
            day_rec = store.get_day(run_id, today.isoformat())
            outcome = (day_rec or {}).get("outcome")
            needs_run = day_rec is None or not outcome or outcome == "data_blocked"
            if needs_run and outcome == "data_blocked":
                exec_day = pkg.next_trade_date(today)
                if exec_day is not None and wall >= datetime.combine(
                    exec_day, parse_hhmm(config.execution_time), tzinfo=tz
                ):
                    needs_run = False  # 窗口已过：受阻终态（近3日循环标注）
            if needs_run:
                if _dispatch_once(r, run_id, today, "decision", ttl=600):
                    _send(run_id, today)
                    dispatched.append(f"{run_id}:decision:{today}")
                else:
                    skipped.append(f"{run_id}:decision:{today}(dup/retry-wait)")

        # -- 受阻重派（J5R3 #4 / J6R4 #3）：近 3 个**交易日**（交易日历
        #    口径，周一可覆盖周五；非自然日）内的受阻日（含隔夜补数），
        #    窗口（次一交易日执行时点）内数据补齐后自动重新门控执行 ----
        for d in _recent_trade_dates(provider, pkg, today, 3):
            if d == today or not pkg.is_trade_date(d):
                continue
            rec = store.get_day(run_id, d.isoformat())
            if (rec or {}).get("outcome") != "data_blocked":
                continue
            if store.get_stage(run_id, d.isoformat(), "execute") is not None:
                continue  # 已恢复执行
            exec_day = pkg.next_trade_date(d)
            if exec_day is not None and wall >= datetime.combine(
                exec_day, parse_hhmm(config.execution_time), tzinfo=tz
            ):
                skipped.append(f"{run_id}:decision:{d}(blocked-final)")
                continue  # 窗口已过：受阻终态，不补写
            if _dispatch_once(r, run_id, d, "decision", ttl=600):
                _send(run_id, d)
                dispatched.append(f"{run_id}:decision:{d}")

        # -- 执行相位（H2-AC02：按交易日回看，非自然日）：近 8 个交易日内
        #    的待执行决策（signal 有、execute 无）、执行日=今天（行情视图
        #    或日历口径——前沿无行情时也派发，任务内如实记录可恢复受阻）、
        #    窗口已开；长休市（相距 8/9+ 自然日）不漏派 -------------
        for d in _recent_trade_dates(provider, pkg, today, 8):
            if not pkg.is_trade_date(d):
                continue
            exec_date = pkg.next_trade_date(d) or provider.next_open_trade_date(d)
            if exec_date != today:
                continue
            gate = provider.resolve(d, symbols=sorted(config.target_weights), now=now)
            if gate.status != "ready":
                continue  # 数据受阻/休市：无待执行
            if store.get_stage(run_id, d.isoformat(), "execute") is not None:
                continue  # 执行阶段已收口
            if store.get_stage(run_id, d.isoformat(), "signal") is None:
                continue  # 决策未发生（错过→不补写）
            win_start = datetime.combine(
                today, parse_hhmm(config.execution_time), tzinfo=tz
            )
            if wall < win_start:
                continue
            if _dispatch_once(r, run_id, d, "execute", ttl=600):
                _send(run_id, d)
                dispatched.append(f"{run_id}:execute:{d}")

    return {"now": now.isoformat(), "dispatched": dispatched, "skipped": skipped}


def _recent_dates(today: date, days: int) -> list[date]:
    return [today - timedelta(days=i) for i in range(days)]


def _recent_trade_dates(provider, pkg, today: date, n: int) -> list[date]:
    """近 n 个交易日（J6R4 #3：交易日历口径，非自然日——周一能覆盖周五）。

    优先 provider 日历（日包 calendar.parquet，覆盖基线之后），回退
    合并包日历（基线内日期）。
    """
    out: list[date] = []
    probe = today
    for _ in range(60):  # 覆盖长假（春节等 8+ 自然日间隔）
        if len(out) >= n:
            break
        probe = date.fromordinal(probe.toordinal() - 1)
        if pkg.is_trade_date(probe):
            out.append(probe)
            continue
        try:
            if (
                provider.next_open_trade_date(date.fromordinal(probe.toordinal() - 1))
                == probe
            ):
                out.append(probe)
        except Exception:  # noqa: BLE001
            continue
    return out


def _dispatch_once(r, run_id: str, d: date, phase: str, *, ttl: int) -> bool:
    """同 相位+日期 派发去重；TTL=短暂窗口（任务幂等，重复派发安全；
    失败/崩溃后下轮 beat 可重派，直到窗口截止由流水线收口）。"""
    key = _DISPATCH_KEY.format(run=run_id, date=d.isoformat(), phase=phase)
    return bool(r.set(key, "1", nx=True, ex=ttl))


def _send(run_id: str, decision_date: date) -> None:
    from backend.services.engine.qlib_app.celery_config import celery_app

    celery_app.send_task(_TASK_NAME, args=[run_id, decision_date.isoformat()])


# ---------------------------------------------------------------------------
# worker 任务体（celery_tasks.py 包装调用）
# ---------------------------------------------------------------------------


def run_scheduled_day(
    ledger_run_id: str, decision_date: str | None = None
) -> dict[str, Any]:
    """执行（或续跑）某运行的一个决策日；异常向上抛由任务包装记录。

    J4R2 #3：任务入口复查 enabled——运行中被禁用即停（不推进新决策日）。
    """
    from backend.services.simulation.virtual_run.clock import local_wall

    got = get_run_config(ledger_run_id)
    if got is None:
        return {
            "ledger_run_id": ledger_run_id,
            "status": "pending_activation",
            "detail": "未配置调度（待启用），不运行",
        }
    _config, sched = got
    if not sched.get("enabled"):
        return {
            "ledger_run_id": ledger_run_id,
            "status": "stopped_by_config",
            "detail": "调度已被禁用：入口即停，不推进决策日",
        }
    config, sched = got
    pipeline = build_pipeline(config, schedule_cfg=sched)
    try:
        if decision_date is None:
            wall = local_wall(pipeline.clock.now(), config.tz)
            decision_date = wall.date().isoformat()
        result = pipeline.run_day(date.fromisoformat(decision_date))
        return {"ledger_run_id": ledger_run_id, **result.to_dict()}
    finally:
        cp = getattr(pipeline.checkpoints, "close", None)
        if callable(cp):
            cp()


# ---------------------------------------------------------------------------
# p03 配置载体消费（H2.1-L3：r01_virtual_run_config 表 → 冻结运行配置）
# ---------------------------------------------------------------------------


def virtual_run_config_from_pg_row(row) -> VirtualRunConfig:
    """p03 ``r01_virtual_run_config`` ORM 行 → runner 冻结配置（L3 消费端）。

    - 账本引擎参数经 p03 ``virtual_ledger_config_from_row`` 同源口径映射；
    - 调度语义/目标权重来自 execution_window JSONB（p03 载体表的自由
      JSON 段：target_weights/decision_cutoff/execution_time/
      window_timeout_minutes/missed_window_policy/entry_policy/timezone）；
    - data_source 段记 v2 基线包路径与 manifest sha。
    启用候选由研究冻结方案写入该表；本函数只读映射，不改表。
    """
    ew = dict(getattr(row, "execution_window", None) or {})
    ds = dict(getattr(row, "data_source", None) or {})
    risk = dict(getattr(row, "risk_config", None) or {})
    cfg = VirtualRunConfig(
        group=row.group,
        strategy_id=row.strategy_id,
        strategy_version=int(row.strategy_version),
        initial_cash=float(row.initial_cash),
        target_weights=dict(ew.get("target_weights") or {}),
        loss_line_amount=risk.get("loss_line_amount"),
        drawdown_pct=float(risk.get("drawdown_pct", 0.30)),
        commission_rate=float(risk.get("commission_rate", 0.0003)),
        commission_min=float(risk.get("commission_min", 0.0)),
        slippage_bps=float(risk.get("slippage_bps", 0.0)),
        price_mode=str(risk.get("price_mode", "open")),
        timezone_name=str(ew.get("timezone", "Asia/Shanghai")),
        decision_cutoff=str(ew.get("decision_cutoff", "15:10")),
        execution_time=str(ew.get("execution_time", "09:31")),
        window_timeout_minutes=int(ew.get("window_timeout_minutes", 30)),
        max_retries=int(ew.get("max_retries", 2)),
        missed_window_policy=str(ew.get("missed_window_policy", "skip_and_record")),
        entry_policy=str(ew.get("entry_policy", "first_decision_day")),
        package_root=str(ds.get("baseline_root", "")),
        manifest_sha256=str(ds.get("baseline_manifest_sha256", "")),
        notes=str(getattr(row, "source_plan_ref", "") or ""),
    )
    derived = cfg.ledger_run_id
    if getattr(row, "ledger_run_id", derived) != derived:
        raise ValueError(
            f"r01_virtual_run_config 行 ledger_run_id={row.ledger_run_id!r} "
            f"与派生身份 {derived!r} 不一致（组别/策略/版本与主键漂移）"
        )
    return cfg


def list_enabled_pg_run_configs(dsn: str) -> dict[str, tuple[VirtualRunConfig, dict]]:
    """读全部 enabled 的 r01_virtual_run_config 行（调度配置源=PG 载体时）。

    返回 {ledger_run_id: (冻结配置, 调度 JSON)}；调度 JSON 含 schedule_key
    指向的 Redis 配置（enabled/时点以 Redis schedule 键为运行口径，
    PG 行 enabled=False 的不加载——未配置=待启用不自动跑）。
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.services.simulation.models.replay import R01VirtualRunConfig as Row

    async def _run() -> dict[str, tuple[VirtualRunConfig, dict]]:
        engine = create_async_engine(dsn)

        async def _inner():
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as db:
                rows = (
                    (await db.execute(select(Row).where(Row.enabled.is_(True))))
                    .scalars()
                    .all()
                )
                out = {}
                for row in rows:
                    cfg = virtual_run_config_from_pg_row(row)
                    out[cfg.ledger_run_id] = (
                        cfg,
                        {
                            "enabled": True,
                            "from_pg_carrier": True,
                            "schedule_key": row.schedule_key,
                        },
                    )
                return out

        try:
            return await _inner()
        finally:
            await engine.dispose()

    return asyncio.run(_run())
