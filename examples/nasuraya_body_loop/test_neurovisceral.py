"""Neurovisceral source, safety and native receipt checks."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from .host import BodyLoop
from .experience import ExperienceController
from . import neurovisceral


class NeurovisceralTests(unittest.TestCase):
    def test_native_source_and_special_organ_budget(self):
        with TemporaryDirectory() as root:
            with BodyLoop.start(Path(root) / "run.sqlite", max_actions=2) as loop:
                body = loop.body()
                before = body.checkpoint()["sha256"]
                sample = neurovisceral.capture(body)
                self.assertEqual(sample["native_checkpoint_sha256"], before)
                self.assertEqual(body.checkpoint()["sha256"], before)
                v = sample["values"]
                self.assertLessEqual(v["azarine_budget_j"], v["native_reserve_j"])
                state = neurovisceral.initial(sample)
                low = neurovisceral.preview(state, sample, desire_proxy=0.)
                high = neurovisceral.preview(state, sample, desire_proxy=.9)
                self.assertGreater(high["predicted_if_actuated_not_actuated"]["heart_bpm"],
                                   low["predicted_if_actuated_not_actuated"]["heart_bpm"])
                self.assertFalse(high["actual_native_physiology_changed"])
                self.assertEqual(body.checkpoint()["sha256"], before)

    def test_cold_restart_replay_and_optional_status(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "run.sqlite"
            with BodyLoop.start(path, max_actions=2) as loop:
                c = ExperienceController.enable(loop)
                c.enable_workspace()
                c.enable_motivation(desire_proxy=.8)
                c.enable_autonomic_bridge()
                c.enable_neurovisceral()
                result = c.step("first")
                self.assertEqual(result["this_call_native_cycles"], 1)
                self.assertIn("neurovisceral", result["plan"])
            with BodyLoop(path) as loop:
                c = ExperienceController(loop)
                repeat = c.step("first")
                self.assertTrue(repeat["replayed"])
                self.assertEqual(repeat["this_call_native_cycles"], 0)
                result = c.step("second")
                self.assertEqual(result["this_call_native_cycles"], 1)
                self.assertEqual(c.status()["neurovisceral_coordination"]["completed_native_cycles"], 2)

    def test_anatomy_is_separate_and_advisory(self):
        anatomy = neurovisceral.anatomy()
        self.assertEqual(len(anatomy["pathways"]), 10)
        self.assertEqual(len(anatomy["special_organs"]), 3)
        self.assertFalse(anatomy["native_organ_solvers_modified"])


if __name__ == "__main__":
    unittest.main()
