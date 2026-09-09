"""Offline automatic member scope; preserve the existing interleaved planner."""
from datetime import date
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import (
    APPEND_PLANNERS, PLANNERS, iter_market_member_jobs,
    market_member_prerequisites, contract_for,
)
import test_tushare_market_sentiment_pipeline as fixtures

OLD = ['tdx_index', 'tdx_daily', 'kpl_list', 'ths_hot', 'dc_hot']
TODAY = date(2026, 9, 9)
IDS = {'tdx_indices': ['880206.TDX'], 'kpl_concepts': ['000366.KP']}


def configuration(**updates):
    return {
        'enable_market_sentiment': True, 'market_sentiment_apis': OLD,
        'market_sentiment_history_start': '20260830',
        'enable_market_members': True, 'market_members_history_start': '20260830',
        'plan_jobs_per_tick': 1000, 'history_plan_seconds': 5,
        **updates,
    }


class MemberScope(unittest.TestCase):
    setUp = fixtures.MarketSentimentRuntime.setUp
    capture = fixtures.MarketSentimentRuntime.capture

    def plan(self, config=None, ids=None, today=TODAY):
        with patch.object(self.p, 'identifiers', return_value=IDS if ids is None else ids):
            return self.p.plan_extended(configuration() if config is None else config, today)

    def states(self, family):
        return [tuple(r) for r in self.p.db.execute(
            'SELECT * FROM planning_state WHERE name IN (?,?) ORDER BY name',
            ('recent:' + family, 'history:' + family))]

    def jobs(self, api):
        return self.p.db.execute(
            "SELECT * FROM jobs WHERE json_extract(job,'$.api_name')=? ORDER BY id", (api,)
        ).fetchall()

    def test_default_disabled_and_old_policy_exactly_unchanged(self):
        old = configuration(enable_market_members=False, plan_jobs_per_tick=10)
        before = module._planning_inputs('market_sentiment', old, IDS)
        self.plan(old)
        state = self.states('market_sentiment')
        oldjobs = [tuple(r) for r in self.p.db.execute('SELECT * FROM jobs ORDER BY id')]
        before_gates = list(self.p.db.execute('SELECT * FROM request_gates'))
        # Isolate alias enumeration: normal old progress is tested separately below.
        with patch.dict(module.PLANNERS, {}, clear=True):
            self.plan(configuration(plan_jobs_per_tick=10))
        self.assertEqual(state, self.states('market_sentiment'))
        self.assertEqual(before, module._planning_inputs('market_sentiment', configuration(), IDS))
        for r in oldjobs:
            self.assertEqual(tuple(self.p.db.execute('SELECT * FROM jobs WHERE id=?', (r[0],)).fetchone()), r)
        self.assertEqual(before_gates, list(self.p.db.execute('SELECT * FROM request_gates')))
        self.assertNotIn('market_members', PLANNERS)
        self.assertIn('market_members', APPEND_PLANNERS)
        self.assertTrue(self.jobs('tdx_member'))

    def test_disabled_reject_overlap_and_missing_group_without_state(self):
        self.plan(configuration(enable_market_members=False))
        self.assertFalse(self.states('market_members'))
        for changed in ({'enable_market_sentiment': False},
                        {'market_sentiment_apis': OLD + ['tdx_member']},
                        {'market_members_apis': ['tdx_daily']}):
            self.plan(configuration(**changed))
            self.assertFalse(self.states('market_members'))
            self.assertEqual(self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:market_members'"
            ).fetchone()[0], 'validation_blocked')

    def test_old_live_stream_progress_equals_control(self):
        control = module.Pipeline(self.root / 'control', self.p.catalog)
        self.addCleanup(control.close)
        for _ in range(4):
            with patch.object(control, 'identifiers', return_value=IDS):
                control.plan_extended(configuration(enable_market_members=False, plan_jobs_per_tick=17), TODAY)
            self.plan(configuration(plan_jobs_per_tick=17))
        self.assertEqual(self.states('market_sentiment'), [tuple(r) for r in control.db.execute(
            "SELECT * FROM planning_state WHERE name IN ('recent:market_sentiment','history:market_sentiment') ORDER BY name"
        )])
        for row in control.db.execute('SELECT * FROM jobs'):
            self.assertEqual(tuple(row), tuple(self.p.db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone()))

    def test_recent_history_resume_new_sources_and_rolling_dates(self):
        cfg = configuration(plan_jobs_per_tick=2)
        self.plan(cfg)
        frozen = self.p.db.execute("SELECT * FROM planning_state WHERE name='history:market_members'").fetchone()
        expanded = {'tdx_indices': IDS['tdx_indices'] + ['880207.TDX'], 'kpl_concepts': IDS['kpl_concepts']}
        self.plan(cfg, expanded)
        current = self.p.db.execute("SELECT * FROM planning_state WHERE name='history:market_members'").fetchone()
        self.assertEqual(frozen['signature'], current['signature'])
        self.assertGreaterEqual(current['offset'], frozen['offset'])
        for _ in range(45):
            self.plan(cfg, expanded)
        expected = list(iter_market_member_jobs(cfg, TODAY, expanded))
        for job in expected:
            self.assertTrue(any(json.loads(r['job'])['params'] == job['params'] and r['epoch'] == job['epoch']
                                for r in self.jobs(job['api_name'])))
        self.plan(configuration(), expanded, date(2026, 9, 10))
        self.assertTrue(any(json.loads(r['job'])['params']['trade_date'] == '20260910' for r in self.jobs('tdx_member')))
        for row in self.jobs('tdx_member') + self.jobs('kpl_concept_cons'):
            job = json.loads(row['job'])
            self.assertEqual(set(job['fields'].split(',')), set(contract_for(job['api_name'])['requested_fields']))
            self.assertEqual(row['group_name'], 'market_sentiment')

    def test_legacy_observations_saturation_children_and_universe_stay(self):
        row, job, result = self.capture('tdx_member', {'trade_date': '20260904'},
            [fixtures.source('tdx_member', ts_code='880206.TDX')], more=True, epoch='history')
        old = tuple(self.p.db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())
        attempts = [tuple(r) for r in self.p.db.execute('SELECT * FROM attempts')]
        with patch.object(self.p, 'identifiers', return_value=IDS):
            split = self.p.split_request(row, job, result)
        self.assertFalse(split['universe_complete'])
        self.plan()
        self.assertEqual(old, tuple(self.p.db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone()))
        self.assertEqual(attempts, [tuple(r) for r in self.p.db.execute('SELECT * FROM attempts')])
        expanded = {'tdx_indices': ['880206.TDX', '880207.TDX'], 'kpl_concepts': []}
        with patch.object(self.p, 'identifiers', return_value=expanded):
            second = self.p.split_request(row, job, result)
        self.assertEqual(second['children'], 2)
        self.assertFalse(second['universe_complete'])
        self.assertEqual(self.p.db.execute('SELECT coverage_proven FROM partition_splits WHERE parent_id=?', (row['id'],)).fetchone()[0], 0)
        child = dict(job, params={**job['params'], 'ts_code': '880206.TDX'})
        childrow = self.p.db.execute('SELECT * FROM jobs WHERE id=?', (self.p.enqueue('tdx_member', child['params']),)).fetchone()
        self.assertIsNone(self.p.split_request(childrow, child, result))

    def test_permission_and_account_api_gates_unchanged(self):
        self.p.db.execute("INSERT INTO capability VALUES('tdx_member:','permission_denied','fixture','fixture')")
        self.p.db.execute("INSERT INTO request_gates VALUES('account',?)", (time.time() + 600,))
        self.p.db.execute("INSERT INTO request_gates VALUES('api:kpl_concept_cons',?)", (time.time() + 600,))
        self.p.db.commit()
        gates = [tuple(r) for r in self.p.db.execute('SELECT * FROM request_gates')]
        self.plan()
        self.assertEqual({r['state'] for r in self.jobs('tdx_member')}, {'permission_blocked'})
        self.assertIsNone(self.p.next_job(configuration(requests_per_minute=240), time.monotonic() + .01))
        self.assertEqual(gates, [tuple(r) for r in self.p.db.execute('SELECT * FROM request_gates')])

    def test_existing_worker_consumes_alias_with_original_group_share(self):
        self.plan(configuration(market_sentiment_apis=[]))
        cfg = configuration(market_sentiment_apis=[], requests_per_minute=500)
        with patch.object(self.p, '_next_family_job', wraps=self.p._next_family_job) as choose:
            selected = self.p.next_job(cfg, time.monotonic() + .1)
        self.assertIsNotNone(selected)
        self.assertEqual(selected['group_name'], 'market_sentiment')
        self.assertIn(json.loads(selected['job'])['api_name'], ('tdx_member', 'kpl_concept_cons'))
        self.assertTrue(choose.called)
        self.assertNotIn('market_members', [call.args[0] for call in choose.call_args_list])
        self.assertFalse(self.p.db.execute(
            "SELECT 1 FROM scheduler_state WHERE name LIKE '%market_members%'"
        ).fetchone())

    def test_explicit_start_invalid_codes_unknown_history_and_empty_universe(self):
        cfg = configuration()
        cfg.pop('market_members_history_start')
        cfg['history_start'] = '19900101'
        jobs = list(iter_market_member_jobs(cfg, TODAY, {}))
        self.assertEqual(len(jobs), 14)
        self.assertNotIn('history', {r['epoch'] for r in jobs})
        gaps = market_member_prerequisites({}, cfg)
        self.assertEqual(sum(g['reason'] == 'unknown_history_start_requires_scope' for g in gaps), 2)
        for invalid in (['600001.SH'], [None], [1], ['880206.TDX\n']):
            with self.assertRaises(ValueError):
                list(iter_market_member_jobs(configuration(), TODAY, {'tdx_indices': invalid}))
        a = module._planning_inputs('market_members', cfg, IDS)
        cfg['history_start'] = '20000101'
        self.assertEqual(a, module._planning_inputs('market_members', cfg, IDS))
        cfg['market_members_history_start'] = '20260901'
        self.assertNotEqual(a[0], module._planning_inputs('market_members', cfg, IDS)[0])


if __name__ == '__main__':
    unittest.main()
