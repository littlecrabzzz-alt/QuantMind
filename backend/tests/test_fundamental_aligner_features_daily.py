from __future__ import annotations

import pandas as pd

from backend.shared.fundamental_aligner import FundamentalAligner


def test_filter_instruments_prefers_features_daily_and_normalizes_symbols(tmp_path):
    day_dir = tmp_path / "dt=20260821"
    day_dir.mkdir()
    pd.DataFrame(
        {
            "symbol": ["600001.SH", "000002.SZ", "600003.SH"],
            "total_mv": [3e9, 3e9, 3e9],
            "float_mv": [1e9, 1e9, 1e9],
            "pe_ttm": [20.0, -5.0, 30.0],
            "pb": [2.0, 2.0, 5.0],
            "vol_std_20": [0.03, 0.03, 0.08],
        }
    ).to_parquet(day_dir / "data.parquet", index=False)

    aligner = FundamentalAligner(parquet_path=str(tmp_path / "legacy.parquet"))
    aligner.features_daily_path = tmp_path

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



def test_numeric_strings_preserve_codes_and_reject_unknown_values(tmp_path):
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

    partition = tmp_path / "dt=20260918"
    partition.mkdir()
    values.to_parquet(partition / "data.parquet", index=False)
    aligner = FundamentalAligner(parquet_path=str(tmp_path / "absent.parquet"))
    aligner.features_daily_path = tmp_path
    symbols = ["SZ000001", "SZ000002", "SZ000003"]
    for constraints in ({"hs_turnover_max": 3}, {"is_st": 0}, {"is_st_in": [0]}, {"is_st_not": 1}):
        assert aligner.filter_instruments("2026-09-18", symbols, constraints) == ["SZ000001"]
    assert aligner.filter_instruments("2026-09-18", symbols, {"sector_code": "001"}) == ["SZ000001"]
