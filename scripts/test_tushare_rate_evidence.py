"""Official rate classification is evidence, never implicit configuration authority."""

from datetime import date
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from audit_tushare_rate_evidence import ROOT, classify, permission_evidence

TODAY = date(2026, 9, 9)


class RateEvidenceTests(unittest.TestCase):
    def test_purchased_text_permissions_and_expiry(self):
        for api, rpm in [('news', 400), ('anns_d', 500), ('monetary_policy', 200)]:
            row = classify(api, ['单独权限'], TODAY)
            self.assertEqual(row['rate_class'], 'purchased_special')
            self.assertEqual(row['documented_rpm'], rpm)
            self.assertEqual(row['purchase_valid_until_date'], '2027-09-08')
            self.assertEqual(row['entitlement'], 'user_reported_purchase')
            self.assertFalse(row['runtime_change_authorized_by_audit'])
        expired = classify('news', [], date(2027, 9, 8))
        self.assertTrue(any('expiry reached' in s for s in expired['unknowns']))

    def test_factor_value_rows_and_trial_never_become_rpm(self):
        row = classify('factor_value', ['限量6000条', '单独权限5000积分可试用'], TODAY)
        self.assertEqual(row['rate_class'], 'independent_unverified')
        self.assertIsNone(row['documented_rpm'])
        self.assertIsNone(row['documented_daily_calls'])
        self.assertTrue(any('6000 is not' in s for s in row['unknowns']))

    def test_exact_override_and_feature_conflicts_survive(self):
        for api, rpm in [('stock_basic', 50), ('ths_member', 200), ('stk_factor_pro', 500)]:
            row = classify(api, ['积分及频次'], TODAY)
            self.assertEqual(row['rate_class'], 'per_api_override')
            self.assertEqual(row['documented_rpm'], rpm)
        chips = classify('cyq_chips', ['5000积分每分钟200次'], TODAY)
        self.assertEqual(chips['documented_rpm'], 200)
        self.assertEqual(chips['documented_daily_calls'], 200000)
        self.assertTrue(any('conflicts' in s for s in chips['unknowns']))

    def test_adjacent_and_trial_entitlements_do_not_inherit(self):
        for api in ('rt_fut_min_daily', 'rt_idx_min_daily', 'hk_mins', 'etf_mins'):
            row = classify(api, ['权限请参考权限说明'], TODAY)
            self.assertEqual(row['rate_class'], 'independent_unverified')
            self.assertIsNone(row['documented_rpm'])
        self.assertEqual(classify('rt_fut_min', ['每分钟500次'], TODAY)['documented_rpm'], 500)

    def test_general_candidate_is_not_account_permission(self):
        row = classify('example', ['用户需要5000积分'], TODAY)
        self.assertEqual(row['rate_class'], 'points_general_candidate')
        self.assertIn('conditional', row['entitlement'])
        self.assertIsNone(row['official_rate_valid_until'])
        self.assertEqual(classify('missing', [], TODAY)['rate_class'], 'unknown')
        self.assertIsNone(classify('stock_basic', [], TODAY)['documented_rpm'])

    def test_policy_parser_does_not_cut_inline_input_reference(self):
        html = '<div class="col-md-9"><p>描述：建议输入参数里选择日期</p>\n<p>积分：2000积分</p>\n<p>输入参数</p>\n<p>字段值：伪造每分钟9000次</p></div>'
        self.assertEqual(permission_evidence(html), ['积分：2000积分'])

    def test_offline_cli_real_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / '290.html').write_text('<div class="col-md-9">频次表</div>')
            (folder / '490.html').write_text('<div class="col-md-9">权限：单独权限，5000积分可试用</div>')
            output = folder / 'audit.json'
            command = [sys.executable, str(ROOT / 'scripts/audit_tushare_rate_evidence.py'),
                       '--archive-dir', tmp, '--current-doc-dir', tmp, '--as-of', '2026-09-09',
                       '--output', str(output)]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(output.read_bytes())
            self.assertEqual(result['registered_count'], 244)
            self.assertIn('fina_mainbz_vip', result['apis'])
            self.assertIsNone(result['apis']['factor_value']['documented_rpm'])
            self.assertTrue(result['read_only_audit'])

    def test_classifier_never_calls_network(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('no network')):
            self.assertEqual(classify('factor_value', [], TODAY)['rate_class'], 'independent_unverified')


if __name__ == '__main__':
    unittest.main()
