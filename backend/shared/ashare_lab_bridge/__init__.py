"""QuantMind 打分信号到 ashare-lab 次日开盘撮合的桥接。"""

from .bridge import (
    AshareLabUnavailable,
    BridgeConfig,
    BridgeResult,
    ashare_lab_available,
    import_ashare_lab,
    run_signal_backtest,
    signals_to_scores,
    to_ts_code,
)

__all__ = [
    "AshareLabUnavailable",
    "BridgeConfig",
    "BridgeResult",
    "ashare_lab_available",
    "import_ashare_lab",
    "run_signal_backtest",
    "signals_to_scores",
    "to_ts_code",
]
