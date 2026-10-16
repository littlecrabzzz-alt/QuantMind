"""CSI 800 cash-dividend total return benchmark and aligned alpha/beta."""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .data.build import SOURCE, _copy, _date, _index_files, _json_write, _literal
from .metrics import cagr


def dividend_contribution(calendar, snapshots, close, adj, dividends):
    """Drift closing snapshot weights using returns excluding cash dividends."""
    calendar = pd.DatetimeIndex(calendar)
    result = pd.DataFrame(np.nan, index=calendar,
                          columns=["recon_price_ret", "div_contrib"])
    if calendar.empty:
        return result
    snapshots = snapshots.copy()
    snapshots["snapshot_date"] = pd.to_datetime(snapshots.snapshot_date)
    snapshots = snapshots[snapshots.snapshot_date <= calendar[-1]]
    codes = pd.Index(sorted(snapshots.code.unique()))
    # Include any supplied pre-calendar observations for the initial drift.
    dates = calendar.union(pd.DatetimeIndex(close.index)).union(
        pd.DatetimeIndex(adj.index)).union(
        pd.DatetimeIndex(snapshots.snapshot_date.unique())).sort_values()
    dates = dates[dates <= calendar[-1]]
    prices = close.reindex(index=dates, columns=codes).ffill()
    adjusted = prices * adj.reindex(index=dates, columns=codes).ffill()
    ratio = (adjusted / adjusted.shift()).fillna(1).to_numpy()
    cash = dividends.copy()
    cash["ex_date"] = pd.to_datetime(cash.ex_date)
    cash = cash.groupby(["ex_date", "code"]).cash_div_tax.sum().unstack()
    cash = cash.reindex(index=dates, columns=codes).fillna(0).to_numpy()
    previous = prices.shift().to_numpy()
    yields = np.divide(cash, previous, out=np.zeros_like(cash, dtype=float),
                       where=np.isfinite(previous) & (previous > 0))
    growth = ratio - yields
    resets = {date: group.set_index("code").weight.reindex(codes).fillna(0).to_numpy(float)
              for date, group in snapshots.groupby("snapshot_date")}
    weights = np.zeros(len(codes), dtype=float)
    output_rows = calendar.get_indexer(dates)
    for i, date in enumerate(dates):
        known = weights.sum() > 0
        row = output_rows[i]
        if known:
            if row > 0 and np.any((weights > 0) & (cash[i] != 0) &
                      (~np.isfinite(previous[i]) | (previous[i] <= 0))):
                raise ValueError(f"Missing previous price for dividend on {date}")
            if row > 0:
                result.iloc[row] = [weights @ growth[i] - 1, weights @ yields[i]]
            weights *= growth[i]
            weights /= weights.sum()
        if date in resets:
            weights = resets[date].copy()
            total = weights.sum()
            if total <= 0 or np.any(weights < 0):
                raise ValueError(f"Invalid snapshot weights on {date}")
            weights /= total
    result.iloc[0, 1] = 0.0
    return result


def total_return_close(price_close, div_contrib):
    """Compound official price returns plus cash dividend contributions."""
    if price_close.empty:
        return price_close.copy()
    growth = 1 + price_close.pct_change(fill_method=None) + div_contrib.reindex(
        price_close.index).fillna(0)
    growth.iloc[0] = 1
    return price_close.iloc[0] * growth.cumprod(skipna=False)


def load_benchmarks(path="data/benchmarks"):
    """Load price and total return closes, indexed by trading date."""
    frame = pd.read_parquet(Path(path) / "csi800_tr.parquet")
    frame["date"] = pd.to_datetime(frame.date)
    return frame.set_index("date")[["price_close", "tr_close"]].rename(
        columns={"price_close": "000906.SH", "tr_close": "000906.SH_TR"})


def alpha_beta(nav, bench_close):
    """OLS on simple returns computed after aligning available closing dates."""
    aligned = pd.concat([nav.rename("nav"), bench_close.rename("bench")],
                        axis=1, join="inner").dropna().sort_index()
    returns = aligned.pct_change(fill_method=None).dropna()
    keys = ["alpha_ann", "beta", "excess_cagr", "tracking_error", "info_ratio", "corr"]
    values = dict.fromkeys(keys, float("nan"))
    values["excess_cagr"] = cagr(aligned.nav) - cagr(aligned.bench)
    if returns.empty:
        return values
    excess = returns.nav - returns.bench
    error = float(excess.std(ddof=1) * np.sqrt(252))
    values["tracking_error"] = error
    values["info_ratio"] = float(excess.mean() * 252 / error) if error > 0 else float("nan")
    if len(returns) > 1 and returns.bench.var(ddof=1) > 0:
        beta = float(returns.nav.cov(returns.bench) / returns.bench.var(ddof=1))
        values.update(beta=beta, alpha_ann=float(
            (returns.nav.mean() - beta * returns.bench.mean()) * 252))
        if returns.nav.std(ddof=1) > 0:
            values["corr"] = float(returns.nav.corr(returns.bench))
    return values


def benchmark_table(nav, benchmarks):
    """Compute the same metrics for each benchmark in column order."""
    return pd.DataFrame.from_dict(
        {name: alpha_beta(nav, benchmarks[name]) for name in benchmarks}, orient="index")


def _source_paths(cache, release_id):
    path = cache / "benchmark_source_paths.json"
    if path.exists():
        return json.loads(path.read_text())
    print(f"Reading CURRENT manifest for {release_id}", flush=True)
    manifest = json.loads((SOURCE / "releases" / release_id / "manifest.json").read_text())
    paths = {api: [] for api in ("dividend", "index_daily")}
    for dataset in manifest["datasets"]:
        if dataset["api_name"] in paths:
            paths[dataset["api_name"]].append(str(SOURCE / dataset["path"]))
    _json_write(path, paths)
    return paths


def _read_batches(connection, paths, select):
    if not paths:
        raise ValueError("No source files found")
    for offset in range(0, len(paths), 1024):
        connection.read_parquet(paths[offset:offset + 1024], union_by_name=True,
                                hive_partitioning=False).create_view("source_batch", replace=True)
        command = "CREATE OR REPLACE TEMP TABLE raw AS" if offset == 0 else "INSERT INTO raw"
        connection.execute(f"{command} {select}")


def build(panel, out):
    """Build from the read-only panel and CURRENT release; publish atomically."""
    panel, out = Path(panel), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    release_id = json.loads((SOURCE / "CURRENT.json").read_text())["release_id"]
    cache = Path("data/cache") / release_id
    cache.mkdir(parents=True, exist_ok=True)
    paths = _source_paths(cache, release_id)
    with duckdb.connect() as connection:
        connection.execute("SET threads = 4")
        connection.execute("SET memory_limit = '2GB'")
        connection.execute(f"SET temp_directory = {_literal(cache / 'benchmark_spill')}")
        dividend_path = cache / "benchmark_dividends.parquet"
        if not dividend_path.exists():
            print(f"Reading {len(paths['dividend'])} dividend files", flush=True)
            _read_batches(connection, paths["dividend"],
                f"SELECT source_ts_code AS code, {_date('end_date')} AS end_date, "
                f"{_date('ex_date')} AS ex_date, cash_div_tax, "
                "_fetched_at::TIMESTAMPTZ AS fetched_at FROM source_batch "
                "WHERE trim(div_proc) = '实施' AND ex_date IS NOT NULL "
                "AND trim(cast(ex_date AS varchar)) <> ''")
            _copy(connection,
                "WITH latest AS (SELECT * FROM raw QUALIFY row_number() OVER ("
                "PARTITION BY code, end_date, ex_date ORDER BY fetched_at DESC NULLS LAST) = 1) "
                "SELECT code, ex_date, sum(cash_div_tax) AS cash_div_tax FROM latest "
                "WHERE ex_date IS NOT NULL GROUP BY code, ex_date ORDER BY code, ex_date",
                dividend_path)
        official_path = cache / "benchmark_h00906.parquet"
        if not official_path.exists():
            selected = _index_files(paths["index_daily"], "source_ts_code", ("H00906.CSI",),
                                    cache / "benchmark_h00906_files.json")["paths"]
            if selected:
                print(f"Reading {len(selected)} H00906 candidate files", flush=True)
                _read_batches(connection, selected,
                    f"SELECT {_date('trade_date')} AS date, close, "
                    "_fetched_at::TIMESTAMPTZ AS fetched_at FROM source_batch "
                    "WHERE source_ts_code = 'H00906.CSI'")
                _copy(connection, "SELECT date, close FROM raw QUALIFY row_number() OVER ("
                      "PARTITION BY date ORDER BY fetched_at DESC NULLS LAST) = 1 ORDER BY date",
                      official_path)
            else:
                _copy(connection, "SELECT NULL::DATE AS date, NULL::DOUBLE AS close WHERE false",
                      official_path)
        calendar = pd.DatetimeIndex(pd.read_parquet(panel / "calendar.parquet").date)
        snapshots = connection.execute(
            f"SELECT snapshot_date, code, weight FROM read_parquet({_literal(panel / 'index_members.parquet')}) "
            "WHERE index_code = '000906.SH'").df()
        connection.register("benchmark_codes", snapshots[["code"]].drop_duplicates())
        print("Reading CSI 800 close and adjustment panel", flush=True)
        daily = connection.execute(
            f"SELECT date, code, close, adj FROM read_parquet({_literal(panel / 'daily.parquet')}) "
            "SEMI JOIN benchmark_codes USING (code)").df()
        close = daily.pivot(index="date", columns="code", values="close")
        adj = daily.pivot(index="date", columns="code", values="adj")
        del daily
        dividends = pd.read_parquet(dividend_path)
        contributions = dividend_contribution(calendar, snapshots, close, adj, dividends)
        price = connection.execute(
            f"SELECT date, close FROM read_parquet({_literal(panel / 'index_daily.parquet')}) "
            "WHERE index_code = '000906.SH'").df().set_index("date").close.reindex(calendar)
        if price.isna().any():
            raise ValueError("Official CSI 800 price close missing on panel calendar")
        official = pd.read_parquet(official_path).set_index("date").close
        official.index = pd.DatetimeIndex(official.index)
        frame = contributions.assign(price_close=price,
            tr_close=total_return_close(price, contributions.div_contrib),
            official_tr_close=official.reindex(calendar))
        frame.index.name = "date"
        frame = frame.reset_index()[["date", "price_close", "recon_price_ret", "div_contrib",
                                     "tr_close", "official_tr_close"]]
        connection.register("benchmark_output", frame)
        rows = _copy(connection, "SELECT date::DATE AS date, * EXCLUDE(date) FROM benchmark_output",
                     out / "csi800_tr.parquet")
        print(f"Built {out / 'csi800_tr.parquet'}: {rows:,} rows", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", default="data/panel")
    parser.add_argument("--out", default="data/benchmarks")
    args = parser.parse_args()
    build(args.panel, args.out)


if __name__ == "__main__":
    main()
