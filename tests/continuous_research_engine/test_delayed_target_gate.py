import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from backend.services.engine.routers.continuous_research import act
from backend.services.research_agent import continuous_state as st
from test_delayed_target_check import BASELINE, PARAMETERS


class DelayedTargetGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_delay_or_unbound_window_is_rejected_before_public_write(
        self,
    ):
        for end, reason in (
            ("2020-06-30", "target_sequence_mismatch"),
            ("2020-06-29", "exactly_one_bound_control"),
        ):
            c = st.initial(
                {
                    "start_date": "2014-08-01",
                    "end_date": "2026-03-24",
                    "symbols": PARAMETERS["symbols"],
                    "max_experiments_per_task": 6,
                }
            )
            t = next(iter(c["tasks"].values()))
            t.update(
                family_id="delay-v1",
                research_brief={"required_precheck": "delayed_targets_v1"},
                reference_overviews=[
                    {
                        "backtest_id": "bound-control",
                        "metadata": {
                            "start_date": "2014-08-01",
                            "end_date": "2020-06-30",
                        },
                        "rows": [
                            {"code": BASELINE, "parameters": copy.deepcopy(PARAMETERS)}
                        ],
                    }
                ],
            )
            c["research_families"] = {
                "delay-v1": {"root_task_id": t["id"], "max_new_experiments": 4}
            }
            db = SimpleNamespace(execute=AsyncMock())
            with self.subTest(end=end), self.assertRaisesRegex(ValueError, reason):
                await act(
                    "a" * 32,
                    c,
                    t,
                    {
                        "action": "experiment",
                        "name": "immediate",
                        "hypothesis": "Wrong immediate signal must be rejected",
                        "code": BASELINE,
                        "parameters": PARAMETERS,
                        "start_date": "2014-08-01",
                        "end_date": end,
                    },
                    None,
                    db,
                )
            db.execute.assert_not_awaited()
            self.assertEqual(t["experiments"], {})
