"""Synthetic target clocks, with deliberately wrong implementations as controls."""

import copy
import json
import unittest

from backend.services.research_agent.delayed_target_check import check_delayed_targets


BASELINE = """def on_signal(ctx):
    p = ctx["parameters"]
    state = ctx.get("state", {})
    sym = p["gate_symbol"]
    if ctx["is_entry"] or ctx["is_month_end"]:
        values = ctx["monthly_prices"][sym][-p["monthly_lookback"]:]
        average = fsum(values) / len(values)
        last = values[-1]
        gate = 1 if last > average else (0 if last < average else state.get("gate", 0))
        state = {"gate": gate, "mode": "on" if gate else "off", "frozen": average}
        return {"targets": p["target_weights"] if gate else p["off_weights"], "reason": "gate", "state": state}
    if p["daily_reentry"] and state["mode"] == "off" and ctx["history"][sym][-1] > state["frozen"]:
        state["mode"] = "re"
        return {"targets": p["target_weights"], "reason": "reentry", "state": state}
    return {"targets": None, "reason": "no_rebalance", "state": state}
"""

WRAPPER = """
def on_signal(ctx):
    state = ctx.get("state", {})
    raw_ctx = dict(ctx)
    raw_ctx["state"] = state.get("original", {})
    raw = baseline_signal(raw_ctx)
    if ctx["is_entry"]:
        return {"targets": raw["targets"], "reason": "entry", "state": {"original": raw["state"], "pending": None}}
    targets = state.get("pending")
    return {"targets": targets, "reason": "one_step", "state": {"original": raw["state"], "pending": raw["targets"], "date": ctx["date"]}}
"""

PARAMETERS = {
    "symbols": ["510300.SH", "518880.SH", "511010.SH"],
    "gate_symbol": "510300.SH",
    "lookback": 61,
    "monthly_lookback": 10,
    "daily_reentry": True,
    "signal_on_month_end": False,
    "target_weights": {"510300.SH": 0.6, "518880.SH": 0.4, "511010.SH": 0},
    "off_weights": {"510300.SH": 0, "518880.SH": 0.4, "511010.SH": 0.6},
}


def candidate(wrapper=WRAPPER):
    return (
        BASELINE.replace("def on_signal(ctx):", "def baseline_signal(ctx):") + wrapper
    )


class DelayedTargetCheckTests(unittest.TestCase):
    def test_valid_one_step_both_variants_and_no_input_mutation(self):
        for reentry in (False, True):
            with self.subTest(reentry=reentry):
                p = dict(PARAMETERS, daily_reentry=reentry)
                before = copy.deepcopy(p)
                result = check_delayed_targets(candidate(), p, BASELINE, p)
                self.assertTrue(result["ok"])
                self.assertEqual(p, before)
                self.assertEqual(len(result["cases"]), 2)
                self.assertEqual(
                    result["internal_state_equivalence"],
                    "not_checked_no_required_state_schema",
                )
                for case in result["cases"]:
                    # Entry is not repeated on the first nonentry day.
                    self.assertIsNone(case["trace"][1]["checked_delayed_targets"])
                    self.assertIsNotNone(case["terminal_expected_pending_target"])
                json.dumps(result, allow_nan=False)

    def test_immediate_submission_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "target_sequence_mismatch"):
            check_delayed_targets(BASELINE, PARAMETERS, BASELINE, PARAMETERS)

    def test_candidate_evaluation_error_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "delayed_target_check"):
            check_delayed_targets(
                "def on_signal(ctx):\n    return 1 / 0",
                PARAMETERS,
                BASELINE,
                PARAMETERS,
            )

    def test_two_steps_is_rejected(self):
        wrong = WRAPPER.replace(
            'targets = state.get("pending")', 'targets = state.get("older")'
        )
        wrong = wrong.replace(
            '"pending": raw["targets"],',
            '"pending": raw["targets"], "older": state.get("pending"),',
        )
        with self.assertRaisesRegex(ValueError, "target_sequence_mismatch"):
            check_delayed_targets(candidate(wrong), PARAMETERS, BASELINE, PARAMETERS)

    def test_only_advancing_nonempty_targets_is_rejected(self):
        wrong = WRAPPER.replace(
            '"pending": raw["targets"],',
            '"pending": raw["targets"] if raw["targets"] is not None else state.get("pending"),',
        )
        with self.assertRaisesRegex(ValueError, "target_sequence_mismatch"):
            check_delayed_targets(candidate(wrong), PARAMETERS, BASELINE, PARAMETERS)

    def test_calendar_day_delay_is_rejected_across_weekend(self):
        wrong = WRAPPER.replace(
            'targets = state.get("pending")',
            """targets = state.get("pending")
    if state.get("date") and int(ctx["date"][-2:]) - int(state["date"][-2:]) != 1:
        targets = None""",
        )
        with self.assertRaisesRegex(ValueError, "target_sequence_mismatch"):
            check_delayed_targets(candidate(wrong), PARAMETERS, BASELINE, PARAMETERS)

    def test_entry_must_not_enter_delay_queue(self):
        wrong = WRAPPER.replace('"pending": None', '"pending": raw["targets"]')
        with self.assertRaisesRegex(ValueError, "target_sequence_mismatch"):
            check_delayed_targets(candidate(wrong), PARAMETERS, BASELINE, PARAMETERS)

    def test_frozen_parameter_drift_is_rejected(self):
        for field, value in (
            ("lookback", 62),
            ("daily_reentry", 1),
            ("target_weights", {"510300.SH": 1.0}),
        ):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "parameter_drift"),
            ):
                check_delayed_targets(
                    candidate(),
                    dict(PARAMETERS, **{field: value}),
                    BASELINE,
                    PARAMETERS,
                )

    def test_original_state_must_advance_not_delayed_with_target(self):
        wrong = WRAPPER.replace(
            '"original": raw["state"], "pending": raw["targets"]',
            '"original": state.get("original", {}), "pending": raw["targets"]',
        )
        with self.assertRaisesRegex(ValueError, "target_sequence_mismatch"):
            check_delayed_targets(candidate(wrong), PARAMETERS, BASELINE, PARAMETERS)


if __name__ == "__main__":
    unittest.main()
