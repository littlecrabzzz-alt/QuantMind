import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.continuous_research.audit import summarize_usage
from backend.services.research_agent import continuous_state as st


class UsageCoverageTests(unittest.TestCase):
    def test_new_task_starts_at_measured_zero(self):
        state = st.initial({})
        key = st.add_task(state, 'risk', 'one new research question', 'evidence')
        self.assertEqual(state['tasks'][key]['usage']['calls'], 0)


    def test_tokens_and_attempts_cannot_fill_missing_calls(self):
        tasks = [
            {'id': 'legacy', 'attempts': 20, 'usage': {'input': 100, 'output': 20, 'unknown_calls': 0}},
            {'id': 'new', 'usage': {'calls': 2, 'input': 3, 'output': 4, 'unknown_calls': 1}},
            {'id': 'zero', 'usage': {'calls': 0}},
            {'id': 'null', 'usage': {'calls': None}},
        ]
        before = copy.deepcopy(tasks)
        usage, coverage = summarize_usage(tasks)
        self.assertEqual(usage, {'calls': 2, 'input': 103, 'output': 24, 'unknown_calls': 1})
        self.assertEqual(coverage['call_count_missing_task_ids'], ['legacy', 'null'])
        self.assertTrue(coverage['calls_are_recorded_lower_bound'])
        self.assertEqual(tasks, before)

    def test_count_fields_present_does_not_prove_full_historical_coverage(self):
        usage, coverage = summarize_usage([{'id': 'partial', 'usage': {'calls': 1}}])
        self.assertEqual(usage['calls'], 1)
        self.assertEqual(coverage['call_count_missing_task_count'], 0)
        self.assertTrue(coverage['calls_are_recorded_lower_bound'])

    def test_step_only_endpoint_preserves_unknown_then_counts_new_calls(self):
        # Execute the real route branch without importing DB/Qlib or writing a programme.
        tree = ast.parse(Path('backend/services/engine/routers/continuous_research.py').read_text())
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == "body.op == 'usage'")
        fn = ast.parse('def apply(t, body, now):\n    pass').body[0]
        fn.body = branch.body
        ns = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<route-usage>', 'exec'), ns)
        for legacy in ({}, {'calls': None}):
            with self.subTest(legacy=legacy):
                task = {'usage': {'input': 100, 'output': 20, 'unknown_calls': 0, **legacy}}
                ns['apply'](task, SimpleNamespace(data={'step': 'working'}), 123)
                self.assertIsNone(task['usage'].get('calls'))
                self.assertTrue(task['usage']['calls_history_incomplete'])
                self.assertEqual(task['step'], 'working')
                self.assertEqual(task['last_activity'], 123)
                ns['apply'](task, SimpleNamespace(data={'calls': 1, 'input': 3}), 124)
                self.assertEqual(task['usage'], {'calls': 1, 'input': 103, 'output': 20,
                                               'unknown_calls': 0, 'calls_history_incomplete': True})
                before = copy.deepcopy(task['usage'])
                ns['apply'](task, SimpleNamespace(data={'step': 'reporting'}), 125)
                self.assertEqual(task['usage'], before)



if __name__ == '__main__':
    unittest.main()
