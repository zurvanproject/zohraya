"""Tests for the PR132 -> PR134 autonomic/motivation bridge in software Tadash."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .experience import ExperienceController, KEY
from . import autonomic_peak, autonomic_bridge, motivation


class AutonomicMotivationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "body.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def config(controller):
        controller.enable_workspace()
        controller.enable_motivation(desire_proxy=.95)
        return controller

    def test_explicit_enable_does_not_run_native_body_or_change_checkpoint(self):
        with BodyLoop.start(self.path, max_actions=3, fixture="normal") as loop:
            c = ExperienceController.enable(loop)
            with self.assertRaisesRegex(ValueError, "motivation and workspace"):
                c.enable_autonomic_bridge()
            self.config(c)
            before = loop.body().checkpoint()["sha256"]
            budget = loop.status()["actions_remaining"]
            status = c.enable_autonomic_bridge()
            self.assertEqual(status["model_phase"], "baseline")
            self.assertEqual(status["model_t_seconds"], 0.)
            self.assertEqual(status["wave_samples_total"], 17)
            self.assertEqual(status["initial_native_checkpoint_sha256"], before)
            self.assertEqual(c.enable_autonomic_bridge(), status)
            self.assertEqual(loop.body().checkpoint()["sha256"], before)
            self.assertEqual(loop.status()["actions_remaining"], budget)
            self.assertEqual(loop.status()["completed_cycles"], 0)
            self.assertTrue(status["no_actual_pelvic_contractions"])

    def test_native_receipts_advance_wave_without_double_play_after_restart(self):
        with BodyLoop.start(self.path, max_actions=3, fixture="normal") as loop:
            c = self.config(ExperienceController.enable(loop))
            c.enable_autonomic_bridge()
            first = c.step("one")
            self.assertEqual(first["plan"]["autonomic_wave"]["sample"]["phase"], "baseline")
            self.assertEqual(first["plan"]["autonomic_wave"]["index"], 0)
            self.assertEqual(first["native_receipt"]["status"], "complete")
            self.assertEqual(c.status()["autonomic_motivation_bridge"]["native_feedback_cycles"], 1)
            self.assertEqual(c.status()["autonomic_motivation_bridge"]["model_t_seconds"], 2.)
            saved = deepcopy(c.status()["state"]["autonomic_bridge"])
        with BodyLoop(self.path) as loop:
            c = ExperienceController(loop)
            self.assertEqual(c.status()["state"]["autonomic_bridge"], saved)
            r = c.step("one")
            self.assertTrue(r["replayed"])
            self.assertEqual(r["this_call_native_cycles"], 0)
            self.assertEqual(c.status()["autonomic_motivation_bridge"]["native_feedback_cycles"], 1)
            for i in (2, 3):
                response = c.step("cycle%d" % i)
                self.assertIn("autonomic_wave", response["plan"])
                self.assertIn("motivation", response["plan"])
                self.assertIn("workspace", response["plan"])
                self.assertEqual(response["native_receipt"]["status"], "complete")
                self.assertEqual(response["this_call_native_cycles"], 1)
            status = c.status()
            self.assertEqual(status["native"]["completed_cycles"], 3)
            self.assertEqual(status["native"]["actions_remaining"], 0)
            self.assertEqual(status["autonomic_motivation_bridge"]["native_feedback_cycles"], 3)
            self.assertEqual(status["motivational_drive"]["native_feedback_cycles"], 3)
            self.assertEqual(status["integrated_workspace"]["learned_native_cycles"], 3)
            self.assertEqual(status["autonomic_motivation_bridge"]["model_t_seconds"], 6.)
            self.assertFalse(status["native"]["external_model_api_used"])

    def test_failed_native_cycle_cannot_advance_wave(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            c = self.config(ExperienceController.enable(loop))
            c.enable_autonomic_bridge()
            with patch.object(UnifiedBody, "cycle", side_effect=RuntimeError("simulator failure")):
                result = c.step("fail")
            self.assertEqual(result["native_receipt"]["status"], "executor_failed")
            self.assertEqual(c.status()["autonomic_motivation_bridge"]["native_feedback_cycles"], 0)
            self.assertEqual(c.status()["autonomic_motivation_bridge"]["model_t_seconds"], 0.)

    def test_enable_not_allowed_after_native_action(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            c = self.config(ExperienceController.enable(loop))
            c.step("one")
            with self.assertRaisesRegex(ValueError, "before first native cycle"):
                c.enable_autonomic_bridge()
            self.assertIsNone(c.status()["autonomic_motivation_bridge"])

    def test_correct_source_and_malformed_wave_rejected(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            c = self.config(ExperienceController.enable(loop))
            c.enable_autonomic_bridge()
            value = c.status()["state"]["autonomic_bridge"]
            preview = autonomic_bridge.preview(value)
            self.assertEqual(preview["source_schema"], autonomic_peak.KEY)
            other = deepcopy(preview)
            other["sample"]["activation_envelope"] = .75
            with self.assertRaisesRegex(ValueError, "corrupted"):
                autonomic_bridge.validate_preview(other)
            other = deepcopy(value)
            other["native_baseline"]["sympathetic"] = 0.
            with self.assertRaisesRegex(ValueError, "provenance"):
                autonomic_bridge.validate(other)
            with self.assertRaisesRegex(ValueError, "native software-body receipt"):
                autonomic_bridge.record(value, "fake", preview, "forged", "walk")
            with self.assertRaisesRegex(ValueError, "predecision not frozen"):
                different = deepcopy(value)
                different["native_feedback_cycles"] = 1
                different["sample_index"] = 1
                autonomic_bridge.record(different, "one", preview,
                                        "native-decision://trusted", "walk")

    def test_phase_causal_changes_are_pure_and_guarded(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            source = autonomic_peak.compute(loop)
            state = autonomic_bridge.initial(source)
        motive = motivation.initial(.95)
        snapshot = {"minimum_state": {
            "energy": .9, "fatigue": .05, "pain": .05, "sleep_pressure": .05}}
        base = {"preferred": "walk", "scores": {"walk": .63, "observe": .39},
                "memory_risk": 0., "prediction": {"prior_samples": 0}}
        affect = {"valence": .65, "arousal": .35}
        baseline = motivation.prepare(motive, snapshot, base, affect)
        initial = motivation.prepare(motive, snapshot, base, affect,
                                     autonomic=autonomic_bridge.preview(state))
        self.assertEqual(initial["preferred"], baseline["preferred"])
        self.assertEqual(initial["adjusted_scores"], baseline["adjusted_scores"])
        state["native_feedback_cycles"] = 3
        state["sample_index"] = 3
        rising = motivation.prepare(motive, snapshot, base, affect,
                                    autonomic=autonomic_bridge.preview(state))
        self.assertEqual(rising["autonomic_phase"], "rise")
        self.assertGreater(rising["wave_exploration_boost"], 0.)
        self.assertEqual(rising["preferred"], "walk")
        state["native_feedback_cycles"] = 6
        state["sample_index"] = 6
        peak_phase = motivation.prepare(motive, snapshot, base, affect,
                                        autonomic=autonomic_bridge.preview(state))
        self.assertEqual(peak_phase["autonomic_phase"], "peak")
        self.assertEqual(peak_phase["preferred"], "observe")
        self.assertEqual(peak_phase["reason"], "guarded_rest")
        state["native_feedback_cycles"] = 10
        state["sample_index"] = 10
        recovered = motivation.prepare(motive, snapshot, base, affect,
                                       autonomic=autonomic_bridge.preview(state))
        self.assertEqual(recovered["autonomic_phase"], "recovery")
        self.assertLess(recovered["wave_regulation_pressure"],
                        peak_phase["wave_regulation_pressure"])
        self.assertFalse(recovered["subjective_lust_or_pleasure_inferred"])
        self.assertTrue(recovered["wave_is_authored_not_experienced"])

    def test_state_integrity_detects_modified_wave_even_if_json_is_valid(self):
        from reflection_cycle import canonical, digest
        import json
        with BodyLoop.start(self.path, max_actions=2) as loop:
            c = self.config(ExperienceController.enable(loop))
            c.enable_autonomic_bridge()
            row = loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
            envelope = json.loads(row[0])
            envelope["value"]["autonomic_bridge"]["sample_index"] = 6
            envelope["sha256"] = digest(envelope["value"])
            loop.engine.db.execute("UPDATE meta SET value=? WHERE key=?",
                                   (canonical(envelope), KEY))
            with self.assertRaisesRegex(ValueError, "index must correspond"):
                c.status()


if __name__ == "__main__":
    unittest.main()
