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
    """独立复算对账：independent_recompute vs 账本 equity 快照。"""
    evidence = ledger.export_evidence()
    recomputed = independent_recompute(evidence, package=ledger.package)
    max_diff = 0.0
    by_date = {r["trade_date"]: r for r in recomputed}
    mismatches: list[dict] = []
    for snap in evidence["equity"]:
        d = snap["trade_date"]
        rec = by_date.get(d)
        if rec is None:
            mismatches.append({"trade_date": d, "reason": "recompute_missing"})
            continue
        diff = abs(float(rec["nav"]) - float(snap["nav"]))
        max_diff = max(max_diff, diff)
        if diff > 1e-6:
            mismatches.append(
                {
                    "trade_date": d,
                    "ledger_nav": snap["nav"],
                    "recomputed_nav": rec["nav"],
                }
            )
    return {
        "ok": not mismatches,
        "days_compared": len(evidence["equity"]),
        "max_abs_nav_diff": round(max_diff, 10),
        "mismatches": mismatches,
    }
