"""Prepare paper inputs from explicit real archive releases, never CURRENT or mtime."""
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path

import duckdb

from .data.build import build, _copy, _literal, _cache_api


def _etf_panel(manifest_path, out, cache, cutoff, *, source_root=None, dataset_refs=None):
    if dataset_refs is None:
        manifest = json.loads(manifest_path.read_text())
        dataset_refs = manifest["datasets"]
    source = Path(source_root) if source_root is not None else manifest_path.parents[2]
    paths = {api: [str(source / item["path"]) for item in dataset_refs
                   if item["api_name"] == api] for api in ("fund_daily", "fund_adj", "etf_limit", "fund_div")}
    with duckdb.connect() as con:
        con.execute("SET threads=4")
        con.execute("SET memory_limit='2GB'")
        con.execute(f"SET temp_directory={_literal(cache / 'etf-spill')}")
        for api, fields in (("fund_daily", "open, close, amount * 1000.0 AS amount, vol * 100.0 AS volume"),
                            ("fund_adj", "adj_factor AS adj"),
                            ("etf_limit", "up_limit, down_limit")):
            if not paths[api]:
                if api == "etf_limit":
                    con.execute("CREATE TEMP TABLE etf_limit(date DATE,code VARCHAR,up_limit DOUBLE,down_limit DOUBLE)")
                    continue
                raise ValueError(f"Explicit market release lacks {api}")
            for offset in range(0, len(paths[api]), 512):
                con.read_parquet(paths[api][offset:offset + 512], union_by_name=True,
                                 hive_partitioning=False).create_view("source_batch", replace=True)
                query = ("SELECT source_ts_code AS code, "
                    "try_strptime(cast(trade_date as varchar), '%Y%m%d')::DATE AS date, "
                    f"{fields}, _fetched_at::TIMESTAMPTZ AS fetched_at FROM source_batch "
                    "WHERE source_ts_code IN ('510300.SH','511010.SH','518880.SH')")
                if offset == 0:
                    con.execute(f"CREATE OR REPLACE TEMP TABLE raw AS {query}")
                else:
                    con.execute(f"INSERT INTO raw {query}")
            con.execute(f"CREATE OR REPLACE TEMP TABLE {api} AS SELECT * EXCLUDE(fetched_at) "
                "FROM raw WHERE date IS NOT NULL QUALIFY row_number() OVER "
                "(PARTITION BY date,code ORDER BY fetched_at DESC NULLS LAST)=1")
        con.execute("CREATE TEMP TABLE cash_events(date DATE,code VARCHAR)")
        for offset in range(0, len(paths["fund_div"]), 512):
            con.read_parquet(paths["fund_div"][offset:offset + 512], union_by_name=True,
                             hive_partitioning=False).create_view("dividend_batch", replace=True)
            con.execute("INSERT INTO cash_events SELECT DISTINCT "
                "try_strptime(cast(ex_date as varchar),'%Y%m%d')::DATE,source_ts_code "
                "FROM dividend_batch WHERE source_ts_code IN ('510300.SH','511010.SH','518880.SH') "
                "AND ex_date IS NOT NULL")
        # Actual available source limits only. I7's frozen calendar rule does not
        # assume a stock limit; S1 refuses absent ETF limits rather than inventing one.
        _copy(con, "SELECT d.*, a.adj, l.up_limit, l.down_limit, "
            "(e.code IS NOT NULL) AS cash_dividend_event "
            "FROM fund_daily d LEFT JOIN fund_adj a USING(date,code) "
            "LEFT JOIN etf_limit l USING(date,code) "
            "LEFT JOIN (SELECT DISTINCT date,code FROM cash_events) e USING(date,code) "
            f"WHERE d.date <= DATE {_literal(cutoff)} ORDER BY d.code,d.date", out)
    return {"cash_dividend_source_available": bool(paths["fund_div"]),
            "cash_dividend_history_verified": False,
            "cash_dividend_note": "Only observed fund_div ex_date events; false does not prove no historical cash dividend"}


def prepare_release(market_manifest, fundamental_manifest, directory, cutoff,
                    replay_start="2026-10-14", cb=None, futures=None, *,
                    calendar_path=None, calendar_sha256=None, readiness_identity=None,
                    account_assets=None):
    """Build real panels once, freeze all consumed bytes, resume an interrupted build."""
    from .data.fundamentals import build_fundamentals
    from .paper_runtime import file_hash, json_bytes, load_inputs, _publish, ledger_lock
    market_manifest = Path(market_manifest).resolve(strict=True)
    fundamental_manifest = Path(fundamental_manifest).resolve(strict=True)
    cutoff = date.fromisoformat(cutoff)
    directory = Path(directory).resolve()
    if calendar_path is not None:
        calendar_path = Path(calendar_path).resolve(strict=True)
        if not calendar_sha256 or file_hash(calendar_path) != calendar_sha256:
            raise ValueError("Approved readiness calendar hash mismatch")
    expected = {"market_manifest": str(market_manifest),
                "market_sha256": file_hash(market_manifest),
                "fundamental_manifest": str(fundamental_manifest),
                "fundamental_sha256": file_hash(fundamental_manifest),
                "usable_date": str(cutoff), "replay_start": replay_start,
                "cb": str(Path(cb).resolve()) if cb is not None else None,
                "futures": str(Path(futures).resolve()) if futures is not None else None,
                "calendar_path": str(calendar_path) if calendar_path is not None else None,
                "calendar_sha256": calendar_sha256, "readiness_identity": readiness_identity,
                "account_assets": ({name: str(Path(path).resolve()) for name, path in account_assets.items()}
                                   if account_assets is not None else None)}
    manifest_out = directory / "inputs.json"
    with ledger_lock(directory):
        if manifest_out.exists():
            saved = load_inputs(manifest_out)
            if saved["archive_identity"] != expected:
                raise ValueError("Prepared directory belongs to a different frozen release/cutoff")
            return manifest_out
        identity_path = directory / "archive_identity.json"
        if identity_path.exists() and json.loads(identity_path.read_text()) != expected:
            raise ValueError("Interrupted preparation belongs to another release; use another output directory")
        if not identity_path.exists():
            _publish({identity_path: json_bytes(expected)})
        cache = directory / "cache"
        panel, fundamental = directory / "panel", directory / "fundamentals"
        build(panel, date(2024, 1, 1), manifest_path=market_manifest, cache_dir=cache, end=cutoff)
        actual_end = json.loads((panel / "build_meta.json").read_text())["end"]
        if actual_end != str(cutoff):
            raise ValueError(f"Market archive only builds through {actual_end}, not approved {cutoff}")
        build_fundamentals(fundamental, manifest_path=fundamental_manifest,
                           cache_dir=cache / "fundamentals")
        calendar = cache / market_manifest.parent.name / "trade_cal.parquet"
        if calendar_path is not None:
            calendar = calendar_path
        else:
            # Research slices may stop at the data day; use the explicit full
            # release's real SSE calendar, never synthetic weekdays.
            full_manifest = json.loads(fundamental_manifest.read_text())
            calendar_paths = [str(fundamental_manifest.parents[2] / item["path"])
                              for item in full_manifest["datasets"] if item["api_name"] == "trade_cal"]
            del full_manifest
            if calendar_paths:
                calendar_cache = cache / "full-calendar" / fundamental_manifest.parent.name
                calendar_cache.mkdir(parents=True, exist_ok=True)
                with duckdb.connect() as connection:
                    connection.execute("SET threads=4")
                    connection.execute("SET memory_limit='2GB'")
                    _cache_api(connection, "trade_cal", calendar_paths, calendar_cache)
                calendar = calendar_cache / "trade_cal.parquet"
        from .paper_assets import exchange_days
        days = exchange_days(calendar, "SSE", cutoff)
        if str(cutoff) not in set(str(t.date()) for t in days):
            raise ValueError("Approved cutoff is not in the explicit exchange calendar")
        spec = {"version": market_manifest.parent.name + ":" + fundamental_manifest.parent.name,
                "usable_date": str(cutoff), "replay_start": replay_start,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "panel": str(panel), "fundamentals": str(fundamental), "calendar": str(calendar),
                "archive_identity": expected, "input_errors": {}, "files": {}, "asset_inputs": {}}
        if account_assets is not None:
            spec["asset_inputs"] = {name: str(Path(path).resolve()) for name, path in account_assets.items()}
        else:
            etf = directory / "etf.parquet"
            try:
                _etf_panel(market_manifest, etf, cache, cutoff)
                for name in ("i7_turn_of_month", "s1_invvol_etf"):
                    spec["asset_inputs"][name] = str(etf)
            except (ValueError, duckdb.Error) as exc:
                for name in ("i7_turn_of_month", "s1_invvol_etf"):
                    spec["input_errors"][name] = str(exc)
            for names, value in ((("cb_double_low",), cb), (("cta_combined", "cta_trend"), futures)):
                for name in names:
                    if value is not None and Path(value).is_dir():
                        spec["asset_inputs"][name] = str(Path(value).resolve())
                    else:
                        spec["input_errors"][name] = f"No real {name} input; no synthetic ledger created"
        sources = {name: spec[name] for name in ("panel", "fundamentals", "calendar")}
        sources.update(spec["asset_inputs"])
        for name, value in sources.items():
            path = Path(value)
            files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
            for file in files:
                spec["files"][str(file.resolve())] = file_hash(file)
            if name in ("panel", "fundamentals", "calendar"):
                spec[name] = os.path.relpath(path, directory)
            else:
                spec["asset_inputs"][name] = os.path.relpath(path, directory)
        spec["files"][str(identity_path)] = file_hash(identity_path)
        spec["files"] = {os.path.relpath(path, directory): value
                         for path, value in spec["files"].items()}
        _publish({manifest_out: json_bytes(spec)})
    return manifest_out
