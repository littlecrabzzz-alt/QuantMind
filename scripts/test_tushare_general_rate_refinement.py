"""Explicit allowlist partition, official ancestry and points-expiry boundaries."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from refine_tushare_general_rates import CategoryPaths, ROOT, build, refine_one


class GeneralRateRefinementTests(unittest.TestCase):
    def test_official_nested_categories_do_not_leak_to_siblings(self):
        parser = CategoryPaths()
        parser.feed('<div id="jstree"><ul><li><a href="/document/2?doc_id=14">股票</a><ul>'
                    '<li><a href="/document/2?doc_id=291">特色数据</a><ul><li><a href="/document/2?doc_id=364">九转</a></li></ul></li>'
                    '<li><a href="/document/2?doc_id=25">常规</a></li></ul></li></ul></div>')
        self.assertEqual(parser.paths['364'], ['14', '291', '364'])
        self.assertEqual(parser.paths['25'], ['14', '25'])

    def test_regular_points_survive_8100_but_no_blanket_permission(self):
        row = refine_one('adj_factor', {'source_doc_id': '28'}, ['15', '28'], ['2000积分起，5000积分频次高'])
        self.assertEqual(row['rpm_at_10100'], 500)
        self.assertEqual(row['rpm_after_2026_12_05_at_8100'], 500)
        self.assertTrue(row['requires_live_permission_and_existing_gates'])

    def test_special_and_unknown_do_not_keep_500_after_points_expire(self):
        special = refine_one('stk_nineturn', {'source_doc_id': '364'}, ['291', '364'], ['6000积分'])
        self.assertEqual(special['rate_class'], 'special_300')
        self.assertEqual(special['rpm_at_10100'], 300)
        self.assertIsNone(special['rpm_after_2026_12_05_at_8100'])
        for api in ('hk_basic', 'hk_tradecal', 'us_basic', 'us_tradecal'):
            row = refine_one(api, {'source_doc_id': '1'}, ['1'], ['5000积分'])
            self.assertEqual(row['rate_class'], 'uncertain')
        row = refine_one('hm_detail', {'source_doc_id': '312'}, ['312'], ['10000积分'])
        self.assertEqual(row['rate_class'], 'uncertain')

    def test_missing_leaf_category_or_threshold_never_defaults_to_500(self):
        for path, lines in [([], ['2000积分']), (['1'], []), (['1'], ['权限未知'])]:
            row = refine_one('new_api', {'source_doc_id': '1'}, path, lines)
            self.assertIsNone(row['rpm_at_10100'])

    def test_exact_frozen_partition_no_omission_or_new_scope(self):
        baseline = json.loads((ROOT / 'docs/tushare-rate-evidence-32fe472.json').read_bytes())
        refined = json.loads((ROOT / 'docs/tushare-general-rate-refinement.json').read_bytes())
        expected = {a for a, r in baseline['apis'].items() if r['rate_class'] == 'points_general_candidate'}
        self.assertEqual(set(refined['apis']), expected)
        self.assertEqual(refined['counts'], {'regular_500': 147, 'special_300': 3, 'uncertain': 5})
        flattened = [a for names in refined['api_sets'].values() for a in names]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), expected)
        self.assertEqual(set(refined['excluded_from_refinement']), set(baseline['apis']) - expected)
        self.assertNotIn('factor_value', refined['apis'])
        self.assertEqual(refined['baseline_report_sha256'], hashlib.sha256((ROOT / 'docs/tushare-rate-evidence-32fe472.json').read_bytes()).hexdigest())

    def test_cli_and_tampered_archive_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = '<div class="col-md-9">积分：5000积分</div>'
            (root / '1.html').write_text(body)
            (root / '290.html').write_text('<div id="jstree"><ul><li><a href="/document/2?doc_id=291">特色数据</a></li><li><a href="/document/2?doc_id=1">基础数据</a></li></ul></div>')
            baseline = {'apis': {'test_api': {'rate_class': 'points_general_candidate', 'source_doc_id': '1', 'source_html_sha256': hashlib.sha256(body.encode()).hexdigest(), 'source_url': 'https://tushare.pro/document/2?doc_id=1'}}}
            (root / 'baseline.json').write_text(json.dumps(baseline))
            cmd = [sys.executable, str(ROOT / 'scripts/refine_tushare_general_rates.py'), '--baseline', str(root / 'baseline.json'), '--category-html', str(root / '290.html'), '--archive-dir', tmp, '--output', str(root / 'output.json')]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / 'output.json').read_bytes())['api_sets']['regular_500'], ['test_api'])
            (root / '1.html').write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'Archived source changed'):
                build(root / 'baseline.json', root / '290.html', root)


if __name__ == '__main__':
    unittest.main()
