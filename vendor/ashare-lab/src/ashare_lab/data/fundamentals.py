"""Financial statement versions and announcement-date point-in-time queries."""

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .build import SOURCE, A_SHARE, _copy, _date, _json_write, _literal


FIELDS = {
    "income": ["total_revenue", "revenue", "oper_cost", "operate_profit",
               "total_profit", "income_tax", "n_income", "n_income_attr_p",
               "fin_exp", "rd_exp", "basic_eps"],
    "balance": ["total_assets", "total_liab", "total_hldr_eqy_exc_min_int",
                "total_cur_assets", "total_cur_liab", "money_cap", "inventories",
                "accounts_receiv", "goodwill", "total_share"],
    "cashflow": ["n_cashflow_act", "n_cashflow_inv_act", "c_pay_acq_const_fiolta",
                 "free_cashflow"],
}
APIS = {"income": "income_vip", "balance": "balancesheet_vip",
        "cashflow": "cashflow_vip"}
KEY_COLUMNS = ["code", "end_date", "report_type", "update_flag", "ann_date",
               "effective_date"]


def build_fundamentals(out, source=SOURCE, start=date(2008, 1, 1), *,
                       manifest_path=None, cache_dir=None):
    """Build deduplicated versions from an explicit release or legacy CURRENT."""
    source, out = Path(source), Path(out)
    start = pd.Timestamp(start).date()
    if manifest_path is None:
        release_id = json.loads((source / "CURRENT.json").read_text())["release_id"]
        manifest_path = source / "releases" / release_id / "manifest.json"
    else:
        manifest_path = Path(manifest_path).resolve()
        source = manifest_path.parents[2]
        release_id = manifest_path.parent.name
    print(f"Reading manifest for {release_id}", flush=True)
    manifest = json.loads(manifest_path.read_text())
    paths = {api: [] for api in APIS.values()}
    for dataset in manifest["datasets"]:
        if dataset["api_name"] in paths:
            paths[dataset["api_name"]].append(str(source / dataset["path"]))
    del manifest
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir or "data/cache/fundamentals") / release_id
    cache.mkdir(parents=True, exist_ok=True)
    stats, files = {}, {}
    with duckdb.connect() as connection:
        connection.execute("SET threads = 4")
        connection.execute("SET memory_limit = '4GB'")
        connection.execute(f"SET temp_directory = {_literal(cache / 'spill')}")
        for statement, api in APIS.items():
            if not paths[api]:
                raise ValueError(f"No source files for {api}")
            observed = set()
            for offset in range(0, len(paths[api]), 256):
                batch = paths[api][offset:offset + 256]
                relation = connection.read_parquet(batch, union_by_name=True,
                                                  hive_partitioning=False)
                columns = set(relation.columns)
                observed.update(columns)
                relation.create_view("source_batch", replace=True)

                def col(name):
                    return name if name in columns else "NULL"

                projection = [
                    f"{col('source_ts_code')}::VARCHAR AS code",
                    f"{_date(col('end_date'))} AS end_date",
                    f"try_cast({col('report_type')} AS INTEGER) AS report_type",
                    f"try_cast({col('update_flag')} AS INTEGER) AS update_flag",
                    f"{_date(col('ann_date'))} AS ann_date",
                    f"coalesce({_date(col('f_ann_date'))}, "
                    f"{_date(col('ann_date'))}) AS effective_date",
                    *[f"try_cast({col(field)} AS DOUBLE) AS {field}"
                      for field in FIELDS[statement]],
                    f"try_cast({col('_fetched_at')} AS TIMESTAMPTZ) AS fetched_at",
                ]
                query = f"SELECT {', '.join(projection)} FROM source_batch"
                if offset == 0:
                    connection.execute(f"CREATE OR REPLACE TEMP TABLE raw AS {query}")
                else:
                    connection.execute(f"INSERT INTO raw {query}")
                print(f"{api}: {min(offset + 256, len(paths[api]))}/{len(paths[api])} files",
                      flush=True)
            read_rows = connection.execute("SELECT count(*) FROM raw").fetchone()[0]
            query = (
                "SELECT * EXCLUDE (fetched_at) FROM raw "
                f"WHERE regexp_full_match(code, {_literal(A_SHARE)}) "
                f"AND end_date >= DATE {_literal(start)} "
                "AND report_type IN (1, 4, 5) AND effective_date IS NOT NULL "
                "QUALIFY row_number() OVER ("
                "PARTITION BY code, end_date, report_type, effective_date "
                "ORDER BY update_flag DESC NULLS LAST, fetched_at DESC NULLS LAST) = 1 "
                "ORDER BY code, end_date, effective_date, report_type"
            )
            filename = f"fin_{statement}.parquet"
            retained = _copy(connection, query, out / filename)
            files[filename] = retained
            stats[api] = {"source_files": len(paths[api]), "read_rows": read_rows,
                          "retained_rows": retained,
                          "missing_fields": sorted(set(FIELDS[statement]) - observed)}
            connection.execute("DROP TABLE raw")
            print(f"{api}: {read_rows:,} read, {retained:,} retained", flush=True)
    _json_write(out / "fin_meta.json", {
        "release_id": release_id, "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "start": start.isoformat(), "apis": stats, "files": files,
    })
    print(f"Built {out}: {files}", flush=True)


class Fundamentals:
    """Immutable query indexes over financial version tables.

    Same-day ties are resolved once. Each remaining row has a half-open
    announcement interval; filtering these intervals requires no per-query sort.
    Final versions are indexed separately for the deliberately naive control.
    """

    def __init__(self, tables):
        self._tables = {}
        self._bounds = {}
        self._final = {}
        for statement, fields in FIELDS.items():
            frame = tables.get(statement)
            if frame is None:
                frame = pd.DataFrame(columns=KEY_COLUMNS + fields)
            else:
                frame = frame.copy()
            for column in ("end_date", "effective_date"):
                frame[column] = pd.to_datetime(frame[column])
            for field in fields:
                if field not in frame:
                    frame[field] = np.nan
            frame = frame.dropna(subset=["code", "end_date", "effective_date"])
            frame = frame[frame.report_type.isin([1, 4, 5])].copy()
            frame["_priority"] = frame.report_type.map({4: 0, 1: 1, 5: 2})
            frame = frame.sort_values(
                ["code", "end_date", "effective_date", "_priority", "update_flag"],
                kind="stable", na_position="first",
            ).drop_duplicates(["code", "end_date", "effective_date"], keep="last")
            next_date = frame.groupby(["code", "end_date"], sort=False).effective_date.shift(-1)
            # Nanosecond units are explicit: input parquet dates may use ms/us.
            begin = frame.effective_date.to_numpy(dtype="datetime64[ns]")
            end = next_date.fillna(pd.Timestamp.max).to_numpy(dtype="datetime64[ns]")
            final = ~frame.duplicated(["code", "end_date"], keep="last").to_numpy()
            values = [c for c in frame.columns if c not in KEY_COLUMNS + ["_priority"]]
            result = frame.set_index(["code", "end_date"])[
                values + ["effective_date", "report_type"]
            ]
            self._tables[statement] = result
            self._bounds[statement] = (begin, end)
            self._final[statement] = result.iloc[np.flatnonzero(final)]

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        return cls({name: pd.read_parquet(directory / f"fin_{name}.parquet")
                    for name in FIELDS})

    def asof(self, statement, d, naive=False):
        """Return one visible version per (code, end_date)."""
        when = pd.Timestamp(d)
        if naive:
            frame = self._final[statement]
            return frame.loc[frame.index.get_level_values("end_date") <= when].copy()
        begin, end = self._bounds[statement]
        stamp = when.to_datetime64().astype("datetime64[ns]")
        return self._tables[statement].iloc[
            np.flatnonzero((begin <= stamp) & (stamp < end))
        ].copy()

    @staticmethod
    def _latest(snapshot):
        codes = snapshot.index.get_level_values("code")
        return snapshot.loc[~codes.duplicated(keep="last")].reset_index("end_date")

    def latest(self, statement, d, naive=False):
        """Return the greatest visible report period for each stock."""
        return self._latest(self.asof(statement, d, naive=naive))

    @staticmethod
    def _ttm(snapshot, latest, field):
        periods = pd.DatetimeIndex(latest.end_date)
        prior_year = periods.year - 1
        annual = pd.to_datetime(prior_year.astype(str) + "-12-31")
        prior_period = periods - pd.DateOffset(years=1)

        def lookup(dates):
            keys = pd.MultiIndex.from_arrays([latest.index, dates], names=["code", "end_date"])
            return snapshot[field].reindex(keys).to_numpy(dtype=float)

        current = latest[field].to_numpy(dtype=float)
        rolling = current + lookup(annual) - lookup(prior_period)
        values = np.where((periods.month == 12) & (periods.day == 31), current, rolling)
        return pd.Series(values, index=latest.index, name=field)

    def ttm(self, field, d, naive=False):
        """Compute cumulative E + previous FY - previous same period."""
        statements = [s for s in ("income", "cashflow") if field in self._tables[s].columns]
        if len(statements) != 1:
            raise ValueError(f"Expected a unique income/cashflow field: {field}")
        snapshot = self.asof(statements[0], d, naive=naive)
        return self._ttm(snapshot, self._latest(snapshot), field)

    def roe_ttm(self, d, naive=False):
        """TTM attributable income / positive equity at the same latest E."""
        snapshot = self.asof("income", d, naive=naive)
        income = self._latest(snapshot)
        earnings = self._ttm(snapshot, income, "n_income_attr_p")
        balance = self.latest("balance", d, naive=naive).reindex(income.index)
        equity = balance.total_hldr_eqy_exc_min_int
        equity = equity.where((equity > 0) & (balance.end_date == income.end_date))
        return (earnings / equity).rename("roe_ttm")

    def panel(self, method, dates, codes, naive=False):
        """Evaluate a named Series-returning method on the requested grid."""
        dates, codes = pd.DatetimeIndex(dates), pd.Index(codes)
        query = getattr(self, method)
        return pd.DataFrame([query(d, naive=naive).reindex(codes).to_numpy() for d in dates],
                            index=dates, columns=codes, dtype=float)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/fundamentals")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2008, 1, 1))
    args = parser.parse_args()
    build_fundamentals(args.out, start=args.start)


if __name__ == "__main__":
    main()
