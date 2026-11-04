"""Native-software tests for authored desire -> peak -> regulation memory."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .experience import ExperienceController
from . import embodied_integration


def configured(loop):
    controller = ExperienceController.enable(loop)
    controller.enable_workspace()
    controller.enable_motivation(desire_proxy=0.85)
    controller.enable_autonomic_bridge()
    controller.enable_neurovisceral()
    return controller


class EmbodiedIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "body.sqlite"

    def tearDown(self):
        self.directory.cleanup()

    def test_enable_requires_layers_and_does_not_actuate(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            controller = ExperienceController.enable(loop)
            with self.assertRaisesRegex(ValueError, "workspace"):
                controller.enable_embodied_integration()
            controller.enable_workspace()
            controller.enable_motivation(desire_proxy=.85)
            controller.enable_autonomic_bridge()
            controller.enable_neurovisceral()
            before = loop.body().checkpoint()["sha256"]
            budget = loop.status()["actions_remaining"]
            result = controller.enable_embodied_integration()
            self.assertEqual(result["native_feedback_cycles"], 0)
            self.assertEqual(result["modeled_peak_count"], 0)
            self.assertEqual(controller.enable_embodied_integration(), result)
            self.assertEqual(loop.body().checkpoint()["sha256"], before)
            self.assertEqual(loop.status()["actions_remaining"], budget)
            self.assertEqual(loop.status()["completed_cycles"], 0)
            self.assertFalse(result["physical_actuation"])
            self.assertTrue(result["model_peak_is_not_felt_orgasm"])

    def test_opt_in_replay_cold_restart_and_peak_phases(self):
        with BodyLoop.start(self.path, max_actions=9, fixture="normal") as loop:
            controller = configured(loop)
            controller.enable_embodied_integration()
            first = controller.step("cycle1")
            self.assertEqual(first["this_call_native_cycles"], 1)
            self.assertEqual(first["plan"]["embodied_integration"]["phase"], "baseline")
            self.assertEqual(
                first["plan"]["embodied_integration"]["actual_somatic_contractions"], 0)
            self.assertEqual(
                controller.status()["embodied_peak_reward_memory"]["native_feedback_cycles"], 1)
        with BodyLoop(self.path) as loop:
            controller = ExperienceController(loop)
            replay = controller.step("cycle1")
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["this_call_native_cycles"], 0)
            self.assertEqual(
                controller.status()["embodied_peak_reward_memory"]["native_feedback_cycles"], 1)
            phases = []
            for n in range(2, 10):
                result = controller.step("cycle%d" % n)
                self.assertEqual(result["native_receipt"]["status"], "complete")
                self.assertEqual(result["this_call_native_cycles"], 1)
                before = result["plan"]["embodied_integration"]
                phases.append(before["phase"])
                self.assertFalse(before["felt_pleasure_or_orgasm_claimed"])
                self.assertTrue(before["native_safety_authoritative"])
                if before["modeled_peak_not_orgasm"]:
                    self.assertEqual(before["recommendation"], "observe")
                    self.assertEqual(result["plan"]["preferred"], "observe")
            status = controller.status()
            memory = status["embodied_peak_reward_memory"]
            self.assertEqual(memory["native_feedback_cycles"], 9)
            self.assertEqual(memory["retained_receipts"], 9)
            self.assertEqual(status["native"]["completed_cycles"], 9)
            self.assertEqual(memory["modeled_peak_count"], 3)
            self.assertEqual(memory["refractory_remaining"], 3)
            self.assertIn("peak", phases)
            self.assertTrue(memory["reward_is_from_native_software_state_not_pleasure"])
            self.assertFalse(status["native"]["external_model_api_used"])

    def test_recovery_uses_a_conservative_observation_gate(self):
        with BodyLoop.start(self.path, max_actions=10, fixture="normal") as loop:
            controller = configured(loop)
            controller.enable_embodied_integration()
            phases = []
            for n in range(10):
                result = controller.step("step%d" % n)
                embodied = result["plan"]["embodied_integration"]
                phases.append(embodied["phase"])
                if embodied["phase"] == "recovery":
                    self.assertEqual(embodied["recommendation"], "observe")
                    self.assertEqual(result["plan"]["preferred"], "observe")
            self.assertIn("recovery", phases)

    def test_no_learning_from_failed_cycle(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            controller = configured(loop)
            controller.enable_embodied_integration()
            with patch.object(UnifiedBody, "cycle", side_effect=RuntimeError("body failure")):
                result = controller.step("fail")
            self.assertEqual(result["native_receipt"]["status"], "executor_failed")
            status = controller.status()["embodied_peak_reward_memory"]
            self.assertEqual(status["native_feedback_cycles"], 0)
            self.assertEqual(status["retained_receipts"], 0)

    def test_source_integrity_and_repeat_rejection(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            controller = configured(loop)
            controller.enable_embodied_integration()
            s = controller.status()["state"]["embodied_integration"]
            bad = deepcopy(s)
            bad["regulation_ema"] = float("nan")
            with self.assertRaises(ValueError):
                embodied_integration.validate(bad)
            result = controller.step("one")
            with self.assertRaisesRegex(ValueError, "distinct native receipt"):
                embodied_integration.record(
                    controller.status()["state"]["embodied_integration"], "one",
                    result["plan"]["embodied_integration"],
                    result["prediction"]["source"], result["native_receipt"]["actual_action"],
                    result["native_receipt"]["self_model_before"],
                    result["native_receipt"]["self_model_after"], 0)
            altered = deepcopy(result["plan"]["embodied_integration"])
            altered["source_checkpoint_sha256"] = "0"*64
            with self.assertRaises(ValueError):
                embodied_integration.record(
                    s, "new", altered, result["prediction"]["source"],
                    result["native_receipt"]["actual_action"],
                    result["native_receipt"]["self_model_before"],
                    result["native_receipt"]["self_model_after"], 0)

    def test_legacy_without_opt_in_keeps_no_integration(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            controller = configured(loop)
            self.assertIsNone(controller.status()["embodied_peak_reward_memory"])
            result = controller.step("first")
            self.assertNotIn("embodied_integration", result["plan"])
            with self.assertRaisesRegex(ValueError, "before first native cycle"):
                controller.enable_embodied_integration()
            self.assertIsNone(controller.status()["embodied_peak_reward_memory"])


if __name__ == "__main__":
    unittest.main()
