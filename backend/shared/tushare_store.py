"""Fixed-release, local-only reads. Observation time is not historical PIT proof."""

from pathlib import Path

from backend.shared.tushare_pipeline import manifest_at

KEYS = {
    "trade_cal": ("exchange", "cal_date"),
    "ci_daily": ("ts_code", "trade_date"),
    "ci_index_member": ("l1_code", "l2_code", "l3_code", "ts_code", "in_date"),
    "etf_basic": ("ts_code",),
    "fund_daily": ("ts_code", "trade_date"),
    "fund_adj": ("ts_code", "trade_date"),
    "fund_portfolio": ("ts_code", "ann_date", "end_date", "symbol"),
}


def read_dataset(root, release_id, api_name):
    """Return latest observed rows within this pinned release, never fetch missing data.

    Retain _fetched_at and source fields. Callers must inspect coverage; this view
    does not authorize PIT backtests or assert historical data completeness.
    """
    import duckdb

    root = Path(root)
    manifest = manifest_at(root, release_id)
    keys = KEYS[api_name]
    paths = []
    for dataset in manifest["datasets"]:
        if dataset["api_name"] != api_name:
            continue
        name = dataset["path"]
        if name not in manifest["files"] or not name.startswith("parquet/"):
            raise ValueError("Dataset missing from verified file inventory")
        path = root / name
        if path.is_symlink() or path.stat().st_size != manifest["files"][name]["bytes"]:
            raise ValueError("Invalid stored partition")
        paths.append(str(path))
    if not paths:
        raise ValueError("Dataset unavailable in fixed release; no upstream fallback")
    with duckdb.connect(
        config={
            "memory_limit": "512MB",
            "threads": "2",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        }
    ) as db:
        relation = db.read_parquet(paths, union_by_name=True)
        if not set(keys).issubset(relation.columns):
            raise ValueError("Stored dataset lacks natural-key fields")
        relation.create_view("stored")
        partition = ",".join('"' + key + '"' for key in keys)
        return db.execute(
            "SELECT * FROM stored QUALIFY row_number() OVER (PARTITION BY "
            + partition
            + " ORDER BY _fetched_at DESC, _observation DESC)=1"
        ).fetch_arrow_table()
