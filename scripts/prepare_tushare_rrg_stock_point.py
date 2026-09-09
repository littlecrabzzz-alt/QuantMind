#!/usr/bin/env python3
"""Prepare one fixed-release RRG stock-input point; never promote a research case."""

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timedelta
import hashlib
import json
import math
import re
from pathlib import Path
import socket
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared.tushare_pipeline import manifest_at  # noqa: E402
from backend.shared.tushare_store import read_dataset  # noqa: E402

GAPS = [
    'Historical CITIC classification and member known_at/publication revisions remain unverified; in_date and fetched_at are not substitutes.',
    'Missing stock endpoints remain explicit; no fill, membership exclusion or industry denominator has been authorized.',
    'free_share units/definition and adjustment revisions require semantic review before weighted industry aggregation.',
    'ETF historical universe, disclosed exposure, corporate actions and executable prices are not certified by this stock-input point.',
    '240 stock-calendar positions are not the 319 industry observations required for full RRG coordinates.',
]


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def skeleton(calendar, target):
    by_day = {}
    for row in calendar:
        if row['exchange'] != 'SSE':
            continue
        day, flag = row['cal_date'], str(row['is_open'])
        if not isinstance(day, str) or not re.fullmatch(r'[0-9]{8}', day):
            raise ValueError('Invalid calendar date')
        datetime.strptime(day, '%Y%m%d')
        if flag not in ('0', '1') or (day in by_day and by_day[day] != flag):
            raise ValueError('Invalid/conflicting SSE calendar')
        by_day[day] = flag
    days = sorted(day for day, flag in by_day.items() if flag == '1' and day <= target)
    if len(days) < 240 or days[-1] != target:
        raise ValueError('Target must be an observed open day with 240 sessions')
    days = days[-240:]
    lo, hi = (datetime.strptime(day, '%Y%m%d') for day in (days[0], target))
    natural = {(lo + timedelta(days=n)).strftime('%Y%m%d') for n in range((hi - lo).days + 1)}
    if natural - by_day.keys():
        raise ValueError('Missing natural-day calendar evidence')
    return days


def unique(rows):
    result = {}
    for row in rows:
        key = (row['trade_date'], row['ts_code'])
        if key in result:
            raise ValueError('Duplicate stock date/code after fixed-reader semantics')
        result[key] = row
    return result


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def point_inputs(days, daily, adjustments, basic, author):
    import numpy as np
    import pandas as pd

    prices, factors, caps = unique(daily), unique(adjustments), unique(basic)
    codes = sorted({code for _, code in prices})
    if not codes:
        raise ValueError('No source stock prices in requested endpoints')
    current, lag = days[-20:], days[:20]
    endpoint_days = set(current + lag)
    if any(day not in endpoint_days for day, _ in prices) or any(day not in endpoint_days for day, _ in factors):
        raise ValueError('Unexpected date outside exact endpoint windows')
    missing_dates = endpoint_days - {day for day, _ in prices}
    if missing_dates:
        raise ValueError('Missing entire endpoint dates: ' + ','.join(sorted(missing_dates)))
    frame = pd.DataFrame(np.nan, index=pd.to_datetime(days), columns=codes)
    invalid = []
    for key, row in prices.items():
        factor = factors.get(key, {}).get('adj_factor')
        value = row.get('close')
        if not positive(value) or not positive(factor) or not math.isfinite(value * factor):
            invalid.append({'trade_date': key[0], 'ts_code': key[1], 'reason': 'missing_or_invalid_close_or_adjustment'})
            continue
        frame.at[pd.Timestamp(key[0]), key[1]] = value * factor
    # The previously accepted author code is hash-checked by load_author.
    flags = author._up_flags(frame, 220).iloc[-20:]
    output, missing = [], []
    for index, day in enumerate(current):
        for code in codes:
            value = flags.at[pd.Timestamp(day), code]
            row, cap = prices.get((day, code)), caps.get((day, code))
            valid = bool(pd.notna(value))
            free_share = cap.get('free_share') if cap else None
            item = {'trade_date': day, 'lag220_date': lag[index], 'ts_code': code,
                    'up_flag': float(value) if valid else None,
                    'close': row.get('close') if row else None,
                    'free_share': free_share,
                    'float_share': cap.get('float_share') if cap else None,
                    'circ_mv': cap.get('circ_mv') if cap else None,
                    'daily_observation': row.get('_observation') if row else None,
                    'daily_basic_observation': cap.get('_observation') if cap else None,
                    'capitalization_fields_present': bool(cap and all(positive(cap.get(k)) for k in ('free_share', 'float_share', 'circ_mv')))}
            output.append(item)
            if not valid:
                missing.append({'ts_code': code, 'current_date': day, 'lag220_date': lag[index],
                                'missing_price_dates': [d for d in (day, lag[index]) if (d, code) not in prices],
                                'reason': 'unclassified_missing_comparison_not_assumed_transport_gap'})
    return output, invalid, missing, {
        'valid_comparisons': int(flags.notna().sum().sum()),
        'last_day_valid': int(flags.iloc[-1].notna().sum()),
        'all20_valid_codes': int(flags.notna().all().sum()),
        'observed_price_codes': len(codes), 'invalid_price_factor_pairs': len(invalid),
        'capitalization_fields_present_comparisons': sum(x['capitalization_fields_present'] for x in output),
        'industry_aggregation_performed': False, 'membership_known_at_verified': False,
    }


def prepare(root, release_id, target, author_path, output):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from verify_tushare_rrg_coordinates import load_author, AUTHOR_SHA256

    root, output, author_path = Path(root).resolve(), Path(output).resolve(), Path(author_path).resolve()
    if (output.exists()
            or any(output == p or p in output.parents for p in (root, REPO, author_path.parent))
            or any((parent / '.git').exists() for parent in (output, *output.parents))):
        raise ValueError('Output must be new and outside source/data trees')
    if not re.fullmatch(r'[0-9]{8}', target):
        raise ValueError('Target date must be exact YYYYMMDD')
    target_day = datetime.strptime(target, '%Y%m%d')
    author = load_author(author_path)
    manifest = manifest_at(root, release_id)
    queries = []

    def read(api, **params):
        table = read_dataset(root, release_id, api, **params)
        if len(table) >= params['limit']:
            raise ValueError(api + ' reached explicit query cap; no truncated acceptance')
        metadata = json.loads(table.schema.metadata[b'tushare'])
        if metadata['release_id'] != release_id or metadata['upstream_calls'] != 0:
            raise ValueError('Unexpected fixed-reader provenance')
        queries.append({'api_name': api, 'params': params, 'rows': len(table), 'metadata': metadata})
        return table

    calendar = read('trade_cal', date_field='cal_date', start_date=(target_day - timedelta(days=900)).strftime('%Y%m%d'), end_date=target, limit=2000)
    days = skeleton(calendar.to_pylist(), target)
    current, lag = days[-20:], days[:20]
    data = {}
    # Two narrow windows replace the former full-year stock-table query.
    for api in ('daily', 'adj_factor', 'daily_basic'):
        rows = []
        for window in ([lag, current] if api != 'daily_basic' else [current]):
            table = read(api, start_date=window[0], end_date=window[-1], limit=200000)
            rows.extend(r for r in table.to_pylist() if r['trade_date'] in set(window))
        data[api] = rows
    members = read('ci_index_member', limit=50000)
    industry = read('ci_daily', start_date=target, end_date=target, limit=100)
    flags, invalid, missing, stats = point_inputs(days, data['daily'], data['adj_factor'], data['daily_basic'], author)
    l1 = {r['l1_code'] for r in members.to_pylist()}
    industry_codes = {r['ts_code'] for r in industry.to_pylist()}
    report = {
        'status': 'blocked_data', 'input_status': 'stock_comparison_inputs_prepared',
        'release_id': release_id, 'target_date': target, 'upstream_calls': 0,
        'author_sha256': AUTHOR_SHA256, 'script_sha256': sha(__file__),
        'calendar': {'sessions': len(days), 'start': days[0], 'end': days[-1], 'current_20': current, 'lag220_20': lag},
        'stock_input': stats, 'queries': queries, 'gaps': GAPS,
        'members': {'rows': len(members), 'known_at_column_present': 'known_at' in members.column_names,
                    'known_at_verified': False, 'missing_price_l1_codes': sorted(l1 - industry_codes),
                    'price_codes_without_l1': sorted(industry_codes - l1)},
        'fixed_observation_partitions': dict(Counter(x['api_name'] for x in manifest['datasets'] if x['api_name'] in ('ci_daily','ci_index_member','etf_basic','etf_index','fund_daily','fund_adj','fund_portfolio','etf_sh_cons','etf_sz_cons'))),
        'partition_count_semantics': 'Physical published observations, not unique dates, full-history coverage or ETF readiness',
        'case_state_changed': False, 'industry_ranking_performed': False, 'returns_calculated': False,
    }
    output.mkdir(parents=True, exist_ok=False)
    for api, rows in data.items():
        pq.write_table(pa.Table.from_pylist(rows), output / (api + '-endpoints.parquet'))
    pq.write_table(calendar, output / 'calendar-source.parquet')
    pq.write_table(members, output / 'members-source.parquet')
    pq.write_table(industry, output / 'industry-point-source.parquet')
    pq.write_table(pa.Table.from_pylist(flags), output / 'stock-comparison-inputs.parquet')
    for name, payload in [('report', report), ('invalid-price-factor-pairs', invalid), ('missing-comparisons', missing)]:
        (output / (name + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    inventory = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in output.iterdir() if p.is_file()}
    (output / 'manifest.json').write_text(json.dumps({'release_id': release_id, 'status': 'blocked_data', 'files': inventory}, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--target-date', required=True)
    parser.add_argument('--author', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with ExitStack() as stack:
        for target in ('socket.socket.connect', 'socket.getaddrinfo', 'backend.shared.runtime_secrets.get_secret', 'sqlite3.connect'):
            stack.enter_context(patch(target, side_effect=AssertionError('Offline stock-input preparation')))
        report = prepare(args.root, args.release_id, args.target_date, args.author, args.output)
    print(json.dumps({'output': str(args.output), 'status': report['status'], 'stock_input': report['stock_input']}))


if __name__ == '__main__':
    main()
