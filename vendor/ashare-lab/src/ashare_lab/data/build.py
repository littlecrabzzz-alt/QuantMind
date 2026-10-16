"""Build the research panel from the read-only local Tushare release."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


SOURCE = Path.home() / "Library/Application Support/QuantMind/tushare"
INDEXES = ("000300.SH", "000905.SH", "000906.SH", "000852.SH", "000985.SH")
A_SHARE = r"^(60|68|000|001|002|003|300|301)[0-9]+\.(SH|SZ)$"


def _date(column):
    return f"try_strptime(cast({column} as varchar), '%Y%m%d')::DATE"


# Canonical columns, primary keys, and the optional index selector.
APIS = {
    "daily_basic": (
        f"source_ts_code AS code, {_date('trade_date')} AS date, "
        "total_mv, circ_mv, pe_ttm, pb, dv_ttm, turnover_rate_f", "code, date", None,
    ),
    "daily": (
        f"source_ts_code AS code, {_date('trade_date')} AS date, "
        "open, high, low, close, pre_close, pct_chg, vol * 100.0 AS volume, "
        "amount * 1000.0 AS amount", "code, date", None,
    ),
    "adj_factor": (
        f"source_ts_code AS code, {_date('trade_date')} AS date, adj_factor AS adj",
        "code, date", None,
    ),
    "stk_limit": (
        f"source_ts_code AS code, {_date('trade_date')} AS date, "
        "up_limit, down_limit, pre_close AS limit_pre_close", "code, date", None,
    ),
    "suspend_d": (
        f"source_ts_code AS code, {_date('trade_date')} AS date, "
        "suspend_type, suspend_timing", "code, date", None,
    ),
    "stock_basic": (
        f"source_ts_code AS code, name, {_date('list_date')} AS list_date, "
        f"{_date('delist_date')} AS delist_date, list_status, market, exchange",
        "code", None,
    ),
    "index_weight": (
        f"source_index_code AS index_code, source_con_code AS code, "
        f"{_date('trade_date')} AS snapshot_date, weight",
        "index_code, code, snapshot_date", "source_index_code",
    ),
    "index_daily": (
        f"source_ts_code AS index_code, {_date('trade_date')} AS date, "
        "open, high, low, close, pct_chg", "index_code, date", "source_ts_code",
    ),
    "index_member_all": (
        f"source_ts_code AS code, l1_code, l1_name, {_date('in_date')} AS in_date, "
        f"{_date('out_date')} AS out_date", "code, l1_code, in_date", None,
    ),
    "trade_cal": (
        f"{_date('cal_date')} AS date, exchange, is_open", "date, exchange", None,
    ),
}


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _json_write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _copy(connection, query, path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    connection.execute(
        f"COPY ({query}) TO {_literal(temporary)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )
    temporary.replace(path)
    return pq.ParquetFile(path).metadata.num_rows


def _index_files(paths, column, targets, cache_path):
    """Conservatively prune files by *every* row group's code statistics."""
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    def inspect(path):
        metadata = pq.ParquetFile(path).metadata
        if column not in metadata.schema.names:
            return path, metadata.num_rows
        col = metadata.schema.names.index(column)
        for group in range(metadata.num_row_groups):
            stats = metadata.row_group(group).column(col).statistics
            if stats is None or not stats.has_min_max:
                return path, metadata.num_rows
            low, high = stats.min, stats.max
            if isinstance(low, bytes):
                low, high = low.decode(), high.decode()
            if any(low <= target <= high for target in targets):
                return path, metadata.num_rows
        return None, metadata.num_rows

    selected, total_rows = [], 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        # Bound outstanding footer reads instead of submitting 320,000 futures.
        for offset in range(0, len(paths), 10000):
            for path, rows in executor.map(inspect, paths[offset:offset + 10000]):
                total_rows += rows
                if path is not None:
                    selected.append(path)
            print(f"  footers {min(offset + 10000, len(paths))}/{len(paths)}, "
                  f"selected {len(selected)}", flush=True)
    result = {"paths": selected, "source_rows": total_rows}
    _json_write(cache_path, result)
    return result


def _cache_api(connection, api, paths, cache):
    output = cache / f"{api}.parquet"
    stats_path = cache / f"{api}.json"
    if output.exists() and stats_path.exists():
        print(f"{api}: reuse cache", flush=True)
        return json.loads(stats_path.read_text())
    columns, keys, selector = APIS[api]
    source_rows = None
    if selector:
        selection = _index_files(paths, selector,
                                 INDEXES if api == "index_daily" else INDEXES[:4],
                                 cache / f"{api}_files.json")
        paths, source_rows = selection["paths"], selection["source_rows"]
    if not paths:
        raise ValueError(f"No source files for {api}")
    print(f"{api}: reading {len(paths)} files", flush=True)
    for offset in range(0, len(paths), 1024):
        batch = paths[offset:offset + 1024]
        relation = connection.read_parquet(batch, union_by_name=True,
                                          hive_partitioning=False)
        relation.create_view("source_batch", replace=True)
        sql = (f"SELECT {columns}, _fetched_at::TIMESTAMPTZ AS fetched_at "
               "FROM source_batch")
        if offset == 0:
            connection.execute(f"CREATE OR REPLACE TEMP TABLE raw AS {sql}")
        else:
            connection.execute(f"INSERT INTO raw {sql}")
    read_rows = connection.execute("SELECT count(*) FROM raw").fetchone()[0]
    if selector:
        targets = INDEXES if api == "index_daily" else INDEXES[:4]
        condition = "index_code IN (" + ",".join(map(_literal, targets)) + ")"
        if api == "index_weight":
            condition += f" AND regexp_full_match(code, {_literal(A_SHARE)})"
    elif api == "trade_cal":
        condition = "exchange = 'SSE'"
    else:
        condition = f"regexp_full_match(code, {_literal(A_SHARE)})"
    deduplicated_rows = _copy(connection,
        "SELECT * EXCLUDE (fetched_at) FROM raw "
        f"WHERE {condition} QUALIFY row_number() OVER "
        f"(PARTITION BY {keys} ORDER BY fetched_at DESC NULLS LAST) = 1 "
        f"ORDER BY {keys}", output)
    stats = {"source_files": len(paths), "read_rows": read_rows,
             "source_rows": source_rows if source_rows is not None else read_rows,
             "deduplicated_rows": deduplicated_rows,
             "scope": "SSE" if api == "trade_cal" else
                      ("selected indexes" if selector else "Shanghai/Shenzhen A shares")}
    _json_write(stats_path, stats)
    print(f"{api}: {read_rows:,} read, {deduplicated_rows:,} retained", flush=True)
    return stats


def _build_basic(connection, out):
    return _copy(connection,
        "SELECT d.date, d.code, b.total_mv, b.circ_mv, b.pe_ttm, b.pb, "
        "b.dv_ttm, b.turnover_rate_f "
        f"FROM read_parquet({_literal(out / 'daily.parquet')}) d "
        "LEFT JOIN daily_basic b USING (code, date) ORDER BY d.code, d.date",
        out / "basic.parquet")


def build(out, start, only=None, *, manifest_path=None, cache_dir=None, end=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE
    if manifest_path is None:
        release_id = json.loads((source / "RESEARCH_CURRENT.json").read_text())["release_id"]
        manifest_path = source / "releases" / release_id / "manifest.json"
    else:
        manifest_path = Path(manifest_path).resolve()
        source = manifest_path.parents[2]
        release_id = manifest_path.parent.name
    cache = Path(cache_dir or "data/cache") / release_id
    cache.mkdir(parents=True, exist_ok=True)
    paths_file = cache / "source_paths.json"
    if paths_file.exists():
        paths = json.loads(paths_file.read_text())
    if not paths_file.exists() or any(api not in paths for api in APIS):
        print(f"Reading manifest for {release_id}", flush=True)
        manifest = json.loads(manifest_path.read_text())
        paths = {api: [] for api in APIS}
        for dataset in manifest["datasets"]:
            if dataset["api_name"] in paths:
                paths[dataset["api_name"]].append(str(source / dataset["path"]))
        del manifest
        _json_write(paths_file, paths)

    connection = duckdb.connect()
    connection.execute("SET threads = 4")
    connection.execute("SET memory_limit = '2GB'")
    connection.execute(f"SET temp_directory = {_literal(cache / 'spill')}")
    if only == "basic" and (out / "daily.parquet").exists():
        _cache_api(connection, "daily_basic", paths["daily_basic"], cache)
        connection.execute("CREATE VIEW daily_basic AS SELECT * FROM read_parquet("
                           f"{_literal(cache / 'daily_basic.parquet')})")
        connection.execute("CREATE OR REPLACE TEMP TABLE raw AS SELECT 1 AS unused")
        rows = _build_basic(connection, out)
        connection.close()
        print(f"Built {out / 'basic.parquet'}: {rows:,} rows", flush=True)
        return
    stats = {}
    for api in APIS:
        stats[api] = _cache_api(connection, api, paths[api], cache)
        connection.execute(f"CREATE OR REPLACE VIEW {api} AS "
                           f"SELECT * FROM read_parquet({_literal(cache / (api + '.parquet'))})")
    # Release the last raw staging table before constructing the panel.
    connection.execute("CREATE OR REPLACE TEMP TABLE raw AS SELECT 1 AS unused")
    max_date = connection.execute("SELECT max(date) FROM daily").fetchone()[0]
    if end is not None:
        max_date = min(max_date, date.fromisoformat(str(end)))
    rows = {}
    rows["stocks.parquet"] = _copy(connection, "SELECT * FROM stock_basic ORDER BY code", out / "stocks.parquet")
    rows["calendar.parquet"] = _copy(connection,
        f"SELECT DISTINCT date FROM trade_cal WHERE exchange = 'SSE' AND is_open = 1 "
        f"AND date BETWEEN DATE {_literal(start)} AND DATE {_literal(max_date)} ORDER BY date",
        out / "calendar.parquet")
    connection.execute(f"CREATE VIEW calendar AS SELECT * FROM read_parquet({_literal(out / 'calendar.parquet')})")
    rows["index_members.parquet"] = _copy(connection,
        f"SELECT index_code, snapshot_date, code, weight FROM index_weight "
        f"WHERE snapshot_date <= DATE {_literal(max_date)} ORDER BY index_code, snapshot_date, code",
        out / "index_members.parquet")
    rows["index_daily.parquet"] = _copy(connection,
        f"SELECT * FROM index_daily WHERE date BETWEEN DATE {_literal(start)} "
        f"AND DATE {_literal(max_date)} ORDER BY index_code, date", out / "index_daily.parquet")
    rows["industry.parquet"] = _copy(connection,
        "SELECT * FROM index_member_all ORDER BY code, in_date", out / "industry.parquet")

    parts = []
    for year in range(start.year, max_date.year + 1):
        lower, upper = max(start, date(year, 1, 1)), min(max_date, date(year, 12, 31))
        if lower > upper:
            continue
        bounds = f"date BETWEEN DATE {_literal(lower)} AND DATE {_literal(upper)}"
        print(f"Building daily {year}", flush=True)
        # One seed per code carries factors across year boundaries and --start.
        connection.execute(f"CREATE OR REPLACE TEMP TABLE adj_seed AS "
            f"SELECT code, adj FROM adj_factor WHERE date < DATE {_literal(lower)} AND adj IS NOT NULL "
            "QUALIFY row_number() OVER (PARTITION BY code ORDER BY date DESC) = 1")
        query = f"""
            WITH keys AS (
                SELECT s.code, c.date FROM stock_basic s CROSS JOIN calendar c
                WHERE c.{bounds} AND s.list_date <= c.date
                    AND (s.delist_date IS NULL OR c.date < s.delist_date)
                UNION
                SELECT code, date FROM daily WHERE {bounds}
            ), joined AS (
                SELECT k.date, k.code, d.open, d.high, d.low, d.close, d.pre_close,
                    d.pct_chg, d.volume, d.amount,
                    coalesce(last_value(a.adj IGNORE NULLS) OVER (
                        PARTITION BY k.code ORDER BY k.date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ), seed.adj) AS adj,
                    l.up_limit, l.down_limit,
                    (d.code IS NULL OR coalesce(d.volume = 0, false)
                        OR coalesce(s.suspend_type = 'S' AND s.suspend_timing IS NULL, false)) AS suspended,
                    coalesce((regexp_matches(k.code, '^(60|000|001|002|003)')
                        OR (regexp_matches(k.code, '^(300|301)') AND k.date < DATE '2020-08-24'))
                        AND abs(l.up_limit / l.limit_pre_close - 1 - 0.05) < 0.006, false) AS is_st
                FROM keys k
                LEFT JOIN (SELECT * FROM daily WHERE {bounds}) d USING (code, date)
                LEFT JOIN (SELECT * FROM adj_factor WHERE {bounds}) a USING (code, date)
                LEFT JOIN adj_seed seed USING (code)
                LEFT JOIN (SELECT * FROM stk_limit WHERE {bounds}) l USING (code, date)
                LEFT JOIN (SELECT * FROM suspend_d WHERE {bounds}) s USING (code, date)
            ) SELECT * FROM joined ORDER BY code, date
        """
        part = cache / f"daily_{lower}_{upper}.parquet"
        _copy(connection, query, part)
        parts.append(str(part))
    relation = connection.read_parquet(parts, hive_partitioning=False)
    relation.create_view("panel_parts")
    rows["daily.parquet"] = _copy(connection, "SELECT * FROM panel_parts ORDER BY code, date", out / "daily.parquet")
    rows["basic.parquet"] = _build_basic(connection, out)
    _json_write(out / "build_meta.json", {
        "release_id": release_id, "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "start": start.isoformat(), "end": max_date.isoformat(), "files": rows, "apis": stats,
    })
    connection.close()
    print(f"Built {out}: {rows}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/panel")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2010, 1, 1))
    parser.add_argument("--only", choices=["basic"])
    args = parser.parse_args()
    build(args.out, args.start, args.only)


if __name__ == "__main__":
    main()
