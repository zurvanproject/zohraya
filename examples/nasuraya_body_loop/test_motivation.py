"""Motivation opt-in, safe native body integration and source-bound feedback tests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .experience import ExperienceController
from . import motivation


class MotivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "body.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def synthetic_state(energy=.85, fatigue=.05, pain=.05, sleep_pressure=.05):
        return {"minimum_state": dict(
            energy=energy, fatigue=fatigue, pain=pain,
            sleep_pressure=sleep_pressure)}

    @staticmethod
    def near_tie():
        return {"preferred": "observe",
                "scores": {"walk": .36, "observe": .44},
                "memory_risk": .0,
                "prediction": {"prior_samples": 0}}

    def test_opt_in_is_only_way_to_add_desire(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            self.assertIsNone(c.status()["motivational_drive"])
            r = c.step("initial")
            self.assertNotIn("motivation", r["plan"])
            self.assertNotIn("motivation", c.status()["state"])
            self.assertIsNone(c.status()["motivational_drive"])
            remaining = loop.status()["actions_remaining"]
            result = c.enable_motivation(desire_proxy=.75)
            self.assertEqual(result["desire_proxy"], .75)
            self.assertEqual(loop.status()["actions_remaining"], remaining)
            self.assertEqual(c.enable_motivation(desire_proxy=.75), result)
            with self.assertRaisesRegex(ValueError, "cannot silently change"):
                c.enable_motivation(desire_proxy=.9)

    def test_high_authored_desire_tips_only_safe_near_tie(self):
        snapshot = self.synthetic_state()
        base = self.near_tie()
        calm = {"valence": .6, "arousal": .2}
        low = motivation.prepare(motivation.initial(0.), snapshot, base, calm)
        high = motivation.prepare(motivation.initial(1.), snapshot, base, calm)
        self.assertEqual(low["preferred"], "observe")
        self.assertEqual(high["preferred"], "walk")
        self.assertEqual(high["reason"], "motivated_exploration")
        self.assertEqual(high["desire_source"], "explicit_authored_simulation_parameter")
        self.assertFalse(high["subjective_lust_or_pleasure_inferred"])
        self.assertGreater(high["exploration_boost"], low["exploration_boost"])

    def test_distress_and_previous_harm_cannot_be_overridden_by_desire(self):
        strong = motivation.initial(1.)
        calm = {"valence": .65, "arousal": .1}
        base = self.near_tie()
        for snapshot in (
                self.synthetic_state(energy=.25),
                self.synthetic_state(fatigue=.9),
                self.synthetic_state(pain=.6),
                self.synthetic_state(sleep_pressure=.9)):
            p = motivation.prepare(strong, snapshot, base, calm)
            self.assertEqual(p["preferred"], "observe")
            self.assertEqual(p["reason"], "guarded_rest")
        harmful_memory = dict(base, memory_risk=.9)
        p = motivation.prepare(strong, self.synthetic_state(), harmful_memory, calm)
        self.assertEqual(p["preferred"], "observe")

    def test_sleep_fixture_avoids_native_protect_while_normal_can_walk(self):
        for fixture in ("sleep", "normal"):
            path = Path(self.tmp.name) / (fixture + ".sqlite")
            with BodyLoop.start(path, fixture=fixture, max_actions=1) as loop:
                c = ExperienceController.enable(loop)
                c.enable_motivation(desire_proxy=.9)
                result = c.step("one")
                self.assertEqual(result["this_call_native_cycles"], 1)
                self.assertIn("motivation", result["plan"])
                if fixture == "sleep":
                    self.assertEqual(result["plan"]["preferred"], "observe")
                    self.assertEqual(result["native_receipt"]["actual_action"], "observe")
                    self.assertEqual(result["plan"]["motivation"]["reason"], "guarded_rest")
                else:
                    self.assertEqual(result["plan"]["preferred"], "walk")
                    self.assertEqual(result["native_receipt"]["actual_action"], "walk")
                self.assertEqual(c.status()["motivational_drive"]["native_feedback_cycles"], 1)

    def test_workspace_and_motivation_use_same_native_receipt(self):
        with BodyLoop.start(self.path, fixture="sleep", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            c.enable_motivation(desire_proxy=.8)
            first = c.step("one")
            self.assertEqual(first["native_receipt"]["actual_action"], "observe")
            self.assertIn("workspace", first["plan"])
            self.assertIn("motivation", first["plan"])
            self.assertEqual(c.status()["integrated_workspace"]["learned_native_cycles"], 1)
            saved = c.status()["state"]["motivation"]
        with BodyLoop(self.path) as loop:
            c = ExperienceController(loop)
            self.assertEqual(c.status()["state"]["motivation"], saved)
            self.assertEqual(c.status()["motivational_drive"]["native_feedback_cycles"], 1)
            replay = c.step("one")
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["this_call_native_cycles"], 0)
            self.assertEqual(c.status()["motivational_drive"]["native_feedback_cycles"], 1)
            second = c.step("two")
            self.assertEqual(second["this_call_native_cycles"], 1)
            self.assertEqual(loop.status()["completed_cycles"], 2)
            self.assertEqual(c.status()["motivational_drive"]["native_feedback_cycles"], 2)
            self.assertEqual(c.status()["integrated_workspace"]["learned_native_cycles"], 2)
            self.assertEqual(loop.status()["actions_remaining"], 0)
            self.assertFalse(c.status()["native"]["external_model_api_used"])

    def test_failed_native_step_does_not_fabricate_motivational_learning(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            c.enable_motivation()
            with patch.object(UnifiedBody, "cycle", side_effect=RuntimeError("failed simulated cycle")):
                out = c.step("one")
            self.assertEqual(out["native_receipt"]["status"], "executor_failed")
            self.assertEqual(c.status()["motivational_drive"]["native_feedback_cycles"], 0)

    def test_bad_input_nan_untrusted_and_replayed_source_rejected(self):
        snap = self.synthetic_state()
        base = self.near_tie()
        state = motivation.initial(.8)
        p = motivation.prepare(state, snap, base, {"valence": .5, "arousal": .2})
        with self.assertRaises(ValueError):
            motivation.initial(float("nan"))
        with self.assertRaises(ValueError):
            motivation.prepare(state, self.synthetic_state(pain=float("inf")),
                               base, {"valence": .5, "arousal": .2})
        with self.assertRaises(ValueError):
            motivation.prepare(state, snap, base,
                               {"valence": .5, "arousal": float("nan")})
        with self.assertRaises(ValueError):
            motivation.record(state, "one", p, snap, "walk", "fake-source", .1, 0.)
        state = motivation.record(state, "one", p, snap, "walk",
                                  "native-decision://case/receipt", .1, 0.)
        with self.assertRaises(ValueError):
            motivation.record(state, "one", p, snap, "walk",
                              "native-decision://case/receipt", .1, 0.)
        self.assertEqual(motivation.summary(state)["native_feedback_cycles"], 1)
        state["receipts"][0]["harm"] = float("nan")
        with self.assertRaises(ValueError):
            motivation.validate(state)


if __name__ == "__main__":
    unittest.main()
