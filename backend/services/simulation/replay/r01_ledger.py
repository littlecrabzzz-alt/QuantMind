"""R01 独立研究账本引擎（ledger-contract v2 的 P0.3 实现）。

在 replay 子系统语义之上实现合同要求的最小执行账本：

- 三层标识：strategy_id+strategy_version / execution_attempt_id /
  ledger_run_id（= replay 会话标识），A/B1/B2/B3/D/N 运行组别参数化；
- 订单幂等键 client_order_id = f"{ledger_run_id}:{trade_date}:{symbol}:{side}"，
  同键重试返回原订单与原成交，不产生第二笔；
- 订单/成交状态机：new→validated→submitted→(partially_)filled /
  rejected / expired_unfilled（部分成交剩余量当日收盘转
  expired_unfilled，不隔日挂单）；
- 现金流政策：ETF 印花税=过户费=0（TG-006 资产类别规则）、佣金可配
  最低收费、现金分红 EOD 入账、份额调整开盘前（不动现金、成本基准
  同比例调整）、残余现金计息 0% 计入 nav；
- 公司行动只消费输入包 typed events，幂等键
  (ledger_run_id, symbol, event_date, event_type)；
- 风险状态机（risk_state.RiskStateMachine）：本金损失线 + 净值高点
  回撤线，独立触发、逐线确认，禁止追加资金掩蔽触发；
- 估值口径：信号=复权序列（包 adjusted_close）、执行=开盘价（未复权，
  含可配滑点与价格档）、净值=收盘未复权价；
- 确定性：同一冻结定义+同一输入包两次运行（不同 attempt）账务结果
  完全一致（时间戳不参与账务）。

纯内存实现（PG 持久化层由 models/replay.py 的 replay_* 表承接，见
db_init.sql + data/upgrade_v1.0.r01replay1.sql）；工程回放为 fixture
样例时显著标注，不进策略收益排行。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from backend.services.simulation.replay.etf_input_package import (
    EtfInputPackage,
    TypedEvent,
)
from backend.services.simulation.replay.risk_state import (
    RiskConfig,
    RiskStateMachine,
    make_risk_confirm_key,
)
from backend.services.simulation.services.ashare_matcher import (
    MatchConfig,
    MatchResult,
    match_order,
)
from backend.services.simulation.services.market_rules import (
    etf_settlement_days_for_symbol,
)
from backend.shared.utc_datetime import utc_now

logger = logging.getLogger(__name__)

GROUPS = ("A", "B1", "B2", "B3", "D", "N", "P0")


class ViewBuildError(ValueError):
    """export_view 构建失败（H1.1）：原生证据缺必需字段或形状不合法。

    格式不明/字段缺失一律显式报错（报出 day/字段/原因），禁止静默填零。
    """


class SameKeyOrderConflict(ValueError):
    """同 client_order_id 但内容不同（W2E3/F1 修复 AC-04）。

    幂等键命中已有订单时，qty_target 必须一致；同键异内容显式拒绝，
    防止静默改写目标量。
    """


class CheckpointConfigMismatch(ValueError):
    """checkpoint 冻结参数与传入 config 不匹配（F1 修复 AC-03）。

    run_id 只绑定 (group, strategy_id, version, attempt)，不含本金/费率/
    风险参数等冻结定义；同 run 改参数恢复会形成混合口径账本。恢复入口
    必须比对完整 config（含合同版本），不匹配显式拒绝，变更参数须新建
    strategy_version/attempt。
    """


class CheckpointPackageMismatch(ValueError):
    """checkpoint 与传入输入包不匹配（W2E4：跨包恢复防护）。

    checkpoint 状态与生成它的输入包绑定（行情/事件/日历一体）；用
    另一个包恢复同一账本会静默产生混合口径账务，必须显式拒绝。
    """


class LedgerOrderingError(ValueError):
    """会话顺序/信号对齐违规（W2E3 修复#2）。

    reason ∈ out_of_order / skipped_session / not_trade_date /
    same_day_signal / signal_not_prev_session。账本会话必须按包交易日
    历逐日推进；调仓日的信号必须是执行日的上一个包交易日。
    """

    def __init__(self, reason: str, message: str):
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


# F3 修复#2：版本身份对齐冻结合同现状（ledger-contract v3 / 输入包
# schema v3）。checkpoint 恢复按此绑定：旧 v2 checkpoint 显式拒绝
# （CheckpointConfigMismatch，合同版本不一致），不静默混用；如需迁移
# 须另发 checkpoint schema 版本与迁移路径记录。
# M4E1（项4）：ledger 合同版本绑定 v3.1（附录 rev2 零股收窄+精度语义）。
CONTRACT_VERSIONS = {
    "ledger_contract": "v3.1",
    "etf_input_package_schema": "v3",
}

# 订单/成交状态机（ledger-contract §4）
ORDER_STATUS_PARTIALLY_FILLED = "partially_filled"
ORDER_STATUS_EXPIRED_UNFILLED = "expired_unfilled"
ORDER_STATUS_FILLED = "filled"
ORDER_STATUS_REJECTED = "rejected"
# 终态（F1 修复 AC-04）：执行/入账层对终态订单幂等——同键重试返回原
# 终态，不改现金/持仓/fills/费用/状态
_TERMINAL_STATUSES = frozenset(
    {
        ORDER_STATUS_FILLED,
        ORDER_STATUS_EXPIRED_UNFILLED,
        ORDER_STATUS_REJECTED,
        "cancelled",
    }
)

_REJECT_REASONS = (
    "no_quote",
    "suspended",
    "limit_hit",
    "insufficient_cash",
    "risk_paused",
    "lot_inexpressible",
    "stale_price",
    "corporate_action_gap",
    "no_position",  # W2E3 修复#5：无持仓/无可卖量卖出
    "sublot_partial_sell_not_allowed",  # M2E1：§3.3.8 零股余额须一次性申报
)


def make_ledger_run_id(group: str, strategy_id: str, version: int, attempt: int) -> str:
    """ledger_run_id = r01-<group>-<strategy_id>-v<version>-a<attempt>。"""
    return f"r01-{group}-{strategy_id}-v{version}-a{attempt:04d}"


def make_virtual_run_id(group: str, strategy_id: str, version: int) -> str:
    """虚拟运行 ledger_run_id = r01vr-<group>-<strategy_id>-v<version>（H2.1-L1）。

    无 attempt 段：持续运行是单轨迹（不重复尝试）；策略定义/参数变更 ⇒
    新 version（新 r01vr run），旧轨迹只读保留、净值不拼接。
    """
    return f"r01vr-{group}-{strategy_id}-v{version}"


def make_revision_run_id(base_virtual_run_id: str, revision_date: date) -> str:
    """修订轨迹 run id：`r01vr-…:rev<YYYYMMDD>`（H2.1-L5）。

    补算/修订与原始向前决策分离——独立 run/检查点/证据，不回填原始轨迹。
    """
    return f"{base_virtual_run_id}:rev{revision_date.strftime('%Y%m%d')}"


def parse_attempt(attempt_id: str) -> int:
    """ "a0001" → 1。"""
    return int(str(attempt_id).lstrip("a"))


def make_client_order_id(
    ledger_run_id: str, trade_date: date, symbol: str, side: str
) -> str:
    return f"{ledger_run_id}:{trade_date.isoformat()}:{symbol}:{side.lower()}"


@dataclass
class LedgerFill:
    """一笔成交（未复权价口径）。"""

    trade_date: str
    symbol: str
    side: str
    price: float
    quantity: int
    commission: float
    stamp_duty: float
    transfer_fee: float
    total_fee: float
    signal_date: str | None = None
    slippage_bps: float = 0.0
    price_source: str = "package_open"

    def to_dict(self) -> dict[str, Any]:
        """M4E1（项3）：恢复层（checkpoint/审计原件）全精度——commission/
        fees 等不再 4dp 舍入（原 total_fee_exact 审计字段保留兼容）；
        展示格式化仅在 export_view。"""
        return {
            "trade_date": self.trade_date,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "quantity": self.quantity,
            "commission": self.commission,
            "stamp_duty": self.stamp_duty,
            "transfer_fee": self.transfer_fee,
            "total_fee": self.total_fee,
            "total_fee_exact": self.total_fee,
            "signal_date": self.signal_date,
            "slippage_bps": self.slippage_bps,
            "price_source": self.price_source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LedgerFill:
        return cls(
            trade_date=d["trade_date"],
            symbol=d["symbol"],
            side=d["side"],
            price=float(d["price"]),
            quantity=int(d["quantity"]),
            commission=float(d["commission"]),
            stamp_duty=float(d["stamp_duty"]),
            transfer_fee=float(d["transfer_fee"]),
            # J6R4：checkpoint 恢复优先全精度费用（to_dict 的 4dp 展示值
            # 仅旧快照回退）——避免往返丢失费用精度导致复算/账本现金
            # 出现 ~1ulp×笔数 级伪残差
            total_fee=float(d.get("total_fee_exact", d["total_fee"])),
            signal_date=d.get("signal_date"),
            slippage_bps=float(d.get("slippage_bps", 0.0)),
            price_source=d.get("price_source", "package_open"),
        )


@dataclass
class LedgerOrder:
    """研究账本订单（含状态机字段）。"""

    client_order_id: str
    ledger_run_id: str
    trade_date: str
    signal_date: str | None
    symbol: str
    side: str  # buy | sell
    origin: str  # signal | manual | risk_exit
    qty_target: int
    status: (
        str  # new/validated/submitted/partially_filled/filled/rejected/expired_unfilled
    )
    qty_filled: int = 0
    qty_remaining: int = 0  # = target − filled，恒非负
    avg_fill_price: float = 0.0
    fees: float = 0.0
    realized_pnl: float = 0.0  # 卖出累计（扣费后）；买入为 0
    fills: list[LedgerFill] = field(default_factory=list)
    reject_reason: str | None = None
    ideal_weight: float | None = None
    realized_weight: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "ledger_run_id": self.ledger_run_id,
            "trade_date": self.trade_date,
            "signal_date": self.signal_date,
            "symbol": self.symbol,
            "side": self.side,
            "origin": self.origin,
            "qty_target": self.qty_target,
            "qty_filled": self.qty_filled,
            "qty_remaining": self.qty_remaining,
            "avg_fill_price": self.avg_fill_price if self.avg_fill_price else None,
            "status": self.status,
            "reject_reason": self.reject_reason,
            "fees": self.fees,
            "realized_pnl": self.realized_pnl,
            "ideal_weight": self.ideal_weight,
            "realized_weight": (
                round(self.realized_weight, 6)
                if self.realized_weight is not None
                else None
            ),
            "fills": [f.to_dict() for f in self.fills],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LedgerOrder:
        order = cls(
            client_order_id=d["client_order_id"],
            ledger_run_id=d["ledger_run_id"],
            trade_date=d["trade_date"],
            signal_date=d.get("signal_date"),
            symbol=d["symbol"],
            side=d["side"],
            origin=d.get("origin", "signal"),
            qty_target=int(d["qty_target"]),
            status=d["status"],
            qty_filled=int(d.get("qty_filled", 0)),
            qty_remaining=int(d.get("qty_remaining", 0)),
            avg_fill_price=float(d.get("avg_fill_price") or 0.0),
            fees=float(d.get("fees", 0.0)),
            realized_pnl=float(d.get("realized_pnl", 0.0)),
            reject_reason=d.get("reject_reason"),
            ideal_weight=d.get("ideal_weight"),
            realized_weight=d.get("realized_weight"),
        )
        order.fills = [LedgerFill.from_dict(f) for f in d.get("fills", [])]
        return order


@dataclass
class LedgerPosition:
    symbol: str
    qty: float = 0.0
    avg_cost: float = 0.0
    available_qty: float = 0.0
    # T+1 逐日解锁（W2E3 修复#2）：pending_t1_qty = 最近一次买入且尚未
    # 跨过 T+1 边界的数量；available_qty 恒 = qty − pending_t1_qty（T+1
    # 品种）/ qty（T+0 品种）。跨过下一个交易日边界时在 rollover 解锁。
    pending_t1_qty: float = 0.0
    pending_t1_date: str | None = None
    # F1 修复 AC-02：缺行情估值冻结政策——沿用最近有效市价（carry-forward）
    # 并记录陈旧程度，禁止静默改用成本价。有行情日 last_mark=收盘并清零
    # stale_days；缺行情日沿用并递增。
    last_mark: float = 0.0
    last_mark_date: str | None = None
    stale_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        """J2E2 精度政策：内部/检查点/审计原件一律全精度（份额折算等
        乘法不留 4dp 舍入），仅展示层（export_view）格式化。"""
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_cost": self.avg_cost,
            "available_qty": self.available_qty,
            "pending_t1_qty": self.pending_t1_qty,
            "pending_t1_date": self.pending_t1_date,
            "last_mark": self.last_mark,
            "last_mark_date": self.last_mark_date,
            "stale_days": self.stale_days,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LedgerPosition:
        return cls(
            symbol=d["symbol"],
            qty=float(d["qty"]),
            avg_cost=float(d["avg_cost"]),
            available_qty=float(d["available_qty"]),
            pending_t1_qty=float(d.get("pending_t1_qty", 0.0)),
            pending_t1_date=d.get("pending_t1_date"),
            last_mark=float(d.get("last_mark", 0.0)),
            last_mark_date=d.get("last_mark_date"),
            stale_days=int(d.get("stale_days", 0)),
        )


@dataclass
class R01LedgerConfig:
    """一次账本运行的冻结定义（创建后锁定）。

    run_kind（H2.1-L1）：
    - "research"：研究账本，r01-…-a<attempt>（复算/重试分层）；
    - "virtual"：虚拟运行账本，r01vr-<group>-<strategy_id>-v<version>
      （无 attempt 段，单轨迹；同一 R01Ledger 引擎与已验收执行/账务规则）。
    修订（L5）：revision_of/revision_date 非空时，run id 在虚拟 id 后追加
    ":rev<date>"——修订轨迹独立落检查点/证据，原始轨迹不回填。
    """

    group: str
    strategy_id: str
    strategy_version: int
    execution_attempt_id: int  # 单调递增 a0001 起；不靠新窗口重置
    initial_cash: float
    run_kind: str = "research"  # research | virtual
    # L5 修订轨迹（仅 virtual 基轨迹可修订；research 复算本就走新 attempt）
    revision_of: str | None = None
    revision_date: date | None = None
    # 风险线（默认 initial_cash×30% 与回撤 30%）
    loss_line_amount: float | None = None
    drawdown_pct: float = 0.30
    # 撮合假设（DG-011 敏感性可配）
    commission_rate: float = 0.0003
    commission_min: float = 0.0
    slippage_bps: float = 5.0
    price_mode: str = "open"
    # 当日市场成交量参与率（W2E3 修复#3）：成交上限 = bar.volume × 此值
    volume_participation: float = 1.0
    # F1 修复 AC-02：缺行情 carry-forward 可靠性阈值——连续缺行情超过该
    # 天数时当日快照标 valuation_reliable=False（不可信，不静默当有效净值）
    stale_mark_limit: int = 5
    # M6E1（项1）：输入日期上界冻结进 config（防未授权放大：续段更大
    # 上界=显式新 config/checkpoint；None=整包现状）
    read_through_bound: date | None = None
    # M2E1（R01SELF 狭义零股申报缺口）：上交所交易规则 2026 修订 §3.3.8
    # "卖出证券时，余额不足100股（份）的部分，应当一次性申报卖出"——
    # 生效日 2026-07-06（上证发〔2026〕41 号）；仅 trade_date ≥ 该日启用
    # 申报校验，此前维持现行为（早期规则全文未取得，不声称全历史违规）
    sublot_rule_effective: date = date(2026, 7, 6)

    def __post_init__(self) -> None:
        if self.group not in GROUPS:
            raise ValueError(f"非法运行组别 {self.group}（允许 {GROUPS}）")
        if self.group == "P0" and not self.strategy_id.startswith("fixture-"):
            raise ValueError(
                "P0 工程样例 strategy_id 必须以 fixture- 前缀（不进收益排行）"
            )
        if self.execution_attempt_id < 1:
            raise ValueError("execution_attempt_id 从 1 起（a0001）")
        if self.run_kind not in ("research", "virtual"):
            raise ValueError(f"非法 run_kind {self.run_kind}（research|virtual）")
        if self.run_kind == "virtual" and self.group == "P0":
            raise ValueError(
                "虚拟运行不使用 P0 工程样例组（须为正式研究组 A/B1/B2/B3/D/N）"
            )
        if (self.revision_of is None) != (self.revision_date is None):
            raise ValueError("revision_of 与 revision_date 必须成对提供")
        if self.revision_of is not None and self.run_kind != "virtual":
            raise ValueError(
                "修订轨迹仅适用于 virtual 运行（research 复算走新 attempt）"
            )
        if self.revision_of is not None and self.revision_of != make_virtual_run_id(
            self.group, self.strategy_id, self.strategy_version
        ):
            raise ValueError("revision_of 必须指向同 group/strategy/version 的基轨迹")

    @property
    def ledger_run_id(self) -> str:
        if self.run_kind == "virtual":
            base = make_virtual_run_id(
                self.group, self.strategy_id, self.strategy_version
            )
            if self.revision_date is not None:
                return make_revision_run_id(base, self.revision_date)
            return base
        return make_ledger_run_id(
            self.group,
            self.strategy_id,
            self.strategy_version,
            self.execution_attempt_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "run_kind": self.run_kind,
            "revision_of": self.revision_of,
            "revision_date": (
                self.revision_date.isoformat() if self.revision_date else None
            ),
            "execution_attempt_id": f"a{self.execution_attempt_id:04d}",
            "ledger_run_id": self.ledger_run_id,
            "initial_cash": self.initial_cash,
            "loss_line_amount": self.loss_line_amount,
            "drawdown_pct": self.drawdown_pct,
            "commission_rate": self.commission_rate,
            "commission_min": self.commission_min,
            "slippage_bps": self.slippage_bps,
            "price_mode": self.price_mode,
            "volume_participation": self.volume_participation,
            "stale_mark_limit": self.stale_mark_limit,
            "sublot_rule_effective": self.sublot_rule_effective.isoformat(),
            "read_through_bound": (
                self.read_through_bound.isoformat() if self.read_through_bound else None
            ),
        }


@dataclass
class DaySummary:
    trade_date: str
    # M4E2：§3.3.8 申报校验审计痕迹（含放行：skipped_unproven_scope 等）
    sublot_checks: list[dict[str, Any]] = field(default_factory=list)
    corporate_actions_applied: list[dict[str, Any]] = field(default_factory=list)
    dividends_credited: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    risk_events: list[dict[str, Any]] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "sublot_checks": list(self.sublot_checks),
            "corporate_actions_applied": self.corporate_actions_applied,
            "dividends_credited": self.dividends_credited,
            "orders": self.orders,
            "risk_events": self.risk_events,
            "snapshot": self.snapshot,
        }


class R01Ledger:
    """一个 ledger_run_id 的完整账本（纯内存、确定性）。"""

    def __init__(
        self,
        package: EtfInputPackage,
        config: R01LedgerConfig,
        *,
        created_at: datetime | None = None,
        source_node: str = "mac",
        input_binding: dict[str, Any] | None = None,
    ):
        self.package = package
        self.config = config
        self.ledger_run_id = config.ledger_run_id
        self.created_at = created_at or utc_now()
        self.source_node = source_node
        self.contract_versions = dict(CONTRACT_VERSIONS)
        # J4E1：输入绑定（基线 + 已消费日增量有序清单）。缺省从包自身
        # 捕获；恢复/续跑走 rebuild_bound_package 重建的包应显式传入
        # 同源绑定（消费新增量后须用 extend_binding 更新再入检查点）。
        from backend.services.simulation.replay.daily_binding import capture_binding

        self.input_binding = input_binding or capture_binding(package)

        self.cash = float(config.initial_cash)
        self.initial_cash_locked = True
        self.positions: dict[str, LedgerPosition] = {}
        self.orders: dict[str, LedgerOrder] = {}
        self.equity: list[dict[str, Any]] = []
        self.risk = RiskStateMachine(
            self.ledger_run_id,
            RiskConfig(
                initial_cash=config.initial_cash,
                loss_line_amount=config.loss_line_amount,
                drawdown_pct=config.drawdown_pct,
            ),
        )
        # 公司行动幂等键 (run, symbol, event_date, event_type)
        self.applied_action_keys: set[tuple[str, str, str, str]] = set()
        self.corporate_action_log: list[dict[str, Any]] = []
        # F2（ledger-contract v3 §5/§6/§8）：分红三段式
        # entitlements: 幂等键 (run, symbol, event_id, record_date) → 阶段记录
        #   stage: entitled（record EOD 定格）→ receivable（ex 开盘前入应收）
        #          → paid（pay 开盘前转可用现金）
        self.dividend_entitlements: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self.dividend_receivable: float = 0.0  # 应收红利（计入 nav、不可交易）
        self.blocked_dividend_log: list[dict[str, Any]] = []
        # M4E2：零股申报校验审计（跨日累计；manual_sell 等摘要外入口）
        self.sublot_check_log: list[dict[str, Any]] = []
        # M4E2：checkpoint 精度来源标记（新建=full；legacy 恢复=legacy）
        self.checkpoint_precision_origin: str = "full_precision"
        self.manual_actions: list[dict[str, Any]] = []
        self.deposit_rejections: list[dict[str, Any]] = []
        self.risk_blocked_orders: list[dict[str, Any]] = []
        # 显式缺口：暂停该标的后续买入直到解决（禁止按零处理）
        self.buy_suspended_symbols: set[str] = set(package.unresolved_gap_symbols())
        self._executed_dates: set[str] = set()
        self._last_trade_date: date | None = None

        self._cfg = MatchConfig(
            price_mode=config.price_mode,
            slippage_bps=config.slippage_bps,
            commission_rate=config.commission_rate,
            commission_min=config.commission_min,
            # 费率字段对 ETF 是结构豁免（印花税/过户费恒 0），
            # 佣金率/最低收费取会话假设
            asset_type="etf",
            allow_partial=True,
            volume_participation=config.volume_participation,
        )

    # ------------------------------------------------------------------
    # 元数据
    # ------------------------------------------------------------------

    def session_metadata(self) -> dict[str, Any]:
        return {
            "strategy_id": self.config.strategy_id,
            "strategy_version": self.config.strategy_version,
            "execution_attempt_id": f"a{self.config.execution_attempt_id:04d}",
            "ledger_run_id": self.ledger_run_id,
            "group": self.config.group,
            "input_package_id": self.package.package_id,
            "input_package_uri": self.package.package_uri,
            "manifest_sha256": self.package.manifest_sha256,
            "contract_versions": self.contract_versions,
            "initial_cash": self.config.initial_cash,
            "risk_config": self.risk.config.to_dict(),
            "match_assumptions": {
                "commission_rate": self.config.commission_rate,
                "commission_min": self.config.commission_min,
                "slippage_bps": self.config.slippage_bps,
                "price_mode": self.config.price_mode,
                "asset_type": "etf",
            },
            "created_at": self.created_at.isoformat(),
            "source_node": self.source_node,
            "is_fixture": self.package.is_fixture,
        }

    # ------------------------------------------------------------------
    # 单日推演
    # ------------------------------------------------------------------

    def _validate_day_ordering(
        self, trade_date: date, signal_date: date | None, has_weights: bool
    ) -> date | None:
        """W2E3 修复#2：会话顺序与 T+1 信号对齐强制校验。

        - 执行日必须是包交易日，且严格递增、不跳日（下一包交易日）；
        - 调仓日的 signal_date 必须是执行日的上一个包交易日（缺省自动
          取该日；同日信号/错位信号显式拒绝）。
        返回生效的 signal_date（可能被自动补全）。
        """
        if not self.package.is_trade_date(trade_date):
            raise LedgerOrderingError(
                "not_trade_date", f"{trade_date} 不是输入包交易日"
            )
        if self._last_trade_date is not None:
            if trade_date <= self._last_trade_date:
                raise LedgerOrderingError(
                    "out_of_order",
                    f"{trade_date} 不早于上一执行日 {self._last_trade_date}",
                )
            expected = self.package.next_trade_date(self._last_trade_date)
            if expected != trade_date:
                raise LedgerOrderingError(
                    "skipped_session",
                    f"期望下一交易日 {expected}，得到 {trade_date}（禁止跳日执行）",
                )
        prev = self.package.prev_trade_date(trade_date)
        if signal_date is not None and signal_date >= trade_date:
            raise LedgerOrderingError(
                "same_day_signal", f"signal_date {signal_date} 必须严格早于执行日"
            )
        if has_weights:
            if signal_date is None:
                signal_date = prev  # 自动对齐上一包交易日
            elif prev is None or signal_date != prev:
                raise LedgerOrderingError(
                    "signal_not_prev_session",
                    f"signal_date {signal_date} 必须是执行日的上一包交易日 {prev}",
                )
        return signal_date

    def run_day(
        self,
        trade_date: date,
        target_weights: dict[str, float] | None = None,
        *,
        signal_date: date | None = None,
    ) -> DaySummary:
        """执行一个交易日（顺序是语义的一部分）：

        1. T+1 解锁（settlement 回转按品种）
        2. 份额调整 typed 事件（开盘前、撮合前，先于分红段）
        3. 分红段（v3 三段式）：ex 开盘前入应收 → pay 开盘前转现金
        4. 目标权重 → 订单（先卖后买）
        5. EOD：record 收盘定格权益 → 收盘估值（nav=现金+应收+持仓）→ 风险 → 快照
        """
        key = trade_date.isoformat()
        if key in self._executed_dates:
            raise ValueError(f"{trade_date} 已执行（重放须新 attempt，TG-004/§3）")

        # W2E3 修复#2：会话顺序与信号对齐由账本强制执行。
        signal_date = self._validate_day_ordering(
            trade_date, signal_date, target_weights is not None
        )

        summary = DaySummary(trade_date=key)
        bars = self.package.load_date(trade_date)

        # 1. 回转解锁：T+1 品种仅解锁已跨过 T+1 边界的具体买入批次
        self._rollover_settlement(trade_date)

        # 2. 份额调整（开盘前；不动现金；先于分红段）
        for ev in self.package.events_on(trade_date):
            if ev.event_type == "share_adjustment":
                applied = self._apply_share_adjustment(ev)
                if applied is not None:
                    summary.corporate_actions_applied.append(applied)
        # 3. 分红三段式（F2 / v3）：ex 开盘前入应收（不可交易），pay 开盘前
        #    应收转可用现金；同日先应收后到账；blocked 事件显式阻塞
        for staged in self._stage_dividend_receivable(trade_date):
            summary.dividends_credited.append(staged)
        for staged in self._stage_dividend_pay(trade_date):
            summary.dividends_credited.append(staged)
        for blocked in self._register_blocked_dividends():
            summary.dividends_credited.append(blocked)

        # 3. 目标权重 → 订单（W2E3 修复#1：目标金额基于信号日收盘 NAV 与
        #    信号日收盘价；执行日只用开盘价成交，无前视）
        if target_weights is not None:
            nav_ref, closes_ref = self._signal_reference(trade_date, signal_date)
            self._rebalance(
                trade_date,
                bars,
                target_weights,
                signal_date,
                nav_ref,
                closes_ref,
                summary,
            )

        # 4. EOD
        self._eod(trade_date, bars, summary)

        self._executed_dates.add(key)
        self._last_trade_date = trade_date
        return summary

    # ------------------------------------------------------------------
    # 订单提交（幂等）
    # ------------------------------------------------------------------

    def submit_order(
        self,
        trade_date: date,
        symbol: str,
        side: str,
        qty: int,
        *,
        origin: str = "signal",
        signal_date: date | None = None,
        ideal_weight: float | None = None,
    ) -> LedgerOrder:
        """提交一笔订单。同 client_order_id 重试返回原订单（不重复成交）。"""
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"side 非法: {side}")
        coid = make_client_order_id(self.ledger_run_id, trade_date, symbol, side)
        existing = self.orders.get(coid)
        if existing is not None:
            # 同键重试：返回原订单与原成交；同键异内容（目标量不同）拒绝
            if existing.qty_target != int(qty):
                raise SameKeyOrderConflict(
                    f"client_order_id={coid} 已存在 qty_target={existing.qty_target}，"
                    f"与重试 qty={qty} 不一致（同键异内容禁止）"
                )
            return existing

        order = LedgerOrder(
            client_order_id=coid,
            ledger_run_id=self.ledger_run_id,
            trade_date=trade_date.isoformat(),
            signal_date=signal_date.isoformat() if signal_date else None,
            symbol=symbol,
            side=side,
            origin=origin,
            qty_target=int(qty),
            qty_remaining=int(qty),
            status="new",
            ideal_weight=ideal_weight,
        )
        self.orders[coid] = order
        return order

    def _validate_and_execute(
        self, order: LedgerOrder, trade_date: date, bars: dict, summary: DaySummary
    ) -> None:
        """validated → submitted → fill/reject 状态机（单日内完成）。

        F1 修复 AC-04：终态订单幂等——重试不再执行任何校验/撮合/入账，
        原样返回（现金/持仓/fills/费用/状态均不变），卖光后的重试也不
        会把原成交改写为拒单。
        """
        if order.status in _TERMINAL_STATUSES:
            return
        order.status = "validated"
        bar = bars.get(order.symbol)

        def _reject(reason: str) -> None:
            order.status = ORDER_STATUS_REJECTED
            order.reject_reason = reason
            order.qty_remaining = order.qty_target

        if bar is None:
            return _reject("no_quote")
        if bar.suspended:
            return _reject("suspended")
        # W2E3 修复#5：裸卖空防护——卖出前必须有持仓且可卖量>0，
        # 拒单 reason=no_position，现金不得增加。
        if order.side == "sell":
            position = self.positions.get(order.symbol)
            if position is None or position.qty <= 1e-9 or position.available_qty <= 0:
                return _reject("no_position")
        # 风险闸门：仅买方向；既定退出/卖出继续有效
        if order.side == "buy":
            if not self.risk.buys_allowed:
                active = self.risk.latest_active_risk_event_id()
                blocked = {
                    "client_order_id": order.client_order_id,
                    "symbol": order.symbol,
                    "trade_date": order.trade_date,
                    "qty": order.qty_target,
                    "reject_reason": "risk_paused",
                }
                self.risk_blocked_orders.append(blocked)
                if active:
                    self.risk.record_blocked_order(active, blocked)
                return _reject("risk_paused")
            if order.symbol in self.buy_suspended_symbols:
                return _reject("corporate_action_gap")

        order.status = "submitted"
        position = self.positions.get(order.symbol)
        available = (
            position.available_qty
            if (position is not None and order.side == "sell")
            else None
        )
        mr: MatchResult = match_order(
            side=order.side,
            quantity=order.qty_target,
            bar=bar,
            cfg=self._cfg,
            available_volume=available,
            cash_available=self.cash if order.side == "buy" else None,
        )
        if not mr.success:
            reason = mr.reason.split(":", 1)[0].lower()
            return _reject(_normalize_reject_reason(reason))

        self._settle_fill(order, mr, bar, summary)

    def _settle_fill(
        self, order: LedgerOrder, mr: MatchResult, bar, summary: DaySummary
    ) -> None:
        """成交入账（现金/持仓/成本）并推进状态机。"""
        gross = mr.fill_quantity * mr.fill_price
        fill = LedgerFill(
            trade_date=order.trade_date,
            symbol=order.symbol,
            side=order.side,
            price=mr.fill_price,
            quantity=mr.fill_quantity,
            commission=mr.commission,
            stamp_duty=mr.stamp_duty,
            transfer_fee=mr.transfer_fee,
            total_fee=mr.total_fee,
            signal_date=order.signal_date,
            slippage_bps=self.config.slippage_bps,
        )
        pos = self.positions.setdefault(
            order.symbol, LedgerPosition(symbol=order.symbol)
        )
        if order.side == "buy":
            self.cash -= gross + mr.total_fee
            # 移动加权成本
            new_qty = pos.qty + mr.fill_quantity
            pos.avg_cost = (
                (pos.avg_cost * pos.qty + gross + mr.total_fee) / new_qty
                if new_qty > 0
                else 0.0
            )
            pos.qty = new_qty
            # T+0 品种当日可卖；T+1 品种记 pending 批次，跨过下一交易日
            # 边界时 rollover 解锁（W2E3 修复#2：逐日解锁具体日期）
            if etf_settlement_days_for_symbol(order.symbol) == 0:
                pos.available_qty += mr.fill_quantity
            else:
                if pos.pending_t1_date == order.trade_date:
                    pos.pending_t1_qty += mr.fill_quantity
                else:
                    pos.pending_t1_qty = mr.fill_quantity
                    pos.pending_t1_date = order.trade_date
        else:
            # 卖出在减仓前抓移动加权成本（清仓后持仓会被删掉）
            avg_cost_before = pos.avg_cost
            self.cash += gross - mr.total_fee
            pos.qty -= mr.fill_quantity
            pos.available_qty = max(0.0, pos.available_qty - mr.fill_quantity)
            realized = (
                mr.fill_price - avg_cost_before
            ) * mr.fill_quantity - mr.total_fee
            order.realized_pnl += realized
            if pos.qty <= 1e-9:
                self.positions.pop(order.symbol, None)

        order.fills.append(fill)
        total_qty = sum(f.quantity for f in order.fills)
        order.qty_filled = total_qty
        order.qty_remaining = max(0, order.qty_target - total_qty)
        order.avg_fill_price = (
            sum(f.quantity * f.price for f in order.fills) / total_qty
            if total_qty > 0
            else 0.0
        )
        order.fees += mr.total_fee
        # 部分成交：当日有效；剩余量收盘后转 expired_unfilled（_eod 统一收口）
        order.status = (
            ORDER_STATUS_FILLED
            if order.qty_remaining == 0
            else ORDER_STATUS_PARTIALLY_FILLED
        )
        summary.orders.append(order.to_dict())

    def _sublot_declaration_check(
        self,
        trade_date: date,
        symbol: str,
        declared_qty: int,
        pos: LedgerPosition | None,
        *,
        extra: str = "",
    ) -> tuple[str | None, dict[str, Any] | None]:
        """§3.3.8 零股申报校验（M4E1 收窄到已证关系；M4E2 放行审计）。

        **唯一强制**：总仓≈可卖（|差|<1e-9，双方强证场景：总仓=可卖<100）
        且 0<申报<可卖（部分零股申报）→ 拒 sublot_partial_sell_not_allowed。
        total≠available（如 T+1 锁定）**不强制**——分歧场景无官方依据不判，
        现状放行。仅 trade_date ≥ sublot_rule_effective（默认 2026-07-06）。
        不扩大卖量、不整手化合法部分成交。

        返回 (reject_reason | None, audit_note | None)：
        - 拒单：reason + audit（记 total/available/declared）；
        - 放行（≥生效日）：audit 含 sublot_check 状态标记——
          `enforced_reject` 不适用；`skipped_unproven_scope`（total≠available
          或余额≥100 等未证关系，放行留痕）/`full_declaration`（全额放行）；
        - 生效日前/非卖出：。调用方把 audit 落到当日 summary（留痕）。
        """
        if pos is None:
            return None, None
        total = round(pos.qty, 9)
        available = round(pos.available_qty, 9)
        total_eq_available = abs(total - available) < 1e-9
        audit: dict[str, Any] = {
            "symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "total": total,
            "available": available,
            "declared": declared_qty,
        }
        if extra:
            audit["context"] = extra
        if trade_date < self.config.sublot_rule_effective:
            audit["sublot_check"] = "skipped_pre_effective"
            return None, audit
        if not total_eq_available:
            # 分歧场景（如 T+1 锁定）：无官方依据不判，放行留痕
            audit["sublot_check"] = "skipped_unproven_scope"
            return None, audit
        # M5E1（项4b）：小数份余额为模型域（现实券商不存在非整数可卖）——
        # 法律已证仅覆盖整数 total=available<100；可卖非整数不强制，放行
        # + fractional_model_domain 审计痕迹
        if available != int(available):
            audit["sublot_check"] = "fractional_model_domain"
            return None, audit
        if not (0 < available < 100):
            audit["sublot_check"] = "skipped_balance_ge_100"
            return None, audit
        if declared_qty >= available:
            audit["sublot_check"] = "full_declaration"
            return None, audit
        if declared_qty <= 0:
            return None, None
        audit["sublot_check"] = "enforced_reject"
        detail = f"total={total},available={available},declared={declared_qty}"
        if extra:
            detail += f",{extra}"
        return f"sublot_partial_sell_not_allowed:{detail}", audit

    def _signal_reference(
        self, trade_date: date, signal_date: date | None
    ) -> tuple[float, dict[str, float]]:
        """信号日估值引用（W2E3 修复#1：无前视）。

        nav_ref = 信号日（上一交易日）收盘 NAV；closes_ref = 持仓在信号日
        的收盘价。信号日恰为上一执行日时直接取其 EOD 快照（同一口径），
        否则用输入包行情重估（首日：现金=initial，持仓为空）。
        """
        if signal_date is None:
            return float(self.config.initial_cash), {}
        if self.equity and self.equity[-1]["trade_date"] == signal_date.isoformat():
            snap = self.equity[-1]
            closes = {
                sym: float(p["close"])
                for sym, p in (snap.get("positions") or {}).items()
            }
            # M4E1（项3）：目标额度取精确 NAV（nav_exact 优先）——合同口径
            # "信号日收盘 NAV"本义即精确值（语义澄清，非默改；舍入边缘的
            # 目标量可能与旧构建差 1 股，回归说明见附录）
            return float(snap.get("nav_exact", snap["nav"])), closes
        sig_bars = self.package.load_date(signal_date)
        closes: dict[str, float] = {}
        market_value = 0.0
        for sym, pos in self.positions.items():
            bar = sig_bars.get(sym)
            # F1 AC-02：信号日缺行情沿用最近有效市价（carry-forward），
            # 禁止静默改用成本价
            close = bar.close if (bar and bar.close > 0) else pos.last_mark
            closes[sym] = close
            market_value += pos.qty * close
        return self.cash + self.dividend_receivable + market_value, closes

    def _signal_close_for(self, symbol: str, signal_date: date | None) -> float | None:
        """标的在信号日（或其前最近可得日）的收盘价；不可得返回 None。"""
        if signal_date is None:
            return None
        probe = signal_date
        for _ in range(5):  # DG-003 缺行日回看最多 5 个交易日
            bar = self.package.get_bar(symbol, probe)
            if bar is not None and bar.close > 0:
                return bar.close
            prev = self.package.prev_trade_date(probe)
            if prev is None:
                return None
            probe = prev
        return None

    def _rebalance(
        self,
        trade_date: date,
        bars: dict,
        target_weights: dict[str, float],
        signal_date: date | None,
        nav_ref: float,
        closes_ref: dict[str, float],
        summary: DaySummary,
    ) -> None:
        """目标权重 → 订单，先卖后买（腾出现金）。

        W2E3 修复#1：目标金额 = weight × 信号日收盘 NAV，定手数用信号日
        收盘价；执行只用执行日开盘价成交（无前视）。ideal_weight=信号
        目标权重，realized_weight 在 EOD 按 (qty×close)/nav 回填（DG-001）。
        """
        if nav_ref <= 0:
            return
        sells: list[LedgerOrder] = []
        buys: list[LedgerOrder] = []
        for symbol, weight in sorted(target_weights.items()):
            symbol = symbol.upper()
            bar = bars.get(symbol)
            price = (
                closes_ref.get(symbol)
                or self._signal_close_for(symbol, signal_date)
                or 0.0
            )
            if price <= 0:
                # 信号日无可用收盘价：显式拒单，不用执行日价格定目标
                order = self.submit_order(
                    trade_date,
                    symbol,
                    "buy",
                    0,
                    origin="signal",
                    signal_date=signal_date,
                    ideal_weight=weight,
                )
                order.status = ORDER_STATUS_REJECTED
                order.reject_reason = "stale_price"
                summary.orders.append(order.to_dict())
                continue
            target_amount = weight * nav_ref
            # 原始目标份额（按信号日收盘价）。M5E1（项1）：买差额初始
            # 申报按冻结方法"先 floor 整手"——申报量=floor(delta/100)*100
            # （delta 精确值含小数）；0 手→不下单+审计（min_lot_unreachable，
            # 含 raw_delta；不静默改目标）。卖侧零股规则不动；合法申报后的
            # 市场量部分成交不整手化。
            raw_target = target_amount / price
            pos = self.positions.get(symbol)
            current_qty = pos.qty if pos else 0.0
            delta = raw_target - current_qty
            side = "buy" if delta > 0 else "sell"
            if side == "buy":
                qty = int(math.floor(delta / 100.0)) * 100
                if qty <= 0:
                    summary.sublot_checks.append({
                        "symbol": symbol,
                        "trade_date": trade_date.isoformat(),
                        "buy_declaration": "min_lot_unreachable",
                        "raw_delta": round(delta, 6),
                        "target_weight": weight,
                        "sublot_check": "skipped_buy_min_lot_unreachable",
                    })
                    continue
            else:
                if abs(delta) < 1:
                    continue
                qty = int(math.ceil(-delta - 1e-9))
            order = self.submit_order(
                trade_date,
                symbol,
                side,
                qty,
                origin="signal",
                signal_date=signal_date,
                ideal_weight=weight,
            )
            # M2E1/M3E1/M4E1/M4E2（§3.3.8）：共享申报校验（run_day 与
            # manual_sell 统一入口），量截断/撮合前；放行亦留审计痕迹
            if side == "sell":
                reject_reason, sublot_audit = self._sublot_declaration_check(
                    trade_date, symbol, qty, pos, extra=f"target_weight={weight}"
                )
                if sublot_audit is not None:
                    sublot_audit["client_order_id"] = order.client_order_id
                    summary.sublot_checks.append(sublot_audit)
                if reject_reason:
                    order.status = ORDER_STATUS_REJECTED
                    order.reject_reason = reject_reason
                    order.qty_remaining = qty
                    summary.orders.append(order.to_dict())
                    continue
            if bar is None or bar.suspended:
                # 停牌/无行情日不虚构成交：显式拒单留痕
                order.status = ORDER_STATUS_REJECTED
                order.reject_reason = "no_quote" if bar is None else "suspended"
                summary.orders.append(order.to_dict())
                continue
            (buys if side == "buy" else sells).append(order)
        for order in sells + buys:
            self._validate_and_execute(order, trade_date, bars, summary)

    # ------------------------------------------------------------------
    # 公司行动
    # ------------------------------------------------------------------

    def _apply_share_adjustment(self, ev: TypedEvent) -> dict[str, Any] | None:
        """份额调整：开盘前、撮合前；qty×=multiplier、成本基准同比例调整、
        不动现金。幂等键 (ledger_run_id, symbol, event_date, event_type)。
        """
        if ev.event_type != "share_adjustment":
            return None  # 非份额调整事件不入此路径（防误用）
        key = (self.ledger_run_id, ev.symbol, ev.event_date.isoformat(), ev.event_type)
        if key in self.applied_action_keys:
            return None
        self.applied_action_keys.add(key)
        pos = self.positions.get(ev.symbol)
        record = {
            "idempotency_key": list(key),
            "event_type": ev.event_type,
            "symbol": ev.symbol,
            "event_date": ev.event_date.isoformat(),
            "qty_multiplier": ev.qty_multiplier,
            "qty_before": round(pos.qty, 4) if pos else 0.0,
            "cash_delta": 0.0,
            "applied": pos is not None and pos.qty > 0,
        }
        if pos is not None and pos.qty > 0:
            pos.qty *= ev.qty_multiplier
            pos.available_qty *= ev.qty_multiplier
            pos.avg_cost /= ev.qty_multiplier  # 成本基准同比例调整
            # F1 AC-02：carry-forward 市价同步换算到新份额口径（qty×m ↔ mark/m）
            if pos.last_mark > 0:
                pos.last_mark /= ev.qty_multiplier
            record["qty_after"] = round(pos.qty, 4)
            record["avg_cost_after"] = round(pos.avg_cost, 6)
        self.corporate_action_log.append(record)
        return record

    # ------------------------------------------------------------------
    # 分红三段式（F2 / ledger-contract v3 §5-§6）
    # 幂等键 (ledger_run_id, symbol, event_id, entitlement_date=record_date)，
    # 三段共用同键；旧"ex_date EOD 按交易后持仓发放"路径已删除（AC-01 判定
    # 为错误语义：误发无权盘、漏发已卖盘、提前释放现金）。
    # ------------------------------------------------------------------

    def _entitlement_key(self, ev: TypedEvent) -> tuple[str, str, str, str]:
        return (
            self.ledger_run_id,
            ev.symbol,
            ev.event_id,
            ev.record_date.isoformat() if ev.record_date else "",
        )

    def _stage_dividend_entitlement(self, trade_date: date) -> None:
        """record_date EOD：按收盘在册持仓定格权益（登记日当日买入享有、
        登记日后卖出不消灭）。不产生现金流；qty 为当日交易后持仓。

        口径统一（v3 §6）：record→ex 之间发生份额调整时，包内
        cash_per_share 为调整后份额口径，定额按 record 日旧口径持仓换算：
        amount = record_qty × cps × Π(multiplier)（等价 record_qty×cps_old）。
        """
        for ev in self.package.dividend_events():
            if ev.blocked or ev.record_date != trade_date:
                continue
            key = self._entitlement_key(ev)
            if key in self.dividend_entitlements:
                continue  # 幂等：重放不重复定格
            pos = self.positions.get(ev.symbol)
            qty = pos.qty if pos else 0.0
            basis_multiplier = 1.0
            for adj in self.package.events_for(ev.symbol):
                if (
                    adj.event_type == "share_adjustment"
                    and ev.record_date < adj.event_date <= ev.event_date
                ):
                    basis_multiplier *= adj.qty_multiplier
            amount = qty * ev.cash_per_share * basis_multiplier
            self.dividend_entitlements[key] = {
                "symbol": ev.symbol,
                "event_id": ev.event_id,
                "record_date": ev.record_date.isoformat(),
                "ex_date": ev.event_date.isoformat(),
                "pay_date": ev.pay_date.isoformat() if ev.pay_date else None,
                "cash_per_share": ev.cash_per_share,
                "basis_multiplier": basis_multiplier,  # M3E2：全精度
                "entitlement_qty": qty,  # M3E2：全精度（展示层才格式化）
                "entitlement_amount": amount,  # M3E1：全精度（pay 段入账金额）
                "stage": "entitled",
                "entitled_on": trade_date.isoformat(),
            }

    def _stage_dividend_receivable(self, trade_date: date) -> list[dict[str, Any]]:
        """ex_date 开盘前：entitlement → dividend_receivable（计入 nav、
        不可用于交易）。价格序列自当日起已除息。"""
        staged: list[dict[str, Any]] = []
        for rec in self.dividend_entitlements.values():
            if rec["stage"] != "entitled" or rec["ex_date"] != trade_date.isoformat():
                continue
            self.dividend_receivable += rec["entitlement_amount"]
            rec["stage"] = "receivable"
            rec["receivable_on"] = trade_date.isoformat()
            staged.append({**rec, "action": "receivable"})
        return staged

    def _stage_dividend_pay(self, trade_date: date) -> list[dict[str, Any]]:
        """pay_date 开盘前：应收转可用现金（当日可交易）。"""
        staged: list[dict[str, Any]] = []
        for rec in self.dividend_entitlements.values():
            if (
                rec["stage"] != "receivable"
                or rec["pay_date"] is None
                or rec["pay_date"] != trade_date.isoformat()
            ):
                continue
            self.dividend_receivable -= rec["entitlement_amount"]
            self.cash += rec["entitlement_amount"]
            rec["stage"] = "paid"
            rec["paid_on"] = trade_date.isoformat()
            staged.append({**rec, "action": "paid"})
        return staged

    def _register_blocked_dividends(self) -> list[dict[str, Any]]:
        """日期缺失（unknown_blocked）分红：三段全阻塞、显式入缺口、
        暂停该标的后续买入（corporate_action_gap 拒单）。幂等登记。"""
        out: list[dict[str, Any]] = []
        for ev in self.package.blocked_dividend_events():
            key = f"blocked:{ev.symbol}:{ev.event_id}"
            if any(b["key"] == key for b in self.blocked_dividend_log):
                continue
            record = {
                "key": key,
                "symbol": ev.symbol,
                "event_id": ev.event_id,
                "ex_date": ev.event_date.isoformat(),
                "record_date_status": ev.record_date_status,
                "pay_date_status": ev.pay_date_status,
                "action": "blocked",
                "note": "分红日期缺失：权益/到账各段显式阻塞（不默认 ex_date），停买该标的",
            }
            self.blocked_dividend_log.append(record)
            self.buy_suspended_symbols.add(ev.symbol)
            out.append(record)
        return out

    # ------------------------------------------------------------------
    # EOD
    # ------------------------------------------------------------------

    def _rollover_settlement(self, trade_date: date) -> None:
        """日初回转解锁（W2E3 修复#2）：仅解锁已跨过 T+1 边界的具体买入
        批次——pending 批次的买入日严格早于今日时解锁（available=qty−0），
        当日稍后新买入的批次单独记 pending，不受影响。
        """
        for pos in self.positions.values():
            if etf_settlement_days_for_symbol(pos.symbol) >= 1:
                if (
                    pos.pending_t1_date is not None
                    and date.fromisoformat(pos.pending_t1_date) < trade_date
                ):
                    pos.available_qty = pos.qty
                    pos.pending_t1_qty = 0.0
                    pos.pending_t1_date = None

    def _nav_with_bars(self, bars: dict) -> float:
        market_value = 0.0
        for symbol, pos in self.positions.items():
            bar = bars.get(symbol)
            # F1 AC-02：缺行情沿用最近有效市价，不再回退成本价
            close = bar.close if (bar and bar.close > 0) else pos.last_mark
            market_value += pos.qty * close
        return self.cash + self.dividend_receivable + market_value

    def _eod(self, trade_date: date, bars: dict, summary: DaySummary) -> None:
        # 部分成交剩余量收口：当日收盘后转 expired_unfilled，不隔日挂单
        for order in self.orders.values():
            if order.trade_date == trade_date.isoformat() and (
                order.status == ORDER_STATUS_PARTIALLY_FILLED
            ):
                order.status = ORDER_STATUS_EXPIRED_UNFILLED

        # record_date EOD：收盘在册持仓定格分红权益（F2 三段式第一段；
        # 旧 ex_date EOD 发放路径已删除）
        self._stage_dividend_entitlement(trade_date)

        # 收盘估值（F1 修复 AC-02 冻结政策）：有行情 → mark=收盘、陈旧清零；
        # 缺行情 → 沿用最近有效市价（carry-forward）、陈旧 +1；连续缺日超
        # 阈值 → 当日快照 valuation_reliable=False（结果不可信，显式暴露）
        market_value = 0.0
        fees_today = 0.0
        realized_pnl_today = 0.0
        valuation_reliable = True
        positions_out: dict[str, Any] = {}
        for symbol, pos in sorted(self.positions.items()):
            bar = bars.get(symbol)
            if bar is not None and bar.close > 0:
                pos.last_mark = float(bar.close)
                pos.last_mark_date = trade_date.isoformat()
                pos.stale_days = 0
                mark_source = "eod_close"
            else:
                pos.stale_days += 1
                mark_source = "carry_forward"
            if pos.stale_days > self.config.stale_mark_limit:
                valuation_reliable = False
            if pos.last_mark > 0:
                close = pos.last_mark
            else:
                # F3 修复#1：从未观测到任何有效市价（首个持仓日即缺行情）——
                # 无"最近有效市价"可 carry，禁止静默回退成本价；持仓以 0 计
                # 入 nav 并强制当日快照不可信（显式暴露，非 silently cost）
                close = 0.0
                mark_source = "unavailable"
                valuation_reliable = False
            market_value += pos.qty * close
            positions_out[symbol] = {
                **pos.to_dict(),
                "close": round(close, 4),
                "mark_source": mark_source,
                "market_value": round(pos.qty * close, 4),
            }
        # v3 §8：nav = cash + dividend_receivable + Σ qty×close（应收计入
        # nav 并参与两条风险线；pay 日转现金后不重复计入）
        nav = self.cash + self.dividend_receivable + market_value
        for order in self.orders.values():
            if order.trade_date == trade_date.isoformat():
                fees_today += order.fees
                realized_pnl_today += order.realized_pnl

        # realized_weight 回填（DG-001）
        for order in self.orders.values():
            if order.trade_date == trade_date.isoformat() and nav > 0:
                bar = bars.get(order.symbol)
                close = bar.close if (bar and bar.close > 0) else 0.0
                pos = self.positions.get(order.symbol)
                qty = pos.qty if pos else 0.0
                order.realized_weight = round(qty * close / nav, 6)

        # 风险评估（HWM 更新 + 两线独立触发）
        triggered = self.risk.on_eod(nav, trade_date)
        summary.risk_events.extend(ev.to_dict() for ev in triggered)

        snapshot = {
            "trade_date": trade_date.isoformat(),
            "cash": round(self.cash, 4),
            "dividend_receivable": round(self.dividend_receivable, 4),
            "market_value": round(market_value, 4),
            "nav": round(nav, 4),
            # J7R5：全精度 NAV 审计字段（严格对账用——与复算全精度值直接
            # 相减，比较前禁止 round/format；展示字段 nav 不变）
            "nav_exact": nav,
            "valuation_reliable": valuation_reliable,
            "fees_today": round(fees_today, 4),
            "realized_pnl_today": round(realized_pnl_today, 4),
            "high_water_mark": round(self.risk.high_water_mark, 4),
            "risk_status": self.risk.status,
            "positions": positions_out,
        }
        self.equity.append(snapshot)
        summary.snapshot = snapshot

    # ------------------------------------------------------------------
    # 用户操作
    # ------------------------------------------------------------------

    def confirm_risk_event(
        self,
        risk_event_id: str,
        *,
        confirmed_by: str,
        confirmed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """用户逐线确认（幂等键 f"{ledger_run_id}:risk-confirm:{risk_event_id}"）。"""
        ts = (confirmed_at or utc_now()).astimezone(timezone.utc)
        # M3E2：确认净值取未舍入源（nav_exact 全精度；无快照回退 initial_cash）
        last = self.equity[-1] if self.equity else {}
        latest_nav = last.get(
            "nav_exact", last.get("nav", self.config.initial_cash)
        )
        self.risk.confirm(
            risk_event_id,
            confirmed_by=confirmed_by,
            confirmed_at=ts.isoformat(),
            nav_at_confirm=float(latest_nav),
        )
        return {
            "confirm_key": make_risk_confirm_key(self.ledger_run_id, risk_event_id),
            "risk_event_id": risk_event_id,
            "confirmed_by": confirmed_by,
            "confirmed_at": ts.isoformat(),
            "nav_at_confirm": latest_nav,
            "buys_allowed_after": self.risk.buys_allowed,
        }

    def manual_sell(
        self,
        trade_date: date,
        symbol: str,
        qty: int,
        *,
        reason: str,
        requested_by: str,
        bars: dict | None = None,
    ) -> LedgerOrder:
        """用户额外减仓：允许任意时刻（含风险暂停期）；记 manual_action；
        不影响 HWM（HWM 只在 EOD 由 nav 更新）、不解除风险暂停、不计为
        策略行为；nav 影响入账。"""
        # F1 修复 AC-04：同键重试幂等——已有订单（任意状态）原样返回，
        # 不重复成交、不把原成交改写为拒单（submit_order 内部另做同键
        # 异内容冲突校验）
        coid = make_client_order_id(self.ledger_run_id, trade_date, symbol, "sell")
        existing = self.orders.get(coid)
        if existing is not None:
            if existing.qty_target != int(qty):
                raise SameKeyOrderConflict(
                    f"client_order_id={coid} 已存在 qty_target={existing.qty_target}，"
                    f"与重试 qty={qty} 不一致（同键异内容禁止）"
                )
            return existing
        # W2E3 修复#5：无持仓/无可卖量的手动卖出同样拒单（no_position）
        position = self.positions.get(symbol)
        if position is None or position.available_qty <= 0:
            order = self.submit_order(trade_date, symbol, "sell", qty, origin="manual")
            order.status = ORDER_STATUS_REJECTED
            order.reject_reason = "no_position"
            order.qty_remaining = qty
            self.manual_actions.append(
                {
                    "date": trade_date.isoformat(),
                    "symbol": symbol,
                    "qty": qty,
                    "reason": reason,
                    "requested_by": requested_by,
                    "client_order_id": order.client_order_id,
                    "status": order.status,
                    "reject_reason": order.reject_reason,
                }
            )
            return order
        # M4E1/M4E2（项2）：manual_sell 与 run_day 统一申报入口——量截断/
        # 撮合前走同一 §3.3.8 校验（同一 helper），不可绕过；放行亦留痕
        sublot_reason, sublot_audit = self._sublot_declaration_check(
            trade_date, symbol, int(qty), position, extra=f"manual,reason={reason}"
        )
        if sublot_audit is not None:
            sublot_audit["client_order_id"] = make_client_order_id(
                self.ledger_run_id, trade_date, symbol, "sell"
            )
            self.sublot_check_log.append(sublot_audit)
        if sublot_reason:
            order = self.submit_order(trade_date, symbol, "sell", qty, origin="manual")
            order.status = ORDER_STATUS_REJECTED
            order.reject_reason = sublot_reason
            order.qty_remaining = qty
            self.manual_actions.append(
                {
                    "date": trade_date.isoformat(),
                    "symbol": symbol,
                    "qty": qty,
                    "reason": reason,
                    "requested_by": requested_by,
                    "client_order_id": order.client_order_id,
                    "status": order.status,
                    "reject_reason": order.reject_reason,
                }
            )
            return order
        bars = bars if bars is not None else self.package.load_date(trade_date)
        order = self.submit_order(
            trade_date,
            symbol,
            "sell",
            qty,
            origin="manual",
            signal_date=None,
        )
        summary = DaySummary(trade_date=trade_date.isoformat())
        self._validate_and_execute(order, trade_date, bars, summary)
        self.manual_actions.append(
            {
                "date": trade_date.isoformat(),
                "symbol": symbol,
                "qty": qty,
                "reason": reason,
                "requested_by": requested_by,
                "client_order_id": order.client_order_id,
                "status": order.status,
            }
        )
        return order

    def deposit(self, amount: float, *, requested_by: str) -> dict[str, Any]:
        """追加资金：一律拒绝（禁止掩蔽触发），拒绝记录入审计。"""
        record = {
            "requested_by": requested_by,
            "amount": float(amount),
            "accepted": False,
            "reason": "initial_cash_locked（ledger-contract §7：禁止追加资金掩蔽触发）",
            "ledger_run_id": self.ledger_run_id,
        }
        self.deposit_rejections.append(record)
        return record

    # ------------------------------------------------------------------
    # 证据导出
    # ------------------------------------------------------------------

    def export_evidence(self) -> dict[str, Any]:
        evidence = {
            "banner": (
                "FIXTURE 工程样例回放——不进策略收益排行"
                if self.package.is_fixture
                else "正式研究账本"
            ),
            "session": self.session_metadata(),
            "package": self.package.describe(),
            "orders": [o.to_dict() for o in self.orders.values()],
            "equity": list(self.equity),
            "corporate_actions": list(self.corporate_action_log),
            "dividends": [
                {**{"idempotency_key": list(k)}, **rec}
                for k, rec in self.dividend_entitlements.items()
            ],
            "blocked_dividends": list(self.blocked_dividend_log),
            "dividend_receivable": round(self.dividend_receivable, 4),
            "manual_actions": list(self.manual_actions),
            "deposit_rejections": list(self.deposit_rejections),
            "risk_blocked_orders": list(self.risk_blocked_orders),
            "risk_state": self.risk.to_dict(),
        }
        return evidence

    def export_view(self) -> dict[str, Any]:
        """公共展示导出（H1.1，view_schema=1）。

        唯一入口：Quickstart / 回报示例 / 页面共用；从审计原件
        ``export_evidence()`` 的真实输出派生（build_view_from_evidence），
        原件本身保持不动。字段缺失显式 ViewBuildError，不静默填零。
        """
        return build_view_from_evidence(self.export_evidence())

    # ------------------------------------------------------------------
    # checkpoint 导出/恢复（W2E3 修复#7：完整账本状态可持久化）
    # ------------------------------------------------------------------

    def export_checkpoint(self) -> dict[str, Any]:
        """完整账本状态快照（纯状态、确定性；与 export_evidence 的区别：
        面向恢复重放，含全部可变状态，账务字段不做展示层取整）。"""
        return {
            "schema_version": 6,  # M4E1：v6=全精度（订单/成交/NAV sizing）
            "ledger_run_id": self.ledger_run_id,
            "package_id": self.package.package_id,
            # J4E1：跨包恢复身份=基线+已消费日增量清单（非瞬时 package_id）
            "input_binding": self.input_binding,
            "config": self.config.to_dict(),
            "contract_versions": dict(self.contract_versions),
            # M4E2（项2）：语义链——本快照数值的精度来源（legacy 恢复的
            # 账本导出标记 legacy，不冒充 full；schema 仍为 6 结构兼容）
            "precision_semantics": self.checkpoint_precision_origin,
            "cash": self.cash,
            "positions": {sym: pos.to_dict() for sym, pos in self.positions.items()},
            "executed_dates": sorted(self._executed_dates),
            "last_trade_date": (
                self._last_trade_date.isoformat() if self._last_trade_date else None
            ),
            "applied_action_keys": [list(k) for k in sorted(self.applied_action_keys)],
            "orders": {coid: o.to_dict() for coid, o in self.orders.items()},
            "equity": list(self.equity),
            "corporate_action_log": list(self.corporate_action_log),
            "dividend_log": [  # 兼容字段：三段式 entitlement 记录快照
                {**{"idempotency_key": list(k)}, **rec}
                for k, rec in self.dividend_entitlements.items()
            ],
            "dividend_receivable": self.dividend_receivable,
            "sublot_check_log": list(self.sublot_check_log),  # M5E1 项3：manual 审计恢复
            "manual_actions": list(self.manual_actions),
            "deposit_rejections": list(self.deposit_rejections),
            "risk_blocked_orders": list(self.risk_blocked_orders),
            "risk_state": self.risk.to_dict(),
        }

    @classmethod
    def restore(
        cls,
        package: EtfInputPackage,
        config: R01LedgerConfig,
        checkpoint: dict[str, Any],
    ) -> R01Ledger:
        """从 export_checkpoint 快照恢复账本，可继续推演。

        恢复校验 ledger_run_id 一致（防错配）；风险状态按事件重算
        status（不信任快照字符串）。
        """
        if checkpoint.get("ledger_run_id") != config.ledger_run_id:
            raise ValueError(
                f"checkpoint ledger_run_id 不匹配: {checkpoint.get('ledger_run_id')}"
                f" != {config.ledger_run_id}"
            )
        # W2E4/J4E1：跨包恢复防护——身份=基线+已消费日增量清单（前缀
        # 兼容）。旧式瞬时 package_id 全等仅在 checkpoint 无 input_binding
        # 时兜底；绑定缺失按冻结规则显式拒绝（schema v5 起必带）。
        cp_binding = checkpoint.get("input_binding")
        if cp_binding is None:
            raise CheckpointPackageMismatch(
                "checkpoint_package_mismatch: 快照缺少 input_binding 绑定字段"
                f"（schema_version={checkpoint.get('schema_version')}，拒绝恢复；"
                "重建包请用 daily_binding.rebuild_bound_package 并传入绑定）"
            )
        from backend.services.simulation.replay.daily_binding import (
            binding_compatible,
            capture_binding,
        )

        ok, why = binding_compatible(capture_binding(package), cp_binding)
        if not ok:
            raise CheckpointPackageMismatch(
                f"checkpoint_package_mismatch: {why}；已消费清单不因新发布的"
                "未消费日增量改变（消费新增量须 extend_binding 显式扩展）"
            )
        # F1 修复 AC-03：完整冻结 config 绑定——本金/费率/滑点/风险参数/
        # 参与率/组别/策略标识/attempt 全量比对；缺绑定字段（旧版快照）
        # 一律拒绝（无版本化迁移路径时不静默放行）
        # M4E1（项4）：checkpoint 精度语义版本——v6=全精度；v5=legacy_precision
        # （接受为历史快照，按原样恢复，不补偿已丢精度、不补造）；v4 缺
        # input_binding 由后续既有校验拒绝。
        cp_schema = checkpoint.get("schema_version")
        if cp_schema not in (5, 6):
            raise CheckpointConfigMismatch(
                f"checkpoint_config_mismatch: 不支持的 schema_version={cp_schema}"
                f"（允许 5=legacy_precision / 6=full_precision）"
            )
        # M4E2（项2）：precision_semantics 语义链——v6 必须带
        # full_precision 标记（缺失/异值=损坏拒绝）；v5 无标记即 legacy。
        # 恢复后 ledger 保留 origin 精度标记：再导出 schema 6 时标记
        # legacy（不冒充 full）。
        cp_precision = checkpoint.get("precision_semantics")
        # M5E1（项2）：v5 禁止携带 precision_semantics 标记——原生 v5 从不
        # 写该字段，出现即矛盾标记=损坏，拒绝（防 v5 被洗成 v6/full）。
        if cp_schema == 5 and "precision_semantics" in checkpoint:
            raise CheckpointConfigMismatch(
                "checkpoint_config_mismatch: schema 5 携带 precision_semantics="
                f"{cp_precision!r}（原生 v5 无此字段，矛盾标记=损坏快照拒绝）"
            )
        if cp_schema == 6 and cp_precision not in ("full_precision", "legacy_precision"):
            raise CheckpointConfigMismatch(
                f"checkpoint_config_mismatch: schema 6 缺/错 precision_semantics="
                f"{cp_precision!r}（允许 full/legacy，损坏快照拒绝）"
            )
        cp_config = checkpoint.get("config")
        if not isinstance(cp_config, dict) or "initial_cash" not in cp_config:
            raise CheckpointConfigMismatch(
                "checkpoint_config_mismatch: 快照缺少冻结 config 绑定字段"
                f"（schema_version={checkpoint.get('schema_version')}，拒绝恢复）"
            )
        new_config = config.to_dict()
        if cp_config != new_config:
            diff = {
                k: (cp_config.get(k), new_config.get(k))
                for k in sorted(set(cp_config) | set(new_config))
                if cp_config.get(k) != new_config.get(k)
            }
            raise CheckpointConfigMismatch(
                f"checkpoint_config_mismatch: 冻结参数不一致 {diff}；"
                f"变更参数须新建 strategy_version/execution_attempt"
            )
        cp_contracts = checkpoint.get("contract_versions")
        current_contracts = _current_contract_versions()
        if cp_contracts is None:
            # 缺绑定字段（旧版快照）显式拒绝：无版本化迁移路径不静默放行
            raise CheckpointConfigMismatch(
                "checkpoint_config_mismatch: 快照缺少 contract_versions 绑定字段"
                f"（schema_version={checkpoint.get('schema_version')}，拒绝恢复）"
            )
        if cp_contracts != current_contracts:
            # M4E1（项4）：v5 legacy 快照携带 v3 合同版本——接受为
            # legacy_precision（ledger_contract v3 是其生成时身份，非漂移）；
            # 其余不一致（含 v6 携带旧版本）仍拒绝
            legacy_ok = cp_schema == 5 and cp_contracts.get(
                "ledger_contract"
            ) == "v3" and cp_contracts.get("etf_input_package_schema") == "v3"
            if not legacy_ok:
                raise CheckpointConfigMismatch(
                    f"checkpoint_config_mismatch: 合同版本不一致 "
                    f"checkpoint={cp_contracts} vs 当前={current_contracts}"
                )
        ledger = cls(package, config)
        ledger.cash = float(checkpoint["cash"])
        ledger.positions = {
            sym: LedgerPosition.from_dict(p)
            for sym, p in checkpoint.get("positions", {}).items()
        }
        ledger._executed_dates = set(checkpoint.get("executed_dates", []))
        ltd = checkpoint.get("last_trade_date")
        ledger._last_trade_date = date.fromisoformat(ltd) if ltd else None
        ledger.applied_action_keys = {
            tuple(k) for k in checkpoint.get("applied_action_keys", [])
        }
        ledger.orders = {
            coid: LedgerOrder.from_dict(o)
            for coid, o in checkpoint.get("orders", {}).items()
        }
        ledger.equity = list(checkpoint.get("equity", []))
        ledger.corporate_action_log = list(checkpoint.get("corporate_action_log", []))
        ledger.dividend_entitlements = {
            tuple(rec["idempotency_key"]): {
                k: v for k, v in rec.items() if k != "idempotency_key"
            }
            for rec in checkpoint.get("dividend_log", [])
        }
        ledger.dividend_receivable = float(checkpoint.get("dividend_receivable", 0.0))
        ledger.sublot_check_log = list(checkpoint.get("sublot_check_log", []))
        ledger.manual_actions = list(checkpoint.get("manual_actions", []))
        ledger.deposit_rejections = list(checkpoint.get("deposit_rejections", []))
        ledger.risk_blocked_orders = list(checkpoint.get("risk_blocked_orders", []))
        # M5E1（项3）：nested risk_state.config 与顶层冻结风险配置一致性
        # 校验——不一致=混合口径快照，显式拒绝
        cp_risk_cfg = (checkpoint.get("risk_state") or {}).get("config") or {}
        exp_loss = (
            config.loss_line_amount
            if config.loss_line_amount is not None
            else config.initial_cash * 0.30
        )
        exp_dd = config.drawdown_pct
        if (
            cp_risk_cfg.get("initial_cash") != config.initial_cash
            or cp_risk_cfg.get("loss_line_amount") != exp_loss
            or cp_risk_cfg.get("drawdown_pct") != exp_dd
        ):
            raise CheckpointConfigMismatch(
                "checkpoint_config_mismatch: nested risk_state.config 与顶层"
                f"冻结风险配置不一致：checkpoint={cp_risk_cfg} vs"
                f" config(initial={config.initial_cash}, loss={exp_loss},"
                f" dd={exp_dd})"
            )
        ledger.risk = RiskStateMachine.from_dict(checkpoint["risk_state"])
        # M4E2：origin 精度标记（legacy 恢复的账本不冒充 full）
        # M5E1：legacy 判定只认 schema_version（v5=无条件 legacy）；
        # 仅原生 v6（schema6 + full 标记）可为 full
        ledger.checkpoint_precision_origin = (
            "legacy_precision" if cp_schema == 5 else cp_precision
        )
        return ledger


# ---------------------------------------------------------------------------
# 独立复算（ledger-contract §9：用输入包原始数据独立重算现金/净值逐日对齐）
# ---------------------------------------------------------------------------


def independent_recompute(
    evidence: dict[str, Any],
    package: EtfInputPackage | None = None,
    *,
    round_output: bool = True,
) -> list[dict[str, Any]]:
    """从导出证据的原始明细（成交/公司行动）独立重建 nav 序列。

    ``round_output=True``（默认）输出 4dp 展示口径；``False`` 输出全精度
    （J2E2 精度政策：对账侧可用全精度逐行判定；默认行为不变）。

    F2（ledger-contract v3 / AC-01）：分红权益资格**独立重算**——按
    record_date 收盘在册持仓定格、ex 入应收、pay 转现金，全部从输入包
    typed 事件与自身持仓重放推导，**不读引擎 dividend_entitlements/
    dividend_receivable/分红日志**（package 缺省时不做分红核算，仅限
    无分红的遗留证据）。份额调整仍从证据 corporate_actions 重放。
    返回逐日 (date, cash, receivable, nav)，供与 evidence.equity 对账。
    """
    session = evidence["session"]
    cash = float(session["initial_cash"])
    positions: dict[str, float] = {}
    costs: dict[str, float] = {}
    dividend_receivable = 0.0
    # 独立权益表：键 (symbol, event_id, record_date) —— 与引擎幂等键同构
    # 但完全由本函数从包事件+自身持仓推导
    entitlements: dict[tuple[str, str, str], dict[str, Any]] = {}
    last_close_seen: dict[str, float] = {}
    fills_by_date: dict[str, list[dict]] = {}
    for order in evidence["orders"]:
        for fill in order.get("fills", []):
            fills_by_date.setdefault(fill["trade_date"], []).append(fill)
    actions_by_date: dict[str, list[dict]] = {}
    for rec in evidence.get("corporate_actions", []):
        actions_by_date.setdefault(rec["event_date"], []).append(rec)

    # 分红事件按三日期独立索引（只用包，不用引擎日志）
    div_by_record: dict[str, list] = {}
    div_by_ex: dict[str, list] = {}
    div_by_pay: dict[str, list] = {}
    if package is not None:
        for ev in package.dividend_events():
            if ev.blocked:
                continue
            div_by_record.setdefault(ev.record_date.isoformat(), []).append(ev)
            div_by_ex.setdefault(ev.event_date.isoformat(), []).append(ev)
            div_by_pay.setdefault(ev.pay_date.isoformat(), []).append(ev)

    out: list[dict[str, Any]] = []
    for snap in evidence["equity"]:
        d = snap["trade_date"]
        day = date.fromisoformat(d)
        # 开盘前：份额调整（先于分红段）
        for rec in actions_by_date.get(d, []):
            sym = rec["symbol"]
            if rec["event_type"] == "share_adjustment" and sym in positions:
                mult = rec["qty_multiplier"]
                positions[sym] *= mult
        # 开盘前：分红段（独立重算）——ex 入应收、pay 转现金
        for ev in div_by_ex.get(d, []):
            key = (ev.symbol, ev.event_id, ev.record_date.isoformat())
            rec = entitlements.get(key)
            if rec is not None and rec["stage"] == "entitled":
                dividend_receivable += rec["amount"]
                rec["stage"] = "receivable"
        for ev in div_by_pay.get(d, []):
            key = (ev.symbol, ev.event_id, ev.record_date.isoformat())
            rec = entitlements.get(key)
            if rec is not None and rec["stage"] == "receivable":
                dividend_receivable -= rec["amount"]
                cash += rec["amount"]
                rec["stage"] = "paid"
        # 成交重放
        for fill in fills_by_date.get(d, []):
            sym, side, qty, price = (
                fill["symbol"],
                fill["side"],
                float(fill["quantity"]),
                float(fill["price"]),
            )
            # J6R4：优先全精度费用（total_fee_exact）——证据层 4dp 展示
            # 舍入不再进入复算重放；旧证据无该字段时回退展示值
            fee = float(fill.get("total_fee_exact", fill["total_fee"]))
            if side == "buy":
                cash -= qty * price + fee
                prev_qty = positions.get(sym, 0.0)
                new_qty = prev_qty + qty
                costs[sym] = (
                    (costs.get(sym, 0.0) * prev_qty + qty * price + fee) / new_qty
                    if new_qty > 0
                    else 0.0
                )
                positions[sym] = new_qty
            else:
                cash += qty * price - fee
                positions[sym] = positions.get(sym, 0.0) - qty
                if positions[sym] <= 1e-9:
                    positions.pop(sym, None)
                    costs.pop(sym, None)
        # EOD：record 收盘在册持仓定格权益（独立资格重算：当日交易后持仓；
        # record→ex 份额调整同口径换算 amount = qty × cps × Πm）
        for ev in div_by_record.get(d, []):
            key = (ev.symbol, ev.event_id, ev.record_date.isoformat())
            if key in entitlements:
                continue
            qty = positions.get(ev.symbol, 0.0)
            basis_m = 1.0
            if package is not None:
                for adj in package.events_for(ev.symbol):
                    if (
                        adj.event_type == "share_adjustment"
                        and ev.record_date < adj.event_date <= ev.event_date
                    ):
                        basis_m *= adj.qty_multiplier
            entitlements[key] = {
                "amount": qty * ev.cash_per_share * basis_m,  # M3E1：全精度
                "qty": qty,
                "stage": "entitled",
            }
        # nav：cash + receivable + Σ qty×close（独立 carry-forward 市价观察）
        market_value = 0.0
        for sym, qty in positions.items():
            close = 0.0
            if package is not None:
                bar = package.get_bar(sym, day)
                if bar is not None and bar.close > 0:
                    close = float(bar.close)
                    last_close_seen[sym] = close
                else:
                    close = last_close_seen.get(sym, 0.0)
            else:
                close = float(
                    (snap.get("positions") or {}).get(sym, {}).get("close", 0.0)
                )
            market_value += qty * close
        if round_output:
            out.append(
                {
                    "trade_date": d,
                    "cash": round(cash, 4),
                    "dividend_receivable": round(dividend_receivable, 4),
                    "nav": round(cash + dividend_receivable + market_value, 4),
                }
            )
        else:
            out.append(
                {
                    "trade_date": d,
                    "cash": cash,
                    "dividend_receivable": dividend_receivable,
                    "nav": cash + dividend_receivable + market_value,
                }
            )
    return out


# ---------------------------------------------------------------------------
# 公共展示导出（H1.1，view_schema=1）：从审计原件派生的明确版本展示结构
# ---------------------------------------------------------------------------

# v2（I1E1）：①days[].risk.status/high_water_mark 改取当日快照（禁止用
# 顶层最终态补历史，H1-AC01）；②持仓收盘标记字段统一 last_mark
# （H1-AC02，与页面消费字段一致；mark→last_mark）。
_VIEW_SCHEMA = 2

# days[].positions 逐日持仓必需字段（缺失 → ViewBuildError，不静默填零）
_VIEW_POSITION_FIELDS = (
    "qty",
    "avg_cost",
    "available_qty",
    "close",
    "mark_source",
    "market_value",
    "stale_days",
)
# days[] 快照必需字段
_VIEW_DAY_FIELDS = (
    "trade_date",
    "cash",
    "dividend_receivable",
    "market_value",
    "nav",
    "valuation_reliable",
    "positions",
)


def _view_require(container: dict, field: str, where: str) -> Any:
    """取必需字段；缺失/None 显式报错（H1.1：不静默填零）。"""
    if field not in container or container[field] is None:
        raise ViewBuildError(
            f"view_schema={_VIEW_SCHEMA} 构建失败：{where} 缺必需字段 {field!r}"
            f"（原生输出形状不合法或版本不匹配，拒绝静默填零）"
        )
    return container[field]


def build_view_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """把 export_evidence() 审计原件转换为 view_schema=1 展示结构（纯函数）。

    结构（字段表见 artifacts/p03/h1/README.md）：
    - days[]：逐日 cash/dividend_receivable/market_value/nav/valuation_reliable
      + positions[]（qty/avg_cost/available_qty/last_mark 收盘标记/mark_source/
      market_value/stale_days/last_mark_date）+ 当日 orders[]（qty 三态 target/filled/remaining、
      avg_fill_price、fees、status、reject_reason、signal_date、fills）
      + risk（当日 status/high_water_mark/当日新触发事件）
    - 顶层：orders 全量、risk_events、corporate_actions、dividends（三段式）、
      session/package/banner（fixture 标注随原件透传）。
    """
    session = evidence.get("session")
    if not isinstance(session, dict):
        raise ViewBuildError(
            "view 构建失败：evidence 缺 session（非原生 export_evidence 输出）"
        )
    orders = evidence.get("orders")
    equity = evidence.get("equity")
    if not isinstance(orders, list) or not isinstance(equity, list):
        raise ViewBuildError(
            "view 构建失败：evidence 缺顶层 orders/equity（原生审计原件必需）"
        )
    orders_by_day: dict[str, list[dict]] = {}
    for o in orders:
        coid = _view_require(o, "client_order_id", "order")
        day = _view_require(o, "trade_date", f"order {coid}")
        orders_by_day.setdefault(day, []).append(o)
    risk_state = evidence.get("risk_state") or {}
    risk_events = risk_state.get("events") or []
    events_by_day: dict[str, list[dict]] = {}
    for ev in risk_events:
        events_by_day.setdefault(str(ev.get("date")), []).append(ev)

    days: list[dict[str, Any]] = []
    for snap in equity:
        d = _view_require(snap, "trade_date", "equity 快照")
        positions_raw = _view_require(snap, "positions", f"equity {d}")
        positions_out = []
        for sym, p in sorted(positions_raw.items()):
            where = f"equity {d} position {sym}"
            positions_out.append(
                {
                    "symbol": sym,
                    # J2E2 精度政策：展示层格式化（qty/标记/市值 4dp、成本 6dp）；
                    # 数值源自全精度原件，仅呈现取整
                    "qty": round(float(_view_require(p, "qty", where)), 4),
                    "avg_cost": round(float(_view_require(p, "avg_cost", where)), 6),
                    "available_qty": round(
                        float(_view_require(p, "available_qty", where)), 4
                    ),
                    "last_mark": round(float(_view_require(p, "close", where)), 4),
                    "mark_source": _view_require(p, "mark_source", where),
                    "market_value": round(
                        float(_view_require(p, "market_value", where)), 4
                    ),
                    "stale_days": _view_require(p, "stale_days", where),
                    "last_mark_date": p.get("last_mark_date"),
                }
            )
        day_orders = []
        for o in orders_by_day.get(d, []):
            where = f"order {o.get('client_order_id')}"
            day_orders.append(
                {
                    "client_order_id": o["client_order_id"],
                    "symbol": _view_require(o, "symbol", where),
                    "side": _view_require(o, "side", where),
                    "origin": o.get("origin"),
                    "status": _view_require(o, "status", where),
                    "qty_target": _view_require(o, "qty_target", where),
                    "qty_filled": _view_require(o, "qty_filled", where),
                    "qty_remaining": _view_require(o, "qty_remaining", where),
                    "avg_fill_price": o.get("avg_fill_price"),
                    "fees": _view_require(o, "fees", where),
                    "reject_reason": o.get("reject_reason"),
                    "signal_date": o.get("signal_date"),
                    "ideal_weight": o.get("ideal_weight"),
                    "realized_weight": o.get("realized_weight"),
                    "fills": [
                        {
                            "price": f.get("price"),
                            "quantity": f.get("quantity"),
                            "total_fee": f.get("total_fee"),
                        }
                        for f in o.get("fills", [])
                    ],
                }
            )
        days.append(
            {
                "date": d,
                "cash": _view_require(snap, "cash", f"equity {d}"),
                "dividend_receivable": _view_require(
                    snap, "dividend_receivable", f"equity {d}"
                ),
                "market_value": _view_require(snap, "market_value", f"equity {d}"),
                "nav": _view_require(snap, "nav", f"equity {d}"),
                "valuation_reliable": _view_require(
                    snap, "valuation_reliable", f"equity {d}"
                ),
                "positions": positions_out,
                "orders": day_orders,
                # H1-AC01：逐日风险态/HWM 取当日快照（缺字段显式拒绝，
                # 禁止用顶层最终态补历史）；顶层 risk_state 仍为最终态
                "risk": {
                    "status": _view_require(snap, "risk_status", f"equity {d}"),
                    "high_water_mark": _view_require(
                        snap, "high_water_mark", f"equity {d}"
                    ),
                    "triggered_today": events_by_day.get(d, []),
                },
            }
        )

    return {
        "view_schema": _VIEW_SCHEMA,
        "derived_from": "R01Ledger.export_evidence",
        "banner": evidence.get("banner"),
        "session": {
            k: session.get(k)
            for k in (
                "strategy_id",
                "strategy_version",
                "execution_attempt_id",
                "ledger_run_id",
                "group",
                "initial_cash",
                "risk_config",
                "contract_versions",
                "is_fixture",
                "input_package_id",
            )
        },
        "package": {
            k: (evidence.get("package") or {}).get(k)
            for k in ("package_id", "package_version", "manifest_sha256", "is_fixture")
        },
        "risk_state": {
            "status": risk_state.get("status"),
            "high_water_mark": risk_state.get("high_water_mark"),
            "config": risk_state.get("config"),
        },
        "risk_events": risk_events,
        "corporate_actions": evidence.get("corporate_actions", []),
        "dividends": evidence.get("dividends", []),
        "blocked_dividends": evidence.get("blocked_dividends", []),
        "days": days,
    }


def identify_export_format(obj: dict[str, Any]) -> str:
    """判别导出对象格式（前端适配用，H1.1 文档同步）。

    返回：
    - "view"：view_schema=N 的展示结构（本模块 export_view 产物）
    - "evidence"：原生审计原件（export_evidence：顶层 banner/session/
      orders/equity，无 view_schema）
    - "legacy_fixture"：旧工程样例（顶层 day_summaries，attempt-1 形状；
      由前端侧兼容，账本侧只读判别不转换）
    - "unknown"：形状不明（消费方须显式拒绝，不猜）
    """
    if not isinstance(obj, dict):
        return "unknown"
    if "view_schema" in obj:
        return "view"
    if "day_summaries" in obj:
        return "legacy_fixture"
    if "banner" in obj and "session" in obj and "equity" in obj and "orders" in obj:
        return "evidence"
    return "unknown"


def _current_contract_versions() -> dict[str, str]:
    """restore 侧取当前合同版本（模块常量与实例初始化同源）。"""
    return dict(CONTRACT_VERSIONS)


def _normalize_reject_reason(reason: str) -> str:
    mapping = {
        "no_market_data": "no_quote",
        "suspended": "suspended",
        "limit_up": "limit_hit",
        "limit_down": "limit_hit",
        "insufficient_available_volume": "lot_inexpressible",
        "insufficient_market_volume": "lot_inexpressible",
        "below_lot_size": "lot_inexpressible",
        "insufficient_cash": "insufficient_cash",
        "invalid_price": "stale_price",
        "missing_execution_price": "stale_price",
        "risk_paused": "risk_paused",
        "corporate_action_gap": "corporate_action_gap",
    }
    return mapping.get(reason, reason)
