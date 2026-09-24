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
