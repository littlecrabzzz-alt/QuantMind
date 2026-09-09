"""Single-point input preparation preserves missingness and cannot grant PIT readiness."""

from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

import importlib.util

from prepare_tushare_rrg_stock_point import point_inputs, positive, prepare, skeleton, unique


SCIENTIFIC = bool(importlib.util.find_spec("numpy") and importlib.util.find_spec("pandas"))


def fixture():
    days, calendar = [], []
    start = datetime(2024, 1, 1)
    for n in range(336):
        day = start + timedelta(days=n)
        opened = day.weekday() < 5
        calendar.append({'exchange': 'SSE', 'cal_date': day.strftime('%Y%m%d'), 'is_open': int(opened)})
        if opened:
            days.append(day.strftime('%Y%m%d'))
    days = days[:240]
    return days, calendar


class StockPointTests(unittest.TestCase):
    def setUp(self):
        self.days, self.calendar = fixture()
        self.daily = [{'trade_date': day, 'ts_code': 'SHT600018', 'close': 10 if day in self.days[:20] else 12, '_observation': day}
                      for day in self.days[:20] + self.days[-20:]]
        self.adj = [{**r, 'adj_factor': 1} for r in self.daily]
        self.basic = [{**r, 'free_share': 100, 'float_share': 200, 'circ_mv': 2000} for r in self.daily[-20:]]

        def flags(frame, lookback):
            self.assertEqual(lookback, 220)
            self.assertEqual(len(frame), 240)
            self.assertTrue(frame.iloc[20:220].isna().all().all())
            lag = frame.shift(lookback)
            return (frame > lag).astype(float).where(frame.notna() & lag.notna())
        self.author = SimpleNamespace(_up_flags=flags)

    def test_calendar_skeleton_uses_sessions_and_requires_closed_days(self):
        self.assertEqual(skeleton(self.calendar, self.days[-1]), self.days)
        without_weekend = [r for r in self.calendar if r['is_open'] == 1]
        with self.assertRaisesRegex(ValueError, 'natural-day'):
            skeleton(without_weekend, self.days[-1])
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            skeleton(self.calendar + [{**self.calendar[0], 'is_open': 0}], self.days[-1])

    @unittest.skipUnless(SCIENTIFIC, "Scientific dependencies required; run documented offline uv environment")
    def test_exact_pairs_keep_stock_identity_and_200_unneeded_rows_missing(self):
        rows, invalid, missing, stats = point_inputs(self.days, self.daily, self.adj, self.basic, self.author)
        self.assertEqual(stats['valid_comparisons'], 20)
        self.assertEqual(stats['all20_valid_codes'], 1)
        self.assertEqual({r['ts_code'] for r in rows}, {'SHT600018'})
        self.assertFalse(stats['membership_known_at_verified'])
        self.assertFalse(stats['industry_aggregation_performed'])
        self.assertEqual((invalid, missing), ([], []))
        self.assertNotIn('known_at', rows[0])

    @unittest.skipUnless(SCIENTIFIC, "Scientific dependencies required; run documented offline uv environment")
    def test_missing_or_invalid_factor_keeps_null_without_filling(self):
        adjusted = self.adj[1:]
        rows, invalid, missing, stats = point_inputs(self.days, self.daily, adjusted, self.basic, self.author)
        self.assertEqual(stats['valid_comparisons'], 19)
        self.assertIsNone(rows[0]['up_flag'])
        self.assertEqual(len(invalid), 1)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['missing_price_dates'], [])  # Price exists; factor is the problem.
        self.assertEqual(len(rows), 20)

    @unittest.skipUnless(SCIENTIFIC, "Scientific dependencies required; run documented offline uv environment")
    def test_duplicate_and_whole_date_missing_refuse_acceptance(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            unique(self.daily + self.daily[:1])
        with self.assertRaisesRegex(ValueError, 'entire endpoint'):
            point_inputs(self.days, self.daily[1:], self.adj, self.basic, self.author)
        for value in (None, True, float('nan'), float('inf'), 0, -1):
            self.assertFalse(positive(value))

    @unittest.skipUnless(SCIENTIFIC, "Scientific dependencies required; run documented offline uv environment")
    def test_missing_capitalization_is_not_invented_or_claimed_ready(self):
        rows, _, _, stats = point_inputs(self.days, self.daily, self.adj, [], self.author)
        self.assertEqual(stats['valid_comparisons'], 20)
        self.assertEqual(stats['capitalization_fields_present_comparisons'], 0)
        self.assertIsNone(rows[0]['free_share'])

    @unittest.skipUnless(SCIENTIFIC, "Scientific dependencies required; run documented offline uv environment")
    def test_protected_output_and_real_cli_author_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'Output must be new'):
                prepare(root, 'CURRENT', self.days[-1], root / 'author.py', root / 'output')
            author = root / 'author.py'
            author.write_text('raise RuntimeError("must never execute")')
            outside = root.parent / (root.name + '-output')
            command = [sys.executable, str(Path(__file__).with_name('prepare_tushare_rrg_stock_point.py')),
                       '--root', str(root), '--release-id', 'data-' + 'a' * 64,
                       '--target-date', self.days[-1], '--author', str(author), '--output', str(outside)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('fingerprint mismatch', result.stderr)
            self.assertNotIn('RuntimeError: must never execute', result.stderr)
            self.assertFalse(outside.exists())


if __name__ == '__main__':
    unittest.main()
