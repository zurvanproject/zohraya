"""Integration checks against the installed packages and real native arbitration."""
import asyncio
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .__main__ import copy_runtime
from .graph import store_and_recall
from .policy import EffortPolicy
from .runtime import native_template, run_case


class ConnectedLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.scratch.cleanup)
        runtime = Path(cls.scratch.name) / "native"
        copy_runtime(runtime)
        cls.template = native_template(runtime)
        cls.ready = run_case(cls.template, "ready", 2, 0.)
        cls.loaded = run_case(cls.template, "loaded", 2, .65)
        cls.masked = run_case(cls.template, "masked", 2, 0., missing_first=True)

    def test_only_initial_fatigue_changes_the_first_request(self):
        ready, loaded = self.ready[0], self.loaded[0]
        self.assertEqual(ready["before_native"], loaded["before_native"])
        self.assertEqual(ready["before_myo"]["elbow_rad"], loaded["before_myo"]["elbow_rad"])
        self.assertEqual((ready["decision"]["requested"], loaded["decision"]["requested"]), ("walk", "rest"))
        self.assertEqual((ready["selected_action"], loaded["selected_action"]), ("walk", "rest"))
        self.assertGreater(ready["after_myo"]["mean_fatigue"], ready["before_myo"]["mean_fatigue"])
        self.assertLess(loaded["after_myo"]["mean_fatigue"], loaded["before_myo"]["mean_fatigue"])

    def test_next_cycle_reuses_measured_elbow_and_fatigue(self):
        first, second = self.masked
        self.assertEqual((first["selected_action"], second["selected_action"]), ("observe", "walk"))
        for key, value in second["before_myo"].items():
            self.assertEqual(first["after_myo"][key], value)
        self.assertAlmostEqual(second["elbow_target_for_native_rad"], np.clip(first["after_myo"]["elbow_rad"], 0., 1.5))
        for row in self.ready + self.loaded + self.masked:
            self.assertEqual(row["native_ticks"], 10)
            self.assertEqual(row["after_myo"]["control_steps"], 50)
            self.assertAlmostEqual(row["after_myo"]["time_s"] - row["before_myo"]["time_s"], 1.)
            self.assertLess(row["after_myo"]["max_compartment_error"], 1e-5)
            self.assertLess(row["motion"]["hand_target_error_m"], .01)

    def test_unavailable_fatigue_and_native_limit(self):
        native = dict(self.ready[0]["before_native"])
        agent = EffortPolicy()
        self.assertEqual(agent.decide(native, .65, missing=True)["requested"], "observe")
        self.assertEqual(agent.decide(native, float("nan"))["cue"], "unclear")
        native["pain"] = .5
        self.assertEqual(agent.decide(native, .65, missing=True)["requested"], "rest")

    def test_native_veto_controls_muscle_and_kinematics(self):
        from run_reflection_demo import sleep_fixture
        row = run_case(sleep_fixture(), "native_veto", 1, 0.)[0]
        self.assertEqual(row["decision"]["requested"], "walk")
        self.assertNotEqual(row["selected_action"], "walk")
        self.assertEqual(row["motion"]["target_elbow_rad"], 0.)
        self.assertLess(row["after_myo"]["mean_fatigue"], self.ready[0]["after_myo"]["mean_fatigue"])

    def test_graph_preserves_records_and_within_case_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.ready + self.loaded
            recovered, stats = asyncio.run(store_and_recall(Path(tmp), rows))
        self.assertEqual(recovered, rows)
        self.assertEqual(stats["episodes"], 4)
        self.assertEqual(stats["temporal_edges"], 2)
        self.assertTrue(stats["database_reopened"] and stats["separate_process"] and stats["standalone_database"])


if __name__ == "__main__":
    unittest.main()
