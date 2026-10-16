"""Classify announcement titles and build the read-only release's event library."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .build import SOURCE, A_SHARE, _copy, _date, _json_write, _literal


PREFIX = r"^[^:：]{0,12}[:：]"
RECENT_YEARS = re.compile(r"最近[0-9０-９零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬億]+年")
GLOBAL_EXCLUDE = ("法律意见", "核查意见", "专项核查", "独立财务顾问", "律师",
                  "保荐机构", "受托管理", "中诚信", "评级", "会计师事务所", "审核问询")
INCREASE_OTHER_COMPANY = re.compile(r"增持[^，,。]*?(有限公司|股权)")
PENALTY = ("行政处罚", "处罚决定", "事先告知")
DISCIPLINE = ("纪律处分", "公开谴责", "通报批评")
WARNING = ("警示函", "监管函", "监管措施决定")
INQUIRY = ("问询函", "关注函")
COMPLETE = ("结果", "完成", "实施完毕", "届满", "期满")
PLAN_EXCLUDE = ("进展", "完成", "结果", "实施完毕", "届满", "期满", "过半")
APIS = ("anns_d", "forecast_vip", "repurchase", "stk_holdertrade")


def clean_title(title):
    """Remove one leading company prefix of at most twelve characters."""
    return re.sub(PREFIX, "", title) if isinstance(title, str) else ""


def _has(title, words):
    return any(word in title for word in words)


def _classify_cleaned(title):
    if _has(title, GLOBAL_EXCLUDE):
        return None, None
    if (_has(title, ("立案",) + PENALTY + DISCIPLINE + WARNING + INQUIRY)
            and not _has(title, ("未被", "不存在被"))
            and not RECENT_YEARS.search(title)):
        if "立案" in title:
            subtype = "investigation_progress" if "进展" in title else "investigation"
        elif _has(title, PENALTY):
            subtype = "penalty"
        elif _has(title, DISCIPLINE):
            subtype = "discipline"
        elif _has(title, WARNING):
            subtype = "warning"
        elif _has(title, INQUIRY):
            subtype = "inquiry_reply" if _has(title, ("回复", "回函")) else "inquiry"
        else:
            subtype = "other"
        return "regulatory", subtype
    if (("业绩预告" in title or ("公告" in title and _has(title, (
            "业绩预增", "业绩预减", "业绩预亏", "业绩预盈", "扭亏为盈", "预计扭亏", "业绩大幅"))))
            and not _has(title, ("业绩快报", "说明会", "业绩预告制度"))):
        return "earnings_forecast", "revision" if _has(title, ("修正", "更正", "补充")) else "initial"
    if ("回购" in title and _has(title, ("股份", "股票", "回购报告书", "回购方案"))
            and not _has(title, ("质押式回购", "回购注销", "注销", "限制性股票", "激励",
                                "债券", "逆回购", "业绩补偿", "补偿股份", "回购义务", "理财", "国债", "质押"))):
        if _has(title, ("终止", "取消")):
            subtype = "terminate"
        elif _has(title, ("方案", "预案", "回购报告书", "拟回购", "计划")):
            subtype = "plan"
        elif "首次" in title:
            subtype = "first"
        elif _has(title, COMPLETE):
            subtype = "complete"
        elif "进展" in title:
            subtype = "progress"
        else:
            subtype = "other"
        return "buyback", subtype
    for event_type, keyword, excluded, plan, progress in (
        ("insider_increase", "增持", ("不增持", "增持基金", "理财", "要约", "免于"), ("计划",), ("进展", "过半")),
        ("insider_decrease", "减持", ("不减持", "不存在减持", "减持承诺", "可转债", "可转换公司债"),
         ("计划", "预披露"), ("进展", "过半", "达到")),
    ):
        if keyword in title and not _has(title, excluded):
            if event_type == "insider_increase" and INCREASE_OTHER_COMPANY.search(title):
                continue
            if _has(title, ("终止", "取消")):
                subtype = "terminate"
            elif _has(title, plan) and not _has(title, PLAN_EXCLUDE):
                subtype = "plan"
            elif _has(title, COMPLETE):
                subtype = "complete"
            elif _has(title, progress):
                subtype = "progress"
            else:
                subtype = "other"
            return event_type, subtype
    return None, None


def classify_title(title):
    """Return the first event type/subtype specified in document 11."""
    return _classify_cleaned(clean_title(title))


def effective_dates(ann_dates, calendar):
    """Find the strictly next calendar date; unavailable dates become NaT."""
    dates = pd.to_datetime(ann_dates)
    cal = pd.DatetimeIndex(calendar).dropna().unique().sort_values()
    values = cal.to_numpy(dtype="datetime64[ns]")
    announcements = np.asarray(dates, dtype="datetime64[ns]")
    positions = np.searchsorted(values, announcements, side="right")
    result = np.full(len(announcements), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = (positions < len(values)) & ~np.isnat(announcements)
    result[valid] = values[positions[valid]]
    return pd.Series(result, index=getattr(ann_dates, "index", None), name="effective_date")


def _read_api(connection, api, paths):
    """Stage only required columns, bounding Parquet schema discovery by batch."""
    if not paths:
        raise ValueError(f"No source files for {api}")
    fields = {
        "anns_d": ["title::VARCHAR AS raw_title", "url::VARCHAR AS url"],
        "forecast_vip": [f"{_date('end_date')} AS fc_end_date", 'type::VARCHAR AS fc_type',
                         "try_cast(p_change_min AS DOUBLE) AS fc_p_change_min",
                         "try_cast(p_change_max AS DOUBLE) AS fc_p_change_max"],
        "repurchase": [],
        "stk_holdertrade": ["in_de::VARCHAR AS in_de"],
    }[api]
    for offset in range(0, len(paths), 256):
        relation = connection.read_parquet(paths[offset:offset + 256], union_by_name=True,
                                          hive_partitioning=False)
        relation.create_view("source_batch", replace=True)
        projection = ["source_ts_code::VARCHAR AS code", f"{_date('ann_date')} AS ann_date", *fields]
        if api in ("anns_d", "forecast_vip"):
            projection.append("try_cast(_fetched_at AS TIMESTAMPTZ) AS fetched_at")
        query = (f"SELECT {', '.join(projection)} FROM source_batch "
                 f"WHERE regexp_full_match(source_ts_code, {_literal(A_SHARE)})")
        if api == "anns_d":
            query += (" AND url IS NOT NULL AND title IS NOT NULL "
                      "QUALIFY row_number() OVER (PARTITION BY url "
                      "ORDER BY length(title), fetched_at DESC NULLS LAST, title, code, ann_date) = 1")
        elif api in ("repurchase", "stk_holdertrade"):
            query = f"SELECT DISTINCT * FROM ({query})"
        if offset == 0:
            connection.execute(f"CREATE TEMP TABLE raw AS {query}")
        else:
            connection.execute(f"INSERT INTO raw {query}")
        if api == "anns_d":
            # Recall uses every same-day source title, before URL deduplication.
            title_days = (
                "WITH cleaned AS (SELECT source_ts_code::VARCHAR AS code, "
                f"{_date('ann_date')} AS ann_date, "
                f"regexp_replace(title::VARCHAR, {_literal(PREFIX)}, '') AS title "
                "FROM source_batch WHERE title IS NOT NULL "
                f"AND regexp_full_match(source_ts_code, {_literal(A_SHARE)})) "
                "SELECT code, ann_date, bool_or(regexp_matches(title, "
                "'季度报告|年度报告|半年度报告|年报|招股|上市公告书|发行|异常波动|异动')) "
                "AS forecast_excluded, bool_or(contains(title, '回购') "
                "AND (contains(title, '股份') OR contains(title, '股票')) "
                "AND NOT regexp_matches(title, '限制性股票|激励|注销|补偿|质押式')) "
                "AS repurchase_candidate FROM cleaned GROUP BY code, ann_date"
            )
            if offset == 0:
                connection.execute(f"CREATE TEMP TABLE title_days AS {title_days}")
            else:
                connection.execute(f"INSERT INTO title_days {title_days}")
        print(f"{api}: {min(offset + 256, len(paths))}/{len(paths)} files", flush=True)


def build_events(panel="data/panel", out="data/events", source=SOURCE):
    """Build events and recall statistics from CURRENT without archive writes."""
    panel, out, source = Path(panel), Path(out), Path(source)
    release_id = json.loads((source / "CURRENT.json").read_text())["release_id"]
    cache = Path("data/cache/events") / release_id
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Reading manifest for {release_id}", flush=True)
    manifest = json.loads((source / "releases" / release_id / "manifest.json").read_text())
    paths = {api: [] for api in APIS}
    for dataset in manifest["datasets"]:
        if dataset["api_name"] in paths:
            paths[dataset["api_name"]].append(str(source / dataset["path"]))
    del manifest

    with duckdb.connect() as connection:
        connection.execute("SET threads = 4")
        connection.execute("SET memory_limit = '4GB'")
        connection.execute(f"SET temp_directory = {_literal(cache / 'spill')}")
        _read_api(connection, "anns_d", paths["anns_d"])
        connection.execute(
            "CREATE TEMP TABLE same_day_titles AS SELECT code, ann_date, "
            "bool_or(forecast_excluded) AS forecast_excluded, "
            "bool_or(repurchase_candidate) AS repurchase_candidate "
            "FROM title_days GROUP BY code, ann_date"
        )
        connection.execute("DROP TABLE title_days")
        query = (
            "SELECT code, ann_date, regexp_replace(raw_title, "
            f"{_literal(PREFIX)}, '') AS title, url FROM raw "
            "QUALIFY row_number() OVER (PARTITION BY url ORDER BY length(raw_title), "
            "fetched_at DESC NULLS LAST, raw_title, code, ann_date) = 1"
        )
        deduplicated_rows = _copy(connection, query, cache / "announcements.parquet")
        connection.execute("DROP TABLE raw")
        connection.execute(f"CREATE VIEW announcements AS SELECT * FROM read_parquet({_literal(cache / 'announcements.parquet')})")
        distinct_titles = _copy(connection, "SELECT DISTINCT title FROM announcements", cache / "titles.parquet")
        connection.execute("CREATE TEMP TABLE classified (title VARCHAR, event_type VARCHAR, subtype VARCHAR)")
        processed = 0
        for batch in pq.ParquetFile(cache / "titles.parquet").iter_batches(batch_size=50000):
            records = []
            for title in batch.column(0).to_pylist():
                event_type, subtype = _classify_cleaned(title)
                if event_type is not None:
                    records.append((title, event_type, subtype))
            if records:
                frame = pd.DataFrame(records, columns=["title", "event_type", "subtype"])
                connection.register("classified_batch", frame)
                connection.execute("INSERT INTO classified SELECT * FROM classified_batch")
                connection.unregister("classified_batch")
            processed += batch.num_rows
            print(f"Classified {processed:,}/{distinct_titles:,} distinct titles", flush=True)
        connection.execute(f"CREATE TEMP TABLE calendar AS SELECT DISTINCT date FROM read_parquet({_literal(panel / 'calendar.parquet')}) WHERE date IS NOT NULL")
        connection.execute(
            "CREATE TEMP TABLE dated_events AS SELECT a.*, c.event_type, c.subtype, "
            "cal.date AS effective_date FROM announcements a JOIN classified c USING (title) "
            "ASOF LEFT JOIN calendar cal ON a.ann_date < cal.date"
        )
        unavailable = connection.execute("SELECT count(*) FROM dated_events WHERE effective_date IS NULL").fetchone()[0]
        _read_api(connection, "forecast_vip", paths["forecast_vip"])
        connection.execute(
            "CREATE TEMP TABLE forecast AS SELECT * EXCLUDE (fetched_at) FROM raw "
            "QUALIFY row_number() OVER (PARTITION BY code, ann_date "
            "ORDER BY fc_end_date DESC NULLS LAST, fetched_at DESC NULLS LAST) = 1"
        )
        connection.execute("DROP TABLE raw")
        query = (
            "SELECT e.code, e.ann_date, e.effective_date, e.event_type, e.subtype, e.title, e.url, "
            "f.fc_type, f.fc_p_change_min, f.fc_p_change_max, f.fc_end_date "
            "FROM dated_events e LEFT JOIN forecast f ON e.code = f.code AND e.ann_date = f.ann_date "
            "AND e.event_type = 'earnings_forecast' WHERE e.effective_date IS NOT NULL "
            "ORDER BY e.effective_date, e.code, e.url"
        )
        rows = _copy(connection, query, out / "events.parquet")
        connection.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet({_literal(out / 'events.parquet')})")
        recall, recall_counts = {}, {}

        def measure(name, table, event_type, days, condition="TRUE"):
            total, matched = connection.execute(
                "WITH reference AS (SELECT DISTINCT code, ann_date FROM " + table +
                " WHERE ann_date BETWEEN DATE '2014-01-01' AND DATE '2025-12-31' "
                f"AND {condition}) SELECT count(*), count(*) FILTER (WHERE EXISTS ("
                "SELECT 1 FROM events e WHERE e.code = r.code "
                f"AND e.event_type = {_literal(event_type)} "
                f"AND e.ann_date BETWEEN r.ann_date - {days} AND r.ann_date + {days})) "
                "FROM reference r"
            ).fetchone()
            recall[name] = matched / total if total else None
            recall_counts[name] = {"total": total, "matched": matched}

        measure("forecast_vip_raw", "forecast", "earnings_forecast", 1)
        connection.execute(
            "CREATE TEMP VIEW forecast_reference AS SELECT f.code, f.ann_date "
            "FROM forecast f JOIN same_day_titles s USING (code, ann_date) "
            "WHERE NOT s.forecast_excluded"
        )
        measure("forecast_vip", "forecast_reference", "earnings_forecast", 1)
        coverage_total, coverage_matched = connection.execute(
            "SELECT count(*), count(s.code) FROM forecast f "
            "LEFT JOIN same_day_titles s USING (code, ann_date) "
            "WHERE f.ann_date BETWEEN DATE '2014-01-01' AND DATE '2025-12-31'"
        ).fetchone()
        coverage = {"forecast_vip": coverage_matched / coverage_total if coverage_total else None}
        _read_api(connection, "repurchase", paths["repurchase"])
        measure("repurchase_raw", "raw", "buyback", 1)
        connection.execute(
            "CREATE TEMP VIEW repurchase_reference AS SELECT r.code, r.ann_date "
            "FROM raw r JOIN same_day_titles s USING (code, ann_date) "
            "WHERE s.repurchase_candidate"
        )
        measure("repurchase", "repurchase_reference", "buyback", 1)
        connection.execute("DROP VIEW repurchase_reference")
        connection.execute("DROP TABLE raw")
        _read_api(connection, "stk_holdertrade", paths["stk_holdertrade"])
        measure("stk_holdertrade_in", "raw", "insider_increase", 3, "in_de = 'IN'")
        measure("stk_holdertrade_de", "raw", "insider_decrease", 3, "in_de = 'DE'")
        counts = {}
        for event_type, subtype, n in connection.execute(
                "SELECT event_type, subtype, count(*) FROM events GROUP BY event_type, subtype ORDER BY event_type, subtype").fetchall():
            counts.setdefault(event_type, {})[subtype] = n
        fill_rate = connection.execute(
            "SELECT count(fc_type)::DOUBLE / nullif(count(*), 0) FROM events WHERE event_type = 'earnings_forecast'"
        ).fetchone()[0]
    meta = {"release_id": release_id, "built_at": datetime.now(timezone.utc).isoformat(),
            "deduplicated_rows": deduplicated_rows, "distinct_titles": distinct_titles,
            "events_rows": rows, "event_type_counts": {k: sum(v.values()) for k, v in counts.items()},
            "event_subtype_counts": counts, "unavailable_effective_date_rows": unavailable,
            "recall": recall, "recall_counts": recall_counts, "coverage": coverage,
            "coverage_counts": {"forecast_vip": {"total": coverage_total, "matched": coverage_matched}},
            "fc_fill_rate": fill_rate}
    _json_write(out / "events_meta.json", meta)
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)
    return meta


def load_events(directory, start=None, end=None, event_types=None):
    """Load events with inclusive filters on their first usable trading date."""
    filters = []
    if start is not None:
        filters.append(("effective_date", ">=", pd.Timestamp(start).date()))
    if end is not None:
        filters.append(("effective_date", "<=", pd.Timestamp(end).date()))
    if event_types is not None:
        filters.append(("event_type", "in", [event_types] if isinstance(event_types, str) else list(event_types)))
    frame = pd.read_parquet(Path(directory) / "events.parquet", filters=filters or None)
    for column in ("ann_date", "effective_date", "fc_end_date"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", default="data/panel")
    parser.add_argument("--out", default="data/events")
    args = parser.parse_args()
    build_events(panel=args.panel, out=args.out)


if __name__ == "__main__":
    main()
