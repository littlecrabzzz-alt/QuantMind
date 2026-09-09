"""Refine the frozen 155 conditional general-rate candidates, without runtime writes."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_intake import DocParser  # noqa: E402
from audit_tushare_rate_evidence import permission_evidence  # noqa: E402


class CategoryPaths(DocParser):
    """Preserve the official sidebar's ancestor IDs; labels alone are ambiguous."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.paths = {}

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if not self.sidebar_depth:
            return
        if tag == 'li':
            self.stack.append(None)
        if tag == 'a' and self.stack:
            match = re.fullmatch(r'/document/2\?doc_id=(\d+)', dict(attrs).get('href', ''))
            if match:
                self.stack[-1] = match[1]
                self.paths[match[1]] = [value for value in self.stack if value]

    def handle_endtag(self, tag):
        if tag == 'li' and self.sidebar_depth and self.stack:
            self.stack.pop()
        super().handle_endtag(tag)


def refine_one(api, row, path, lines):
    joined = ' '.join(lines)
    mentions = sorted({int(n) for n in re.findall(r'(\d+)\s*(?:个)?积分', joined)})
    mentions += [int(n) for n in re.findall(r'积分[^0-9\n]{0,8}(\d+)', joined)]
    mentions = sorted(set(mentions))
    result = {'api_name': api, 'source_doc_id': row['source_doc_id'],
              'official_category_path': path, 'mentioned_points': mentions,
              'rate_class': 'uncertain', 'rpm_at_10100': None,
              'rpm_after_2026_12_05_at_8100': None, 'reason': '',
              'requires_live_permission_and_existing_gates': True,
              'next_points_expiry': '2027-09-08'}
    if not path or not lines:
        result['reason'] = 'Missing category path or archived leaf points policy.'
    elif '291' in path:
        result.update(rate_class='special_300', rpm_at_10100=300,
                      reason='Official 290 links special category 291; this leaf is a descendant. Independent and explicit overrides were excluded before this refinement.',
                      next_points_expiry='2026-12-05')
    elif api in {'hk_basic', 'hk_tradecal', 'us_basic', 'us_tradecal'}:
        result['reason'] = 'Leaf has points-based access but 290 broadly excludes HK/US permissions from points. Do not resolve that scope conflict by choosing the higher rate.'
    elif not mentions or max(mentions) > 8100:
        result['reason'] = 'Leaf points condition cannot be certified to survive the declared 8100 balance; hm_detail explicitly requires 10000.'
    else:
        result.update(rate_class='regular_500', rpm_at_10100=500,
                      rpm_after_2026_12_05_at_8100=500,
                      reason='Documented points-based leaf outside category291; no independent/explicit override in the frozen candidate set, and all introductory points levels fit 8100. Apply general 5000-plus table conditionally.')
    return result


def build(baseline_path, category_path, archive_dir):
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    category_bytes = category_path.read_bytes()
    parser = CategoryPaths()
    parser.feed(category_bytes.decode('utf-8'))
    if parser.links.get('291') != '特色数据':
        raise ValueError('Expected official special category291 missing; review source instead of guessing')
    result = {}
    for api, row in baseline['apis'].items():
        if row['rate_class'] != 'points_general_candidate':
            continue
        path = archive_dir / (row['source_doc_id'] + '.html')
        body = path.read_bytes() if path.is_file() else None
        if body is not None and hashlib.sha256(body).hexdigest() != row['source_html_sha256']:
            raise ValueError(f'Archived source changed: {api}')
        lines = permission_evidence(body.decode()) if body else []
        item = refine_one(api, row, parser.paths.get(row['source_doc_id'], []), lines)
        item.update(source_html_sha256=row['source_html_sha256'],
                    source_url=row['source_url'],
                    category_labels=[parser.links.get(n) for n in item['official_category_path']],
                    source_policy_line_sha256=[hashlib.sha256(s.encode()).hexdigest() for s in lines])
        result[api] = item
    classes = ('regular_500', 'special_300', 'uncertain')
    return {'schema_version': 1, 'baseline_commit': '492c43b',
            'baseline_report_sha256': hashlib.sha256(baseline_bytes).hexdigest(),
            'official_category_url': 'https://tushare.pro/document/2?doc_id=290',
            'official_category_html_sha256': hashlib.sha256(category_bytes).hexdigest(),
            'counts': dict(sorted(Counter(r['rate_class'] for r in result.values()).items())),
            'api_sets': {kind: sorted(a for a, r in result.items() if r['rate_class'] == kind)
                         for kind in classes},
            'apis': result,
            'excluded_from_refinement': {a: r['rate_class'] for a, r in baseline['apis'].items()
                                         if r['rate_class'] != 'points_general_candidate'},
            'constraints': ['No runtime policy changed. Regular500 remains subject to live entitlement, account/API gates and observed cooldowns.',
                            'Only the frozen 155 candidates are refined; purchased, independent, explicit overrides and earlier unknowns are preserved.',
                            '8100 is conditional on the user-declared tranche dates and no other balance change. Expiry clock/timezone/renewal not inspected.',
                            'Special300 eligibility requires review when the 10000 tier ends; null at8100 means no rate authorization from this audit, not necessarily no supplier access.',
                            'Official category and leaf statements are dated evidence, not permanent API rights.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--category-html', type=Path, required=True)
    parser.add_argument('--archive-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.baseline, args.category_html, args.archive_dir)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['counts'], sort_keys=True))


if __name__ == '__main__':
    main()
