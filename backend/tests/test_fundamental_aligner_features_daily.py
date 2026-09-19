from __future__ import annotations

import pandas as pd

import backend.services.engine.data_platform.quantdb_hub as hub_mod
from backend.shared.fundamental_aligner import FundamentalAligner


class _FakeHub:
    """对齐器读取路径的假 QuantDB 中枢：返回预置的 features_daily 行。"""

    available = True
    _inst = None

    def __init__(self, rows: pd.DataFrame):
        self._rows = rows

    @classmethod
    def get_instance(cls) -> _FakeHub:
        return cls._inst

    def fetch_latest_rows(self, view, symbols, dt=None, lookback=100, columns=None):
        if not symbols or df_empty(self._rows):
            return pd.DataFrame()
        need = ["symbol"] + [c for c in (columns or []) if c in self._rows.columns] + ["dt"]
        out = self._rows[self._rows["symbol"].isin(symbols)].copy()
        out["dt"] = dt or 0
        return out[need]


def df_empty(df: pd.DataFrame) -> bool:
    return df is None or df.empty


def test_filter_instruments_reads_features_daily_and_normalizes_symbols(monkeypatch):
    rows = pd.DataFrame(
        {
            "symbol": ["600001.SH", "000002.SZ", "600003.SH"],
            "total_mv": [3e9, 3e9, 3e9],
            "float_mv": [1e9, 1e9, 1e9],
            "pe_ttm": [20.0, -5.0, 30.0],
            "pb": [2.0, 2.0, 5.0],
            "vol_std_20": [0.03, 0.03, 0.08],
        }
    )
    fake = _FakeHub(rows)
    _FakeHub._inst = fake
    monkeypatch.setattr(hub_mod, "QuantDBDataHub", _FakeHub)

    aligner = FundamentalAligner()
    filtered = aligner.filter_instruments(
        "2026-08-21",
        ["SH600001", "SZ000002", "SH600003"],
        {
            "total_mv_min": 2e9,
            "float_mv_min": 5e8,
            "pe_ttm_min": 0,
            "pb_max": 3.5,
            "vol_std_20_max": 0.06,
        },
    )

    assert filtered == ["SH600001"]



def test_numeric_strings_preserve_codes_and_reject_unknown_values(tmp_path, monkeypatch):
    from backend.services.engine.data_platform.quantdb_hub import QuantDBDataHub

    values = pd.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "hs_turnover": ["2.5", "9.0", "--"],
        "is_st": ["0", "1", "--"],
        "sector_code": ["001", "002", "003"],
        "region_area_code": ["01", "02", "03"],
        "industry_name": ["银行", "科技", "能源"],
    })
    normalized = QuantDBDataHub._normalize_columns(None, values.copy())
    assert normalized["hs_turnover"].tolist()[:2] == [2.5, 9.0]
    assert pd.isna(normalized["hs_turnover"].iloc[2])
    for col in ("symbol", "sector_code", "region_area_code", "industry_name"):
        assert normalized[col].equals(values[col])

    partition = tmp_path / "6_ml_datasets/features_daily/dt=20260918"
    partition.mkdir(parents=True)
    values.to_parquet(partition / "data.parquet", index=False)
    monkeypatch.setattr(QuantDBDataHub, "_instance", QuantDBDataHub(tmp_path))
    aligner = FundamentalAligner()
    symbols = ["SZ000001", "SZ000002", "SZ000003"]
    for constraints in ({"hs_turnover_max": 3}, {"is_st": 0}, {"is_st_in": [0]}, {"is_st_not": 1}):
        assert aligner.filter_instruments("2026-09-18", symbols, constraints) == ["SZ000001"]
    assert aligner.filter_instruments("2026-09-18", symbols, {"sector_code": "001"}) == ["SZ000001"]


def test_exact_partition_connection_respects_resource_limits(tmp_path):
    from backend.services.engine.data_platform.quantdb_hub import QuantDBDataHub

    hub = QuantDBDataHub(tmp_path, duckdb_config={"memory_limit": "128MB", "threads": 1})
    conn = hub._exact_conn()
    assert conn.execute("SELECT current_setting('threads')").fetchone()[0] == 1
    assert conn.execute("SELECT current_setting('memory_limit')").fetchone()[0] == "122.0 MiB"
    assert hub._exact_conn() is conn
    conn.close()
