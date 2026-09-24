"""R01 ETF 固定输入包视图（TG-007 消费侧）。

p02 生产固定输入包（node://mac/r01-etf-daily/<version>），本模块是
执行层（p03）的唯一消费入口：

- 只读消费固定包，校验 manifest_sha256（调用方传入期望值时强制比对）；
- manifest 结构按 ``contracts/etf-input-package.schema.json`` (v2) 的
  必需字段做结构校验（机器 schema 全量校验由 p02 生产侧负责）；
- typed 公司行动事件逐行按 $defs.typed_event 语义校验后导出；
- daily/<code>.parquet 列口径：trade_date(YYYY-MM-DD), open, high, low,
  close, volume(原始单位:手), amount(原始单位:千元), adj_factor —— 单位
  换算按 manifest.unit_conversions（vol×100 → 份、amount×1000 → 元），
  派生 vwap=amount/volume，pre_close 取包内前一交易日，涨跌停按 ETF
  板块规则（默认 ±10%，588* 科创 ±20%）。

本轮（R01P0-W2E）用工程 fixture 样例包联调（package_id 以 ``fixture-``
开头、显著标注），真实包由 p02 交付后另派集成验证任务。

禁止：直接读 Mac 归档 CURRENT、裸拼接 QuantDB etf_kline（W1C 裁决）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from backend.services.simulation.services.local_market_data import DailyBar
from backend.shared.stock_utils import StockCodeUtil

logger = logging.getLogger(__name__)

# 涨跌幅：ETF 默认 ±10%，科创 ETF（588xxx）±20%。债券/黄金/跨境同为 ±10%
# （基金交易规则）。该口径为工程假设，p02 交付 etf_limit 数据集后以其为准。
_ETF_STAR_PREFIXES = ("588",)


class EtfInputPackageError(ValueError):
    """输入包结构/校验失败。"""


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# typed event（$defs.typed_event 的 Python 视图）
# ---------------------------------------------------------------------------

_EVENT_TYPES = ("cash_dividend", "share_adjustment")
_VERIFICATION_METHODS = (
    "pre_close_continuity",
    "nav_continuity",
    "fund_div_match",
    "unresolved_gap",
)


@dataclass(frozen=True)
class TypedEvent:
    """一条公司行动 typed 事件（账本只消费这个结构，不解读原始因子）。"""

    symbol: str
    event_date: date
    event_type: str  # cash_dividend | share_adjustment
    cash_per_share: float
    qty_multiplier: float
    derived_from: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    basis_note: str = ""

    @property
    def idempotency_key(self) -> tuple[str, str, str, str]:
        """(ledger_run_id 占位, symbol, event_date, event_type) 中后三段。"""
        return (self.symbol, self.event_date.isoformat(), self.event_type)


def _parse_typed_event_row(symbol: str, row: dict[str, Any]) -> TypedEvent:
    """逐行按 $defs.typed_event 语义校验并构造 TypedEvent。"""
    for key in ("event_date", "event_type", "cash_per_share", "qty_multiplier"):
        if key not in row:
            raise EtfInputPackageError(f"{symbol} 事件缺字段 {key}: {row}")
    try:
        event_date = date.fromisoformat(str(row["event_date"])[:10])
    except ValueError as exc:
        raise EtfInputPackageError(f"{symbol} 事件 event_date 非法: {row}") from exc
    event_type = str(row["event_type"])
    if event_type not in _EVENT_TYPES:
        raise EtfInputPackageError(f"{symbol} 事件 event_type 非法: {event_type}")
    cash_per_share = float(row["cash_per_share"])
    qty_multiplier = float(row["qty_multiplier"])
    if cash_per_share < 0:
        raise EtfInputPackageError(f"{symbol} 事件 cash_per_share<0: {row}")
    if qty_multiplier <= 0:
        raise EtfInputPackageError(f"{symbol} 事件 qty_multiplier<=0: {row}")
    derived_raw = row.get("derived_from") or {}
    if "adj_factor_prev" not in derived_raw or "adj_factor_new" not in derived_raw:
        raise EtfInputPackageError(f"{symbol} 事件 derived_from 缺因子对: {row}")
    derived = {
        "adj_factor_prev": float(derived_raw["adj_factor_prev"]),
        "adj_factor_new": float(derived_raw["adj_factor_new"]),
    }
    if "fund_div_ref" in derived_raw:
        derived["fund_div_ref"] = str(derived_raw["fund_div_ref"])
    ver_raw = row.get("verification") or {}
    if "passed" not in ver_raw or "method" not in ver_raw:
        raise EtfInputPackageError(f"{symbol} 事件 verification 缺字段: {row}")
    method = str(ver_raw["method"])
    if method not in _VERIFICATION_METHODS:
        raise EtfInputPackageError(f"{symbol} 事件 verification.method 非法: {method}")
    verification = {
        "passed": bool(ver_raw["passed"]),
        "method": method,
    }
    if "detail" in ver_raw:
        verification["detail"] = str(ver_raw["detail"])

    # allOf 分支语义
    if event_type == "cash_dividend":
        if qty_multiplier != 1:
            raise EtfInputPackageError(f"{symbol} 现金分红事件 qty_multiplier≠1: {row}")
        if cash_per_share <= 0:
            raise EtfInputPackageError(f"{symbol} 现金分红事件 cash_per_share≤0: {row}")
        if not derived.get("fund_div_ref"):
            raise EtfInputPackageError(f"{symbol} 现金分红事件缺 fund_div_ref: {row}")
    else:  # share_adjustment
        if cash_per_share != 0:
            raise EtfInputPackageError(f"{symbol} 份额调整事件 cash_per_share≠0: {row}")
        if qty_multiplier == 1:
            raise EtfInputPackageError(f"{symbol} 份额调整事件 qty_multiplier=1: {row}")

    return TypedEvent(
        symbol=symbol,
        event_date=event_date,
        event_type=event_type,
        cash_per_share=cash_per_share,
        qty_multiplier=qty_multiplier,
        derived_from=derived,
        verification=verification,
        basis_note=str(row.get("basis_note") or ""),
    )


# ---------------------------------------------------------------------------
# manifest 结构校验（必需字段子集；全量 schema 由生产侧 jsonschema 校验）
# ---------------------------------------------------------------------------

_MANIFEST_REQUIRED = (
    "schema_version",
    "package_id",
    "package_version",
    "package_uri",
    "source_release_id",
    "generated_at",
    "generated_by_node",
    "source_datasets",
    "unit_conversions",
    "factor_convention",
    "symbols",
    "known_gaps",
)
_DATASET_NAMES = ("fund_daily", "fund_adj", "fund_div", "trade_cal", "etf_limit")


def _validate_manifest(manifest: dict[str, Any]) -> None:
    for key in _MANIFEST_REQUIRED:
        if key not in manifest:
            raise EtfInputPackageError(f"manifest 缺必需字段: {key}")
    if manifest["schema_version"] != 2:
        raise EtfInputPackageError(
            f"manifest schema_version≠2: {manifest['schema_version']}"
        )
    if not str(manifest["package_uri"]).startswith("node://"):
        raise EtfInputPackageError(
            f"package_uri 必须是节点受控 URI: {manifest['package_uri']}"
        )
    datasets = manifest["source_datasets"]
    if not isinstance(datasets, list) or not datasets:
        raise EtfInputPackageError("source_datasets 不能为空")
    for ds in datasets:
        if ds.get("api_name") not in _DATASET_NAMES:
            raise EtfInputPackageError(f"source_datasets.api_name 非法: {ds}")
        if not isinstance(ds.get("sha256"), str) or len(ds["sha256"]) != 64:
            raise EtfInputPackageError(f"source_datasets.sha256 非法: {ds}")
    symbols = manifest["symbols"]
    if not isinstance(symbols, list) or not symbols:
        raise EtfInputPackageError("symbols 不能为空")
    for sym in symbols:
        code = str(sym.get("code") or "")
        suffix = StockCodeUtil.to_suffix(code)
        if suffix != code or not suffix:
            raise EtfInputPackageError(f"symbols.code 必须为 suffix 式: {code}")


# ---------------------------------------------------------------------------
# 包视图
# ---------------------------------------------------------------------------


def _etf_limit_pct(symbol: str) -> float:
    code = symbol.split(".", 1)[0]
    return 0.20 if code.startswith(_ETF_STAR_PREFIXES) else 0.10


def _etf_limits(pre_close: float, symbol: str) -> tuple[float, float]:
    if pre_close <= 0:
        return math.inf, 0.0
    pct = _etf_limit_pct(symbol)
    up = round(round(pre_close * (1 + pct), 3) + 1e-9, 3)
    down = round(round(pre_close * (1 - pct), 3) + 1e-9, 3)
    return up, down


class EtfInputPackage:
    """一个固定输入包的只读视图（线程安全懒加载）。

    布局（本模块定义的冻结消费接口，p02 生产侧对齐）::

        <package_root>/manifest.json
        <package_root>/daily/<code>.parquet    # code 为 suffix 式（510300.SH）
        <package_root>/events/<code>.parquet   # typed 事件，可为空文件/缺省
    """

    def __init__(self, root: Path, manifest: dict[str, Any], manifest_sha256: str):
        self.root = Path(root)
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self.package_id = str(manifest["package_id"])
        self.package_version = str(manifest["package_version"])
        self.package_uri = str(manifest["package_uri"])
        self.is_fixture = self.package_id.startswith("fixture-")
        self._lock = threading.RLock()
        self._daily: dict[str, pd.DataFrame] = {}
        self._events: dict[str, list[TypedEvent]] = {}
        self._trade_dates: list[date] | None = None
        self._dates_by_symbol: dict[str, list[date]] = {}

    # -- 元数据 ----------------------------------------------------------

    def symbol_meta(self, code: str) -> dict[str, Any] | None:
        for sym in self.manifest["symbols"]:
            if sym["code"] == StockCodeUtil.to_suffix(code):
                return sym
        return None

    def known_gaps(self) -> list[dict[str, Any]]:
        return list(self.manifest.get("known_gaps") or [])

    # -- 日线 ------------------------------------------------------------

    def _load_daily(self, code: str) -> pd.DataFrame:
        suffix = StockCodeUtil.to_suffix(code)
        with self._lock:
            df = self._daily.get(suffix)
        if df is not None:
            return df
        path = self.root / "daily" / f"{suffix}.parquet"
        if not path.is_file():
            raise EtfInputPackageError(f"包内缺日线文件: {path.name}")
        df = pd.read_parquet(path)
        if "trade_date" not in df.columns:
            raise EtfInputPackageError(f"{suffix} 日线缺 trade_date 列")
        df = df.copy()
        df["trade_date"] = [
            date.fromisoformat(str(v)[:10]) if isinstance(v, str)
            else pd.Timestamp(v).date()
            for v in df["trade_date"]
        ]
        df = df.sort_values("trade_date").reset_index(drop=True)
        with self._lock:
            self._daily[suffix] = df
        return df

    def trade_dates(self) -> list[date]:
        """包级交易日并集（按全部 symbol 日线的日期并集，升序）。"""
        if self._trade_dates is None:
            all_dates: set[date] = set()
            for sym in self.manifest["symbols"]:
                df = self._load_daily(sym["code"])
                all_dates.update(df["trade_date"].tolist())
            self._trade_dates = sorted(all_dates)
        return list(self._trade_dates)

    def next_trade_date(self, d: date) -> date | None:
        dates = self.trade_dates()
        for x in dates:
            if x > d:
                return x
        return None

    def load_date(self, trade_date: date, symbols: list[str] | None = None) -> dict[str, DailyBar]:
        """按日加载 DailyBar（与 LocalMarketData.load_date 同口径）。

        单位换算按 manifest.unit_conventions 声明：vol 手→份 ×100、
        amount 千元→元 ×1000。pre_close 取该 symbol 包内前一交易日。
        """
        wanted = (
            [StockCodeUtil.to_suffix(s) for s in symbols]
            if symbols is not None
            else [sym["code"] for sym in self.manifest["symbols"]]
        )
        bars: dict[str, DailyBar] = {}
        for suffix in wanted:
            df = self._load_daily(suffix)
            day_rows = df[df["trade_date"] == trade_date]
            if day_rows.empty:
                continue
            row = day_rows.iloc[-1]
            prev_rows = df[df["trade_date"] < trade_date]
            pre_close = float(prev_rows.iloc[-1]["close"]) if not prev_rows.empty else 0.0

            close = float(row["close"])
            volume = max(float(row.get("volume", 0) or 0), 0.0) * 100.0
            amount = max(float(row.get("amount", 0) or 0), 0.0) * 1000.0
            vwap = amount / volume if volume > 0 and amount > 0 else close
            limit_up, limit_down = _etf_limits(pre_close, suffix)
            bars[suffix] = DailyBar(
                symbol=suffix,
                trade_date=trade_date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=close,
                volume=volume,
                amount=amount,
                vwap=vwap,
                pre_close=pre_close,
                limit_up=limit_up,
                limit_down=limit_down,
                is_st=False,
                suspended=volume <= 0,
                lot_size=100,
            )
        return bars

    def get_bar(self, symbol: str, trade_date: date) -> DailyBar | None:
        return self.load_date(trade_date, [symbol]).get(StockCodeUtil.to_suffix(symbol))

    def adjusted_close(self, symbol: str, trade_date: date) -> float | None:
        """信号口径：close × adj_factor（manifest.factor_convention 公式）。"""
        suffix = StockCodeUtil.to_suffix(symbol)
        df = self._load_daily(suffix)
        rows = df[df["trade_date"] == trade_date]
        if rows.empty:
            return None
        row = rows.iloc[-1]
        return float(row["close"]) * float(row.get("adj_factor", 1.0) or 1.0)

    # -- typed events ------------------------------------------------------

    def events_for(self, symbol: str) -> list[TypedEvent]:
        """该 symbol 的全部 typed 事件，按（日期, 份额调整优先）排序。

        同日并存时份额调整排在现金分红前（ledger-contract §6 时序：
        cash_per_share 已是调整后份额口径）。
        """
        suffix = StockCodeUtil.to_suffix(symbol)
        with self._lock:
            cached = self._events.get(suffix)
        if cached is not None:
            return list(cached)
        path = self.root / "events" / f"{suffix}.parquet"
        events: list[TypedEvent] = []
        if path.is_file():
            df = pd.read_parquet(path)
            for row in df.to_dict(orient="records"):
                events.append(_parse_typed_event_row(suffix, row))
        events.sort(key=lambda e: (e.event_date, 0 if e.event_type == "share_adjustment" else 1))
        with self._lock:
            self._events[suffix] = events
        return list(events)

    def events_on(self, trade_date: date) -> list[TypedEvent]:
        out: list[TypedEvent] = []
        for sym in self.manifest["symbols"]:
            for ev in self.events_for(sym["code"]):
                if ev.event_date == trade_date:
                    out.append(ev)
        return out

    def unresolved_gap_symbols(self) -> set[str]:
        """verification=unresolved_gap 的事件对应 symbol：账本暂停其后续买入。"""
        out: set[str] = set()
        for sym in self.manifest["symbols"]:
            for ev in self.events_for(sym["code"]):
                if ev.verification.get("method") == "unresolved_gap":
                    out.add(ev.symbol)
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_version": self.package_version,
            "package_uri": self.package_uri,
            "source_release_id": self.manifest["source_release_id"],
            "manifest_sha256": self.manifest_sha256,
            "is_fixture": self.is_fixture,
            "symbols": [s["code"] for s in self.manifest["symbols"]],
            "trade_dates": [d.isoformat() for d in self.trade_dates()],
            "event_count": sum(
                len(self.events_for(s["code"])) for s in self.manifest["symbols"]
            ),
        }


def load_etf_input_package(
    package_root: str | Path,
    *,
    expect_manifest_sha256: str | None = None,
) -> EtfInputPackage:
    """加载并校验固定输入包。

    expect_manifest_sha256 非空时强制比对 manifest.json 的 SHA256
    （TG-007：执行侧只读消费固定包并校验 manifest_sha256）。
    """
    root = Path(package_root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise EtfInputPackageError(f"输入包缺 manifest.json: {root}")
    digest = sha256_of_file(manifest_path)
    if expect_manifest_sha256 and digest != expect_manifest_sha256:
        raise EtfInputPackageError(
            f"manifest_sha256 不匹配: expect={expect_manifest_sha256} got={digest}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EtfInputPackageError(f"manifest.json 解析失败: {exc}") from exc
    _validate_manifest(manifest)
    return EtfInputPackage(root, manifest, digest)


# ---------------------------------------------------------------------------
# 工程 fixture 样例包构造器（仅测试/证据联调用，不进任何正式链路）
# ---------------------------------------------------------------------------


def build_fixture_package(
    root: str | Path,
    *,
    package_id: str = "fixture-r01-etf-daily-w2e",
    generated_by_node: str = "mac",
) -> EtfInputPackage:
    """写一个工程 fixture 样例包并返回其视图。

    显著标注：package_id 以 fixture- 开头；manifest.fixture=true。
    日常行情为确定性合成序列（真实包由 p02 产出，集成验证另派）。
    回归事件采用 DG-005 冻结口径：
      - 159934.SZ 2025-09-22 share_adjustment qty_multiplier=0.9481
      - 510500.SH 2015-04-15 share_adjustment qty_multiplier=0.2803
      - 510300.SH 分红链样例（cash_dividend）
    """
    root = Path(root)
    (root / "daily").mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)

    def _drift_series(start: date, days: int, base: float, drift: float):
        out = []
        cur = base
        d = start
        for _ in range(days):
            out.append((d, round(cur, 4)))
            cur = round(cur * (1 + drift), 4)
            d = date.fromordinal(d.toordinal() + 1)
        return out

    # -- 合成日线：6 个标的（覆盖验证池三类 + 回归对象） ------------------
    # (code, base_price, drift, adj_factor)
    universe = [
        ("510300.SH", 4.000, 0.002, 1.5000),   # 宽基，有分红
        ("510500.SH", 6.000, 0.001, 1.2000),   # 宽基，2015-04-15 份额折算
        ("159915.SZ", 3.000, 0.0015, 1.0000),  # 深市宽基对照
        ("511010.SH", 107.000, 0.0002, 1.0100),  # 国债（高价低手数 DG-001）
        ("518880.SH", 5.500, 0.0018, 1.4000),  # 黄金
        ("159934.SZ", 5.000, 0.0012, 1.0500),  # 黄金回归对象 2025-09-22 折算
    ]
    start = date(2025, 9, 8)
    days = 24
    daily_frames: dict[str, pd.DataFrame] = {}
    for code, base, drift, adj in universe:
        rows = []
        for d, close in _drift_series(start, days, base, drift):
            weekend = d.weekday() >= 5
            if weekend:
                continue
            openp = round(close * 0.999, 4)
            high = round(max(openp, close) * 1.003, 4)
            low = round(min(openp, close) * 0.997, 4)
            rows.append(
                {
                    "trade_date": d.isoformat(),
                    "open": openp,
                    "high": high,
                    "low": low,
                    "close": close,
                    # 手；停牌日置 0
                    "volume": 0.0 if d == date(2025, 9, 16) else 12000.0,
                    "amount": 0.0 if d == date(2025, 9, 16) else round(close * 12000 * 100 / 1000, 2),
                    "adj_factor": adj,
                }
            )
        daily_frames[code] = pd.DataFrame(rows)
        daily_frames[code].to_parquet(root / "daily" / f"{code}.parquet", index=False)

    # -- typed 事件 --------------------------------------------------------
    def _events_df(records):
        return pd.DataFrame(records)

    # 159934.SZ 2025-09-22 份额折算（DG-005 冻结回归值 0.9481）
    # adj 因子按 qty_multiplier = new/prev 反推：prev=1.0500 → new=1.0500×0.9481
    ev_159934 = [
        {
            "event_date": "2025-09-22",
            "event_type": "share_adjustment",
            "cash_per_share": 0.0,
            "qty_multiplier": 0.9481,
            "basis_note": "fixture：DG-005 回归冻结值",
            "derived_from": {
                "adj_factor_prev": 1.0500,
                "adj_factor_new": round(1.0500 * 0.9481, 6),
            },
            "verification": {"passed": True, "method": "pre_close_continuity", "detail": "fixture"},
        }
    ]
    # 510500.SH 2015-04-15 折算在 fixture 窗口之外（2015），此处按冻结值
    # 放一条 2025-09-18 的同倍率事件做账本回归（真实日期回归由 p02 真实包验证）
    ev_510500 = [
        {
            "event_date": "2025-09-18",
            "event_type": "share_adjustment",
            "cash_per_share": 0.0,
            "qty_multiplier": 0.2803,
            "basis_note": "fixture：DG-005 冻结倍率（真实日期 2015-04-15 待真实包回归）",
            "derived_from": {"adj_factor_prev": 1.2000, "adj_factor_new": round(1.2000 * 0.2803, 6)},
            "verification": {"passed": True, "method": "pre_close_continuity", "detail": "fixture"},
        }
    ]
    # 510300.SH 现金分红链（ex_date 2025-09-19，每份 0.05 元）
    ev_510300 = [
        {
            "event_date": "2025-09-19",
            "event_type": "cash_dividend",
            "cash_per_share": 0.05,
            "qty_multiplier": 1.0,
            "basis_note": "",
            "derived_from": {
                "adj_factor_prev": 1.5000,
                "adj_factor_new": 1.5000,
                "fund_div_ref": "fund_div:510300.SH:20250919:0.05",
            },
            "verification": {"passed": True, "method": "fund_div_match", "detail": "fixture"},
        }
    ]
    # 同日并存用例：518880.SH 2025-09-23 先份额调整后现金分红
    # （cash_per_share 已是调整后份额口径）
    ev_518880 = [
        {
            "event_date": "2025-09-23",
            "event_type": "share_adjustment",
            "cash_per_share": 0.0,
            "qty_multiplier": 0.5000,
            "basis_note": "",
            "derived_from": {"adj_factor_prev": 1.4000, "adj_factor_new": 0.7000},
            "verification": {"passed": True, "method": "pre_close_continuity", "detail": "fixture"},
        },
        {
            "event_date": "2025-09-23",
            "event_type": "cash_dividend",
            "cash_per_share": 0.0400,
            "qty_multiplier": 1.0,
            "basis_note": "同日既有份额调整：0.0400 已换算为调整后份额口径",
            "derived_from": {
                "adj_factor_prev": 0.7000,
                "adj_factor_new": 0.7000,
                "fund_div_ref": "fund_div:518880.SH:20250923:0.08",
            },
            "verification": {"passed": True, "method": "nav_continuity", "detail": "fixture"},
        },
    ]
    for code, recs in (
        ("159934.SZ", ev_159934),
        ("510500.SH", ev_510500),
        ("510300.SH", ev_510300),
        ("518880.SH", ev_518880),
    ):
        _events_df(recs).to_parquet(root / "events" / f"{code}.parquet", index=False)

    manifest = {
        "schema_version": 2,
        "package_id": package_id,
        "package_version": "w2e-fixture-1",
        "package_uri": f"node://{generated_by_node}/r01-etf-daily/{package_id}",
        "source_release_id": "fixture-no-release（工程合成，非 Tushare 归档）",
        "generated_at": "2026-09-25T00:00:00Z",
        "generated_by_node": generated_by_node,
        "fixture": True,
        "source_datasets": [
            {"api_name": "fund_daily", "sha256": "0" * 64},
            {"api_name": "fund_adj", "sha256": "0" * 64},
            {"api_name": "fund_div", "sha256": "0" * 64},
            {"api_name": "trade_cal", "sha256": "0" * 64},
            {"api_name": "etf_limit", "sha256": "0" * 64},
        ],
        "unit_conversions": {
            "vol": "lot(100 shares) -> shares, multiply by 100",
            "amount": "thousand CNY -> CNY, multiply by 1000",
            "rules": "fixture 合成序列按换算后单位反推原始单位",
        },
        "factor_convention": {
            "formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
            "verified_cases": [
                "159934.SZ 2025-09-22（fixture，冻结值 0.9481）",
                "510500.SH 2015-04-15（fixture，冻结值 0.2803）",
            ],
        },
        "symbols": [
            {
                "code": code,
                "class": cls,
                "role": role,
                "data_start": start.isoformat(),
                "data_end": (date.fromordinal(start.toordinal() + days - 1)).isoformat(),
                "missing_days": ["20250916"] if code == "510300.SH" else [],
                "warmup_start": start.isoformat(),
            }
            for code, cls, role in (
                ("510300.SH", "equity_broad", "primary"),
                ("510500.SH", "equity_broad", "primary"),
                ("159915.SZ", "equity_broad", "primary"),
                ("511010.SH", "treasury", "primary"),
                ("518880.SH", "gold", "primary"),
                ("159934.SZ", "gold", "regression-only"),
            )
        ],
        "known_gaps": [
            {
                "gap_id": "fixture-gap-1",
                "desc": "fixture：2025-09-16 全市场停牌日（volume=0）",
                "handling": "explicit-missing",
            }
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_etf_input_package(root)
