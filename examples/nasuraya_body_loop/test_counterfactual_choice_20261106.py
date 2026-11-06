"""Acceptance tests for counterfactual body feedback and decision revision."""
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import unittest

from .host import BodyLoop
from .instinct import InstinctController
from .counterfactual_choice import ChoiceRevisionMemory, reconsider


def feedback(report, **changes):
    values = {key: .15 for key in (
        "sympathetic", "parasympathetic", "arousal", "pain", "fatigue")}
    values.update(changes)
    return {"source": "synthetic_counterfactual_fixture",
            "baseline_native_checkpoint_sha256":
                report["native_observation"]["checkpoint_sha256"],
            "values": values}


class CounterfactualBodyMindTests(unittest.TestCase):
    def _fixture(self, loop, *, consent=None):
        controller = InstinctController.enable(loop)
        if consent is None:
            event = {"id": "exploration", "source": "synthetic_fixture",
                     "relationship": "friendship", "adult_context": True,
                     "novelty": .9}
        else:
            event = {"id": "romance", "source": "synthetic_fixture",
                     "relationship": "romantic", "adult_context": True,
                     "consent": consent, "incentive": 1}
        return controller.step(event)

    def test_identical_intention_diverges_with_different_body_feedback(self):
        with TemporaryDirectory() as d:
            with BodyLoop.start(Path(d) / "test.sqlite",
                                fixture="normal", mode="observe",
                                max_actions=0) as loop:
                report = self._fixture(loop)
                native_hash = loop.body().checkpoint()["sha256"]
                calm = reconsider(report, feedback(report, fatigue=.2))
                strained = reconsider(report, feedback(report, fatigue=.93))
                self.assertEqual(calm["initial_choice"], "explore")
                self.assertEqual(strained["initial_choice"], "explore")
                self.assertEqual(calm["revised_choice"], "explore")
                self.assertEqual(strained["revised_choice"],
                                 "regulate_and_rest")
                self.assertTrue(strained["changed"])
                self.assertEqual(loop.body().checkpoint()["sha256"],
                                 native_hash)
                self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_explicit_boundary_stays_binding_even_when_body_changes(self):
        with TemporaryDirectory() as d:
            with BodyLoop.start(Path(d) / "test.sqlite",
                                mode="observe", max_actions=0) as loop:
                report = self._fixture(loop, consent="refused")
                result = reconsider(report, feedback(report, fatigue=.99,
                                                     sympathetic=.99))
                self.assertEqual(result["initial_choice"],
                                 "respect_boundary")
                self.assertEqual(result["revised_choice"],
                                 "respect_boundary")
                self.assertFalse(result["actuation_authorized"])

    def test_counterfactual_replay_survives_cold_restart(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "test.sqlite"
            with BodyLoop.start(path, mode="observe", max_actions=0) as loop:
                report = self._fixture(loop)
                fake_body = feedback(report, fatigue=.91)
                memory = ChoiceRevisionMemory(loop)
                first = memory.step("choice-01", report, fake_body)
                self.assertEqual(memory.status()["cases"], 1)
                native_hash = loop.body().checkpoint()["sha256"]
            with BodyLoop(path) as loop:
                memory = ChoiceRevisionMemory(loop)
                prior = memory.step("choice-01", report, fake_body)
                self.assertTrue(prior["replayed"])
                self.assertEqual(prior["revised_choice"],
                                 first["revised_choice"])
                self.assertEqual(memory.status()["cases"], 1)
                self.assertEqual(loop.body().checkpoint()["sha256"],
                                 native_hash)
                self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_conflict_invalid_provenance_and_out_of_range_are_rejected(self):
        with TemporaryDirectory() as d:
            with BodyLoop.start(Path(d) / "test.sqlite",
                                mode="observe", max_actions=0) as loop:
                report = self._fixture(loop)
                controller = ChoiceRevisionMemory(loop)
                baseline = feedback(report)
                controller.step("id-1", report, baseline)
                changed = feedback(report, fatigue=.9)
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    controller.step("id-1", report, changed)
                wrong = dict(baseline, source="native_software_checkpoint_only")
                with self.assertRaises(ValueError):
                    reconsider(report, wrong)
                wrong = deepcopy(baseline)
                wrong["values"]["fatigue"] = float("nan")
                with self.assertRaises(ValueError):
                    reconsider(report, wrong)
                wrong = dict(baseline, baseline_native_checkpoint_sha256="f" * 64)
                with self.assertRaises(ValueError):
                    reconsider(report, wrong)
                self.assertEqual(controller.status()["cases"], 1)

    def test_deterministic_and_non_actuating(self):
        with TemporaryDirectory() as d:
            with BodyLoop.start(Path(d) / "test.sqlite",
                                mode="observe", max_actions=0) as loop:
                report = self._fixture(loop)
                sample = feedback(report, pain=.9)
                a, b = reconsider(report, sample), reconsider(report, sample)
                self.assertEqual(a, b)
                self.assertFalse(a["actuation_authorized"])
                self.assertEqual(a["native_cycles_caused"], 0)
                self.assertEqual(a["counterfactual_source"],
                                 "synthetic_counterfactual_fixture")


if __name__ == "__main__":
    unittest.main(verbosity=2)
