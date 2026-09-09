"""Offline rate evidence inventory; outputs an audit, never runtime configuration."""

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_intake import DocParser  # noqa: E402
from backend.shared.tushare_pipeline import CONTRACTS  # noqa: E402
from backend.shared.tushare_registry import EXTENDED_CONTRACTS, contract_for  # noqa: E402

# User's dated purchase declaration, not a fresh account/credential inspection.
PURCHASED = dict.fromkeys(('news', 'major_news', 'cctv_news'), 400)
PURCHASED.update(dict.fromkeys(('anns_d', 'irm_qa_sh', 'irm_qa_sz', 'npr', 'research_report'), 500))
PURCHASED['monetary_policy'] = 200
SPECIAL = {'report_rc', 'cyq_perf', 'cyq_chips', 'broker_recommend'}
OVERRIDES = {
    'stock_basic': 50, 'daily': 500, 'ths_member': 200,
    'cyq_chips': 200,  # Ambiguous tier carry-forward vs general 300: audit conflict.
    'cb_factor_pro': 500, 'fund_factor_pro': 500, 'idx_factor_pro': 500,
    'stk_factor': 500, 'stk_factor_pro': 500, 'fund_portfolio': 500,
    'kpl_list': 500, 'limit_list_d': 500, 'limit_list_ths': 500,
    'limit_cpt_list': 500, 'limit_step': 500,
    'slb_len': 500, 'slb_sec': 500, 'slb_sec_detail': 500, 'slb_len_mm': 500,
}
# Only direct product/API mappings. No 500rpm inferred for every minute product.
INDEPENDENT_RPM = dict.fromkeys(('stk_mins', 'ft_mins', 'opt_mins', 'sw_mins'), 500)
INDEPENDENT_RPM.update(dict.fromkeys(('rt_k', 'rt_etf_k', 'rt_idx_k', 'rt_sw_k', 'rt_etf_sz_iopv'), 50))
INDEPENDENT_RPM.update(dict.fromkeys(('hk_income', 'hk_balancesheet', 'hk_cashflow', 'hk_fina_indicator',
                                    'us_income', 'us_balancesheet', 'us_cashflow', 'us_fina_indicator',
                                    'us_daily', 'us_daily_adj', 'cb_price_chg', 'stk_premarket'), 500))
INDEPENDENT_RPM['rt_fut_min'] = 500  # Exact doc340 header, not its adjacent daily API.
INDEPENDENT_UNKNOWN = {
    'factor_list', 'factor_value', 'yc_cb', 'hk_daily', 'hk_daily_adj', 'hk_adjfactor',
    'us_adjfactor', 'etf_mins', 'idx_mins', 'hk_mins', 'rt_idx_min', 'rt_idx_min_daily',
    'rt_fut_min_daily', 'stk_auction', 'stk_auction_o', 'stk_auction_c',
}


def permission_evidence(html):
    parser = DocParser()
    parser.feed(html)
    text = ''.join(parser.article)
    # Only introductory policy lines, not table values or later sample code.
    head = re.split(r'(?m)^\s*(?:输入参数|输入字段|接口用法|接口示例|代码示例)\s*$', text, maxsplit=1)[0]
    return [line.strip() for line in head.splitlines()
            if re.search(r'积分|权限|频次|每分钟|次/分钟', line)]


def classify(api, lines, as_of):
    joined = ' '.join(lines)
    result = {'rate_class': 'unknown', 'documented_rpm': None,
              'documented_daily_calls': None, 'unknowns': [],
              'entitlement': 'not_verified', 'purchase_valid_until_date': None,
              'official_rate_valid_until': None, 'runtime_change_authorized_by_audit': False,
              'points_evidence_recheck_on': '2026-12-05'}
    if api in PURCHASED:
        result.update(rate_class='purchased_special', documented_rpm=PURCHASED[api],
                      entitlement='user_reported_purchase', purchase_valid_until_date='2027-09-08')
        if as_of >= date(2027, 9, 8):
            result['unknowns'].append('Purchase expiry reached; exact expiry time or renewal not inspected.')
    elif api in INDEPENDENT_RPM or api in INDEPENDENT_UNKNOWN or re.search(r'单独.{0,5}权限|独立权限|与积分无关', joined):
        result.update(rate_class='independent_unverified', documented_rpm=INDEPENDENT_RPM.get(api))
        result['unknowns'].append('Independent entitlement, trial quota and expiry unverified; points do not grant it.')
    elif api in OVERRIDES and lines:
        result.update(rate_class='per_api_override', documented_rpm=OVERRIDES[api],
                      entitlement='conditional_on_documented_points_tier')
    elif api in SPECIAL and lines:
        result.update(rate_class='points_special', documented_rpm=300,
                      entitlement='conditional_on_10000_points_tier')
    elif '积分' in joined:
        result.update(rate_class='points_general_candidate', documented_rpm=500,
                      entitlement='conditional_on_leaf_threshold_and_general_tier')
        result['unknowns'].append('General-table candidate only; special-category applicability and live gates not certified.')
    else:
        result['unknowns'].append('No sufficient archived leaf rate/points policy; do not substitute 500.')
    result['rate_basis'] = ('leaf_override' if result['rate_class'] == 'per_api_override'
                            else '290_product_mapping' if api in PURCHASED or api in INDEPENDENT_RPM
                            else '290_conditional_points_table' if result['rate_class'].startswith('points_')
                            else 'unknown')
    if api == 'rt_fut_min':
        result['rate_basis'] = 'leaf_override_independent_entitlement'
    if api == 'cyq_chips':
        result['documented_daily_calls'] = 200000
        result['unknowns'].append('Leaf 200rpm stated alongside 5000 tier; 10000 daily quota rises but rpm unspecified. General special 300 conflicts; 200 is conservative, not verified 10100 entitlement.')
    elif api == 'cyq_perf':
        result['documented_daily_calls'] = 200000
    elif api == 'report_rc':
        result['unknowns'].append('Leaf says no daily total above 10000; general table distinguishes special total at 15000. Preserve discrepancy.')
    if api == 'factor_value':
        result['unknowns'].append('Doc490 gives 6000 rows/call and optional 5000-point trial, but no rpm or daily request quota. 6000 is not a frequency.')
    if api in {'factor_value', 'factor_list'}:
        assert result['documented_rpm'] is None
    if api in {'rt_fut_min_daily', 'rt_idx_min_daily'}:
        result['unknowns'].append('Adjacent daily API cannot inherit sibling minute header frequency without explicit evidence.')
    if result['documented_rpm'] is None:
        result['unknowns'].append('Official API rpm remains unknown.')
    result['unknowns'].append('Documentation is a dated observation, not a guaranteed validity period or current service quota.')
    return result


def build(archive_dir, current_dir, as_of):
    ledger = json.loads((ROOT / 'config/tushare-coverage-ledger.json').read_bytes())
    docs = {api: str(e['doc_id']) for e in ledger['entries'] + ledger['discovered_entries']
            for api in e.get('acquisition_api_names', e['api_names'])}
    docs.update(rt_idx_min_daily='420', rt_fut_min_daily='340')
    result = {}
    for api in sorted(set(CONTRACTS) | set(EXTENDED_CONTRACTS)):
        doc_id = docs.get(api)
        path = current_dir / f'{doc_id}.html'
        source_kind = 'current_public_document'
        if not path.is_file():
            path = archive_dir / f'{doc_id}.html'
            source_kind = 'previously_archived_official_document'
        body = path.read_bytes() if path.is_file() else None
        lines = permission_evidence(body.decode('utf-8')) if body else []
        row = classify(api, lines, as_of)
        spec = contract_for(api)
        row.update(api_name=api, source_doc_id=doc_id,
                   stored_permission_status=[e.get('permission_status')
                                             for e in ledger['entries'] + ledger['discovered_entries']
                                             if api in e.get('acquisition_api_names', e['api_names'])],
                   source_url=f'https://tushare.pro/document/2?doc_id={doc_id}',
                   source_kind=source_kind if body else 'archive_missing',
                   source_html_sha256=hashlib.sha256(body).hexdigest() if body else None,
                   source_path=str(path) if body else None,
                   policy_line_evidence=[{'sha256': hashlib.sha256(line.encode()).hexdigest(),
                                         'numbers': re.findall(r'[0-9]+', line)} for line in lines],
                   repository_contract_rpm=spec.get('requests_per_minute', 500),
                   repository_api_config_default_rpm=200,
                   repository_default_gate_rpm=min(200, spec.get('requests_per_minute', 500)),
                   live_config_rpm=None, live_permission_probe=None,
                   rate_evidence_doc_ids=[doc_id, '290'])
        if row['documented_rpm'] is not None:
            row['contract_exceeds_documented_candidate'] = row['repository_contract_rpm'] > row['documented_rpm']
        else:
            row['contract_exceeds_documented_candidate'] = None
        result[api] = row
    general = current_dir / '290.html'
    return {'schema_version': 1, 'baseline': '32fe472', 'as_of_date': as_of.isoformat(),
            'read_only_audit': True, 'apis': result,
            'counts': dict(sorted(Counter(r['rate_class'] for r in result.values()).items())),
            'registered_count': len(result),
            'source_policy_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'registry_sha256': hashlib.sha256((ROOT / 'backend/shared/tushare_registry.py').read_bytes()).hexdigest(),
            'general_document': {'url': 'https://tushare.pro/document/2?doc_id=290',
                                 'html_sha256': hashlib.sha256(general.read_bytes()).hexdigest(),
                                 'valid_until': None,
                                 'current_check_metadata': json.loads((current_dir / '290.meta.json').read_bytes())
                                 if (current_dir / '290.meta.json').is_file() else None},
            'account_points_evidence': {'basis': 'user declaration, not account inspection',
                                       'declared_points': 10100,
                                       'tranches': [{'points': 8000, 'expires_on': '2027-09-08'},
                                                    {'points': 2000, 'expires_on': '2026-12-05'},
                                                    {'points': 100, 'expires_on': None}],
                                       'expiry_time_timezone': 'not provided'},
            'general_table': {'regular_5000_plus_rpm': 500, 'special_10000_plus_rpm': 300,
                              'special_15000_total': 'no total limit; not 15000-point entitlement for this account'},
            'limits': ['This JSON is not a deployable rate policy; no runtime imports it.',
                       'No credential, authority config, queue, request or production read/write performed.',
                       'Explicit leaf frequency takes precedence in review; conflicts remain unknown, not silently maximized.',
                       'Per-account gate and API-specific cooldown/minimum interval remain separate; throughput is not API entitlement.',
                       'Points-tier figures above are conditional at the audit date; renewals and later service changes require revalidation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-dir', type=Path, required=True)
    parser.add_argument('--current-doc-dir', type=Path, required=True)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.archive_dir, args.current_doc_dir, args.as_of)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'registered_count': result['registered_count'], 'classes': result['counts']}))


if __name__ == '__main__':
    main()
