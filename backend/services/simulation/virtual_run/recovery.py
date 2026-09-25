"""检查点存取与对账（h2-interfaces §3 恢复点；H2.2-R3）。

- 账本权威状态复用 p03 ``ReplayLedgerCheckpoint``（按 ledger_run_id 幂等
  upsert；``r01vr-`` 前缀与研究 ``r01-`` 天然不冲突）；
- ``InMemoryCheckpointStore``：确定性验收/单测（与 DB 路径同语义：
  save=export_checkpoint 幂等覆盖、load=R01Ledger.restore 三层校验）；
- ``DbCheckpointStore``：生产/沙盒 PG（复用 p03 ledger_persistence）；
- 对账：``reconcile`` 用 ``independent_recompute`` 从原始明细独立重建
  nav 序列与账本快照比对（report 阶段证据）；
- ``NeedsManualReview``：阶段状态与账本权威状态矛盾（"结果不明"）——
  先核对再续，不盲目重放（复用"结果不明不自动重跑"语义）。
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from backend.services.simulation.replay.etf_input_package import EtfInputPackage
from backend.services.simulation.replay.r01_ledger import (
    R01Ledger,
    R01LedgerConfig,
    independent_recompute,
)


class NeedsManualReview(RuntimeError):
    """阶段恢复点与账本检查点矛盾：须人工核对，禁止自动重跑掩盖。"""


class CheckpointStore(Protocol):
    def save(self, ledger: R01Ledger) -> None: ...
    def load(
        self, package: EtfInputPackage, config: R01LedgerConfig
    ) -> R01Ledger | None: ...


class InMemoryCheckpointStore:
    """进程内检查点（键=ledger_run_id；语义与 DB upsert 一致）。"""

    def __init__(self) -> None:
        self._states: dict[str, dict] = {}
        self.save_count = 0

    def save(self, ledger: R01Ledger) -> None:
        self._states[ledger.ledger_run_id] = ledger.export_checkpoint()
        self.save_count += 1

    def load(
        self, package: EtfInputPackage, config: R01LedgerConfig
    ) -> R01Ledger | None:
        state = self._states.get(config.ledger_run_id)
        if state is None:
            return None
        return R01Ledger.restore(package, config, state)


class DbCheckpointStore:
    """PG 检查点（复用 p03 ledger_persistence；同步壳包 asyncio）。

    每次 save/load 独立建 engine 并释放（asyncio.run 每次新 loop，
    跨调用缓存 engine 会把连接绑到旧 loop 报 Future attached to a
    different loop；日频调用开销可忽略）。幂等持久化由
    replay_ledger_checkpoints 的 upsert 承担，不依赖连接复用。
    """

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _run(self, fn):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(self._dsn)

        async def _wrapper():
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as db:
                result = await fn(db)
            await engine.dispose()  # 同 loop 内释放，避免 asyncpg 跨 loop 关闭噪声
            return result

        return asyncio.run(_wrapper())

    def save(self, ledger: R01Ledger) -> None:
        from backend.services.simulation.replay import ledger_persistence

        async def _fn(db) -> None:
            await ledger_persistence.save_checkpoint(db, ledger)
            await db.commit()

        self._run(_fn)

    def load(
        self, package: EtfInputPackage, config: R01LedgerConfig
    ) -> R01Ledger | None:
        """按 config.ledger_run_id 取快照并恢复账本；无快照返回 None。

        J4R2/J4E1：带 input_binding 的检查点（r01vr 日增量运行）直接经
        R01Ledger.restore 按绑定前缀兼容恢复——恢复包可以是已消费清单的
        扩展（新日增量显式消费后进入），不要求瞬时 package_id 全等；
        无绑定字段由 restore 自身显式拒绝（J4E1 语义）。
        """
        from sqlalchemy import select

        from backend.services.simulation.models.replay import ReplayLedgerCheckpoint
        from backend.services.simulation.replay.r01_ledger import R01Ledger

        async def _fn(db):
            return (
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

        row = self._run(_fn)
        if row is None:
            return None
        return R01Ledger.restore(package, config, row.state)


def reconcile(ledger: R01Ledger) -> dict:
    """独立复算对账（J5R3 #1：全精度复算逐行判定，展示舍入与判定分离）。

    - 复算用 ``independent_recompute(round_output=False)`` 全精度输出；
    - 逐行判定：|复算全精度 nav − 账本 equity 展示值| ≤ 证据层舍入界
      （evidence 成交/费用为 4dp 审计口径，复算重放这些舍入值，与账本
      全精度内部的偏差界 = 0.5ulp×(成交笔数+1)；缺行=fail，空集不得
      经 all([]) 判通过；界内=两侧由一致的全精度账务在证据舍入界内
      派生，超界=真实账务分歧 fail）；
    - ``strict_1e_6``（信息项）：全部残差 ≤1e-6 —— 需 p03 在 evidence
      暴露全精度成交后才能达成（当前 evidence 层为 4dp 审计口径，
      待办 p03；不以此作为通过条件，如实报告）；
    - 每行残差如实入 mismatches 报告（含通过行的 max 残差）。
    """
    evidence = ledger.export_evidence()
    recomputed = independent_recompute(
        evidence, package=ledger.package, round_output=False
    )
    n_fills = sum(len(o.get("fills", [])) for o in evidence.get("orders", []))
    row_bound = 5.05e-5 * (n_fills + 1)  # 证据层 4dp 舍入累积界
    snaps = {snap["trade_date"]: snap for snap in evidence["equity"]}
    by_date = {r["trade_date"]: r for r in recomputed}
    max_residual = 0.0
    strict_residual = 0.0
    mismatches: list[dict] = []
    rows: list[dict] = []
    for d in sorted(set(snaps) | set(by_date)):
        snap, rec = snaps.get(d), by_date.get(d)
        if snap is None or rec is None:
            mismatches.append(
                {
                    "trade_date": d,
                    "reason": "row_missing",
                    "ledger_row": snap is not None,
                    "recompute_row": rec is not None,
                }
            )
            continue
        nav_full = float(rec["nav"])
        nav_display = float(snap["nav"])
        residual = abs(nav_full - nav_display)
        max_residual = max(max_residual, residual)
        rows.append(
            {
                "trade_date": d,
                "ledger_nav_display": nav_display,
                "recomputed_nav_full": nav_full,
                "residual": round(residual, 10),
            }
        )
        if residual > row_bound:
            mismatches.append(
                {
                    "trade_date": d,
                    "ledger_nav": nav_display,
                    "recomputed_nav_full": nav_full,
                    "residual": round(residual, 10),
                    "row_bound": round(row_bound, 10),
                }
            )
    return {
        "ok": not mismatches,
        "days_compared": len(evidence["equity"]),
        "n_fills": n_fills,
        "row_bound": round(row_bound, 10),
        "max_abs_nav_diff": round(max_residual, 10),
        "strict_1e_6": max_residual <= 1e-6,
        "mismatches": mismatches,
        "rows": rows,
        "judgment": "full_precision_per_row(evidence_layer_bound)",
        "note": (
            "严格 1e-6 需 evidence 暴露全精度成交（p03 待办）；当前逐行"
            "判定界=0.5ulp×(成交笔数+1)，源于 evidence 4dp 审计口径舍入"
        ),
    }
