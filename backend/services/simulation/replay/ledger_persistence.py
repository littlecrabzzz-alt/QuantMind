"""R01 研究账本 checkpoint 的 PG 持久化（W2E3 修复#7）。

- save_checkpoint：按 ledger_run_id 幂等 upsert（同 run 重放保存覆盖，
  不产生第二行）；
- load_checkpoint：恢复 R01Ledger（R01Ledger.restore），可继续推演。

引擎本身纯内存确定性；本模块只做状态快照的存取，不参与账务计算。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.simulation.models.replay import ReplayLedgerCheckpoint
from backend.services.simulation.replay.etf_input_package import EtfInputPackage
from backend.services.simulation.replay.r01_ledger import (
    CheckpointPackageMismatch,
    R01Ledger,
    R01LedgerConfig,
)


async def save_checkpoint(db: AsyncSession, ledger: R01Ledger) -> None:
    """幂等 upsert 账本完整状态快照。"""
    state = ledger.export_checkpoint()
    stmt = pg_insert(ReplayLedgerCheckpoint).values(
        ledger_run_id=ledger.ledger_run_id,
        package_id=ledger.package.package_id,
        state=state,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReplayLedgerCheckpoint.ledger_run_id],
        set_={"package_id": stmt.excluded.package_id, "state": stmt.excluded.state},
    )
    await db.execute(stmt)


async def load_checkpoint(
    db: AsyncSession,
    package: EtfInputPackage,
    config: R01LedgerConfig,
) -> R01Ledger | None:
    """按 config.ledger_run_id 取快照并恢复账本；无快照返回 None。"""
    row = (
        (
            await db.execute(
                select(ReplayLedgerCheckpoint).where(
                    ReplayLedgerCheckpoint.ledger_run_id == config.ledger_run_id
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    # W2E4：跨包恢复防护——DB 行的 package_id 必须与传入包一致，
    # 错误输入包不得恢复同一账本（错误信息含两个 package_id）
    if row.package_id != package.package_id:
        raise CheckpointPackageMismatch(
            f"checkpoint_package_mismatch: DB 行 package_id={row.package_id!r} "
            f"与传入包 package_id={package.package_id!r} 不一致，拒绝恢复"
        )
    return R01Ledger.restore(package, config, row.state)


# ---------------------------------------------------------------------------
# H2.1-L1/L3/L4：虚拟运行（r01vr-）runner 消费接口（实现归 runner owner）
# ---------------------------------------------------------------------------


def virtual_ledger_config_from_row(row) -> R01LedgerConfig:
    """r01_virtual_run_config ORM 行 → 冻结 R01LedgerConfig（runner 入口）。

    run_kind="virtual"（无 attempt 段，单轨迹）；风险参数/撮合假设来自
    配置行 risk_config（缺省走引擎默认：损失线 initial×30%、回撤 30%、
    佣金/滑点默认）；同租户用户权限沿用（配置行不含用户隔离字段，
    页面/查询按既有 tenant/user 认证过滤——见账户关系审计说明）。
    """
    risk = dict(row.risk_config or {})
    return R01LedgerConfig(
        group=row.group,
        strategy_id=row.strategy_id,
        strategy_version=row.strategy_version,
        execution_attempt_id=1,  # virtual 无 attempt 语义，恒 1
        initial_cash=float(row.initial_cash),
        run_kind="virtual",
        loss_line_amount=risk.get("loss_line_amount"),
        drawdown_pct=float(risk.get("drawdown_pct", 0.30)),
        commission_rate=float(risk.get("commission_rate", 0.0003)),
        commission_min=float(risk.get("commission_min", 0.0)),
        slippage_bps=float(risk.get("slippage_bps", 0.0)),
        price_mode=str(risk.get("price_mode", "open")),
        volume_participation=float(risk.get("volume_participation", 1.0)),
        stale_mark_limit=int(risk.get("stale_mark_limit", 5)),
    )


async def load_or_create(
    db: AsyncSession,
    package: EtfInputPackage,
    config: R01LedgerConfig,
) -> tuple[R01Ledger, bool]:
    """按 ledger_run_id 取检查点恢复账本；无检查点则新建（H2.1-L4）。

    返回 (ledger, created)。r01vr- 前缀与研究 r01- 前缀在同一
    replay_ledger_checkpoints 表中天然不冲突；跨日跨月延续=每次运行日
    从最后检查点 restore 续跑（现金/持仓/应收/累计费用/HWM/风险态/
    检查点全部随 checkpoint 延续，不每日清零）。
    """
    ledger = await load_checkpoint(db, package, config)
    if ledger is not None:
        return ledger, False
    return R01Ledger(package, config), True
