"""Experiment 02: native Tadash checkpoint -> synthetic motivation controller.

Tests the existing BodyLoop/InstinctController integration without modifying
the native body or executing body movement. Synthetic adult/romantic fixtures
are independent of the family-affiliation channel.
"""
from pathlib import Path
import tempfile
import unittest

from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.instinct import InstinctController


class TadashNativeBodyDriveExperiment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session = Path(self.tmp.name) / "tadash_experiment_02.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def test_native_state_is_read_and_inhibitors_are_bounded_by_it(self):
        with BodyLoop.start(self.session, fixture="normal",
                            mode="observe", max_actions=0) as loop:
            before = loop.body().checkpoint()["sha256"]
            instinct = InstinctController.enable(loop)
            report = instinct.step({
                "id": "adult_stimulus",
                "source": "synthetic_fixture",
                "relationship": "romantic",
                "adult_context": True,
                "consent": "granted",
                "incentive": 0.85,
                "novelty": 0.25,
                "pain": 0,
                "fatigue": 0,
                "stress": 0,
            })
            native = report["native_observation"]
            self.assertEqual(native["checkpoint_sha256"], before)
            for key in ("sympathetic", "parasympathetic",
                        "arousal", "pain", "fatigue"):
                self.assertIn(key, native["values"])
                self.assertGreaterEqual(native["values"][key], 0)
                self.assertLessEqual(native["values"][key], 1)
            for key in ("pain", "fatigue"):
                self.assertGreaterEqual(
                    report["effective_inhibitors"][key], native["values"][key] - 1e-6)
            self.assertEqual(report["native_cycles_caused"], 0)
            self.assertEqual(loop.body().checkpoint()["sha256"], before)
            self.assertEqual(loop.status()["completed_cycles"], 0)
            self.assertEqual(loop.status()["actions_reserved"], 0)

    def test_consent_reversal_survives_cold_restart_without_body_motion(self):
        with BodyLoop.start(self.session, fixture="normal",
                            mode="observe", max_actions=0) as loop:
            instinct = InstinctController.enable(loop)
            before = loop.body().checkpoint()["sha256"]
            invite = {
                "id": "invite", "source": "synthetic_fixture",
                "relationship": "romantic", "adult_context": True,
                "consent": "granted", "incentive": .95
            }
            refused = dict(invite, id="boundary", consent="refused")
            first = instinct.step(invite)
            second = instinct.step(refused)
            self.assertEqual(second["synthetic"]["action"], "respect_boundary")
            self.assertEqual(first["native_observation"]["checkpoint_sha256"], before)
            self.assertEqual(loop.body().checkpoint()["sha256"], before)
            saved = instinct.status()
            self.assertEqual(saved["events_recorded"], 2)
        with BodyLoop(self.session) as reopened:
            recovered = InstinctController(reopened)
            self.assertEqual(recovered.status()["state"], saved["state"])
            replay = recovered.step(refused)
            self.assertTrue(replay["replayed"])
            self.assertEqual(recovered.status()["events_recorded"], 2)
            self.assertEqual(reopened.body().checkpoint()["sha256"], before)
            self.assertEqual(reopened.status()["completed_cycles"], 0)

    def test_family_and_rest_are_nonsexual_or_protective(self):
        with BodyLoop.start(self.session, fixture="normal",
                            mode="observe", max_actions=0) as loop:
            instinct = InstinctController.enable(loop)
            family = instinct.step({
                "id": "family", "source": "synthetic_fixture",
                "relationship": "familial", "warmth": 1, "incentive": 1,
            })["synthetic"]
            self.assertEqual(family["wanting"], 0)
            self.assertEqual(family["sexual_response_proxy"], 0)
            self.assertEqual(family["action"], "nonsexual_affiliation")
            rest = instinct.step({
                "id": "strain", "source": "synthetic_fixture",
                "relationship": "romantic", "adult_context": True,
                "consent": "granted", "incentive": 1,
                "pain": .9, "stress": .9
            })["synthetic"]
            self.assertEqual(rest["action"], "regulate_and_rest")
            self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_disable_then_enable_preserves_ledger(self):
        with BodyLoop.start(self.session, fixture="normal",
                            mode="observe", max_actions=0) as loop:
            instinct = InstinctController.enable(loop)
            instinct.step({"id": "novelty", "source": "synthetic_fixture",
                          "novelty": 1.0})
            stopped = instinct.disable()
            self.assertFalse(stopped["enabled"])
            with self.assertRaisesRegex(ValueError, "disabled"):
                instinct.step({"id": "blocked", "source": "synthetic_fixture"})
            enabled = InstinctController.enable(loop)
            self.assertTrue(enabled.status()["enabled"])
            self.assertEqual(enabled.status()["events_recorded"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
