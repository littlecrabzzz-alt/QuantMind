"""复用 ashare-lab 的逐日撮合；不依赖 Qlib 或修改市场数据。"""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from backend.shared.stock_utils import StockCodeUtil


_VENDOR_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "ashare-lab"


class AshareLabUnavailable(RuntimeError):
    """本节点无法导入 ashare-lab。"""


def _source_dir() -> Path:
    return Path(os.environ.get("ASHARE_LAB_SRC", _VENDOR_ROOT / "src")).expanduser()


def _panel_dir() -> Path:
    return Path(os.environ.get("ASHARE_LAB_PANEL", _VENDOR_ROOT / "data" / "panel")).expanduser()


def import_ashare_lab() -> SimpleNamespace:
    """延迟导入仓库内源码，并暴露桥接所需的原生接口。"""
    try:
        source = _source_dir()
        if not (source / "ashare_lab").is_dir():
            raise AshareLabUnavailable(f"ashare-lab source missing: {source}")
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from ashare_lab import metrics
        from ashare_lab.data.market import MarketData, load_market_data
        from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
        from ashare_lab.strategies.score import ScoreStrategy
        from ashare_lab.strategy import Strategy, month_end_dates
        from ashare_lab.universe import eligible

        return SimpleNamespace(
            MarketData=MarketData,
            load_market_data=load_market_data,
            ScoreStrategy=ScoreStrategy,
            Strategy=Strategy,
            run_backtest=run_backtest,
            BacktestConfig=BacktestConfig,
            CostModel=CostModel,
            eligible=eligible,
            month_end_dates=month_end_dates,
            metrics=metrics,
        )
    except Exception as exc:
        raise AshareLabUnavailable(f"ashare-lab unavailable: {exc}") from exc


def ashare_lab_available() -> bool:
    """源码可导入且必需的面板文件齐备时返回 True。"""
    try:
        panel = _panel_dir()
        if not all((panel / name).is_file() for name in (
            "daily.parquet", "calendar.parquet", "stocks.parquet",
            "index_members.parquet", "index_daily.parquet",
        )):
            return False
        import_ashare_lab()
        return True
    except Exception:
        return False


def to_ts_code(instrument: str) -> str:
    """通过统一代码工具转换，并拒绝无法识别的 A 股代码。"""
    if not isinstance(instrument, str):
        raise ValueError(f"Invalid stock code: {instrument!r}")
    code = StockCodeUtil.to_suffix(instrument)
    if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code):
        raise ValueError(f"Invalid stock code: {instrument!r}")
    return code


def signals_to_scores(signals) -> pd.Series:
    """将双层索引的信号转换为按日期、后缀代码排序的分数。"""
    if isinstance(signals, pd.DataFrame):
        scores = signals["score"].copy()
    elif isinstance(signals, pd.Series):
        scores = signals.copy()
    else:
        raise ValueError("signals must be a DataFrame or Series")
    if not isinstance(scores.index, pd.MultiIndex) or scores.index.nlevels != 2:
        raise ValueError("signals must have a two-level (datetime, instrument) index")
    scores.index = pd.MultiIndex.from_arrays(
        [pd.to_datetime(scores.index.get_level_values(0)),
         [to_ts_code(code) for code in scores.index.get_level_values(1)]],
        names=["date", "code"],
    )
    if not scores.index.is_unique:
        raise ValueError("signals contain duplicate (date, code) entries")
    return scores.dropna().sort_index()


@dataclass
class BridgeConfig:
    initial_capital: float = 1e7
    topk: int = 50
    universe: str = "000906.SH"
    min_list_days: int = 250
    min_amount: float = 5e7
    commission: float = 0.00025
    transfer: float = 0.00001
    stamp_before: float = 0.001
    stamp_after: float = 0.0005
    slippage: float = 0.001
    lot: int = 100


@dataclass
class BridgeResult:
    success: bool
    error_message: str = ""
    nav: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    portfolio_dict: dict = field(default_factory=dict)


def run_signal_backtest(
    signals, start, end, config=BridgeConfig(), data=None, panel_dir=None,
) -> BridgeResult:
    """收盘信号在下一交易日开盘撮合；失败统一返回结果对象。"""
    try:
        scores = signals_to_scores(signals)
        lab = import_ashare_lab()
        if data is None:
            data = lab.load_market_data(
                Path(panel_dir).expanduser() if panel_dir is not None else _panel_dir(),
                pd.Timestamp(start) - pd.Timedelta(days=450), end,
                universe=config.universe,
            )

        class SignalStrategy(lab.ScoreStrategy):
            def target_weights(self, t, data):
                mask = lab.eligible(
                    t, data, config.universe, config.min_list_days,
                    min_amount=config.min_amount,
                )
                ranked = self.scores.loc[t].reindex(mask.index[mask]).dropna().sort_index()
                selected = ranked.sort_values(
                    ascending=False, kind="stable",
                ).head(self.top_n).index
                return (
                    pd.Series(1 / len(selected), index=selected)
                    if len(selected) else pd.Series(dtype=float)
                )

        costs = lab.CostModel(
            commission=config.commission, transfer=config.transfer,
            stamp_before=config.stamp_before, stamp_after=config.stamp_after,
            slippage=config.slippage, lot=config.lot,
        )
        result = lab.run_backtest(
            SignalStrategy(scores, top_n=config.topk), data,
            lab.BacktestConfig(start, end, config.initial_capital, costs),
        )
        nav = result.nav
        previous = nav.shift(1).fillna(config.initial_capital)
        fees = result.trades.groupby("date")["fee"].sum().reindex(nav.index, fill_value=0.0)
        traded = result.trades.loc[result.trades.side.isin(["buy", "sell"])]
        turnover = traded.groupby("date")["value"].sum().reindex(nav.index, fill_value=0.0)
        report = pd.DataFrame({
            "account": nav,
            "return": nav / previous - 1 + fees / previous,
            "cost": fees / previous,
            "cost_amount": fees,
            "turnover": turnover / previous,
            "cash": result.cash,
            "value": nav - result.cash,
        })
        final_value = float(nav.iloc[-1])
        return BridgeResult(
            success=True, nav=nav, trades=result.trades,
            annual_return=lab.metrics.cagr(nav),
            sharpe_ratio=lab.metrics.sharpe(nav),
            max_drawdown=lab.metrics.max_drawdown(nav),
            total_return=final_value / config.initial_capital - 1,
            portfolio_dict={
                "report": report, "final_value": final_value,
                "account": final_value,
                "position_value": float(report["value"].iloc[-1]),
                "execution_model": "ashare_lab_next_open_lot",
            },
        )
    except Exception as exc:
        return BridgeResult(success=False, error_message=str(exc))
