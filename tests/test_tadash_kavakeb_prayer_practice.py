"""Boundary tests for the authored adapter, not a re-test of native dynamics."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.tadash_kavakeb_prayer_practice import (
    DEFAULT_CONFIG, GasAudit, GaitEnvironment, Inputs, PostureLoop, PrayerPostureLoop,
    environment, norm, run_one, validate_config,
)


class PrayerPracticeBoundaries(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))

    def test_nonfinite_and_oversized_reference_rejected(self):
        for amplitude in (float("nan"), float("inf"), -float("inf"), .001001, -.001, True):
            with self.subTest(amplitude=amplitude):
                candidate = deepcopy(self.config)
                candidate["simulation"]["reference_amplitude_m"] = amplitude
                with self.assertRaises(ValueError):
                    validate_config(candidate)
        for direction in ([float("nan"), 0], [1, 1], [2, 0], [0, 0]):
            with self.subTest(direction=direction):
                candidate = deepcopy(self.config)
                candidate["simulation"]["geometry_directions"][0] = direction
                with self.assertRaises(ValueError):
                    validate_config(candidate)

    def test_duration_clock_and_resource_limits_cannot_be_relaxed(self):
        for key, value in (("dt_s", .01), ("dt_s", float("nan")),
                           ("stage_duration_s", 4.1), ("stage_duration_s", .075),
                           ("repetitions", 4), ("repetitions", True)):
            with self.subTest(key=key, value=value):
                candidate = deepcopy(self.config)
                candidate["simulation"][key] = value
                with self.assertRaises(ValueError):
                    validate_config(candidate)
        candidate = deepcopy(self.config)
        candidate["acceptance"]["maximum_pressure_kpa"] = 301
        with self.assertRaises(ValueError):
            validate_config(candidate)

    def test_native_rest_reflex_and_swing_targets_retain_authority(self):
        schedule = validate_config(self.config)
        loop = PrayerPostureLoop(schedule)
        # A clock-only fixture puts the target function at its nonzero peak.
        # No COM, velocity, foot or joint position is assigned in this test.
        loop.state.time_s = 6.
        normal = environment(schedule)
        self.assertEqual(loop._target(normal), [.001, 0.])

        rest = GaitEnvironment(body=Inputs(dt_s=schedule.dt), airway_capacity=.1)
        self.assertEqual(loop._target(rest), PostureLoop._target(loop, rest))
        self.assertEqual(loop.last_authored_offset, [0., 0.])
        self.assertEqual(loop.last_reference_guard, "native_pending_rest")

        loop.state.reflex_recovery = True
        self.assertEqual(loop._target(normal), PostureLoop._target(loop, normal))
        self.assertEqual(loop.last_authored_offset, [0., 0.])
        self.assertEqual(loop.last_reference_guard, "native_reflex")
        loop.state.reflex_recovery = False

        loop.state.swing = {"side": "R"}
        self.assertEqual(loop._target(normal), PostureLoop._target(loop, normal))
        self.assertEqual(loop.last_authored_offset, [0., 0.])
        self.assertEqual(loop.last_reference_guard, "native_stance_or_swing")

    def test_real_native_contact_failure_never_counts_as_complete(self):
        def no_contact(index, loop, schedule):
            inactive = [p["id"] for p in loop.design["patches"]]
            return GaitEnvironment(body=Inputs(dt_s=schedule.dt), command="stand",
                                   inactive_patches={"L": inactive, "R": inactive})

        result = run_one(self.config, "practice", environment_factory=no_contact)
        report = result["summary"]
        self.assertFalse(report["completed"])
        self.assertEqual(report["full_passes"], 0)
        self.assertEqual(report["integration_frames"], 1)
        self.assertEqual(report["passed_integration_frames"], 0)
        self.assertEqual(report["status"], "stopped_on_failure")
        self.assertIn("native_mechanical_failure", report["failures"][0]["reasons"])
        self.assertEqual(result["frames"][-1]["native_failed_reason"], "no_pressure_feasible_support")

    def test_prayer_text_changes_do_not_change_numeric_controls_or_motion(self):
        first = deepcopy(self.config)
        first["simulation"].update(repetitions=1, stage_duration_s=.2, geometry_directions=[[1, 0]])
        second = deepcopy(first)
        second["prayer"] = {"opening_fa": "متن متفاوت", "instructions": "arbitrary display text, no actuator authority"}
        a = run_one(first, "practice", max_steps=8)
        b = run_one(second, "practice", max_steps=8)
        self.assertTrue(any(norm(row["target_offset_m"]) > 0 for row in a["frames"]))
        self.assertEqual(a["frames"], b["frames"])
        self.assertEqual(a["checkpoint"], b["checkpoint"])
        self.assertEqual(a["summary"]["failures"], [])
        self.assertFalse(a["summary"]["completed"])
        self.assertEqual(a["summary"]["full_passes"], 0)

    def test_one_completed_schedule_is_not_a_three_pass_session(self):
        candidate = deepcopy(self.config)
        candidate["simulation"].update(repetitions=1, stage_duration_s=.05,
                                        reference_amplitude_m=0., geometry_directions=[[1, 0]])
        report = run_one(candidate, "practice")["summary"]
        self.assertEqual(report["full_passes"], 1)
        self.assertTrue(report["schedule_completed"])
        self.assertFalse(report["session_complete_under_three_pass_rule"])
        self.assertFalse(report["completed"])
        self.assertEqual(report["status"], "partial_session_under_three_pass_rule")

    def test_false_native_audit_verdict_stops_even_without_exception(self):
        native_result = GasAudit.result
        def false_verdict(audit):
            return {**native_result(audit), "passed": False}
        with patch.object(GasAudit, "result", false_verdict):
            result = run_one(self.config, "practice", max_steps=8)
        report = result["summary"]
        self.assertEqual(report["integration_frames"], 1)
        self.assertEqual(report["full_passes"], 0)
        self.assertFalse(report["completed"])
        self.assertFalse(report["audits"]["gas"]["passed"])
        self.assertFalse(result["frames"][-1]["audits"]["gas"]["passed"])
        self.assertIn("gas_audit", report["failures"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
