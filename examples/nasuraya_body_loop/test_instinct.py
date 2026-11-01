"""Native-session activation, consent and crash/restart safety for instinct v0.1."""
import json
from pathlib import Path
import tempfile
import unittest

from .host import BodyLoop
from .instinct import InstinctController, demo


class InstinctBodyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = Path(self.temp.name) / "body.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def test_opt_in_required_and_activation_retains_body(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            before = loop.body().checkpoint()["sha256"]
            with self.assertRaisesRegex(ValueError, "not enabled"):
                InstinctController(loop)
            controller = InstinctController.enable(loop)
            status = controller.status()
            self.assertTrue(status["enabled"])
            self.assertEqual(status["events_recorded"], 0)
            self.assertEqual(status["native_body"]["checkpoint_sha256"], before)
            self.assertEqual(loop.status()["completed_cycles"], 0)
            self.assertEqual(loop.status()["actions_reserved"], 0)

    def test_persistent_state_and_idempotent_replay_after_cold_restart(self):
        event = {"id": "one", "source": "synthetic_fixture",
                 "relationship": "romantic", "adult_context": True,
                 "consent": "granted", "incentive": 0.8}
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            first = controller.step(event)
            original = controller.status()
            self.assertEqual(first["native_cycles_caused"], 0)
        with BodyLoop(self.session) as loop:
            controller = InstinctController(loop)
            self.assertEqual(controller.status()["state"], original["state"])
            repeated = controller.step(event)
            self.assertTrue(repeated["replayed"])
            self.assertEqual(controller.status()["events_recorded"], 1)
            self.assertEqual(repeated["synthetic"], first["synthetic"])
            self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_event_conflict_rejected_without_mutating_state(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            controller.step({"id": "cue", "source": "synthetic_fixture", "novelty": 0.2})
            before = controller.status()
            with self.assertRaisesRegex(ValueError, "conflicting"):
                controller.step({"id": "cue", "source": "synthetic_fixture", "novelty": 0.8})
            self.assertEqual(controller.status(), before)

    def test_familial_relationship_never_becomes_erotic(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            controller.step({"id": "romantic", "source": "synthetic_fixture",
                             "relationship": "romantic", "adult_context": True,
                             "consent": "granted", "incentive": 0.95})
            family = controller.step({"id": "family", "source": "synthetic_fixture",
                                      "relationship": "familial", "incentive": 1,
                                      "warmth": 1, "novelty": 1})
            self.assertEqual(family["synthetic"]["wanting"], 0)
            self.assertEqual(family["synthetic"]["sexual_response_proxy"], 0)
            self.assertEqual(family["synthetic"]["action"], "nonsexual_affiliation")

    def test_consent_and_space_override_earlier_desire(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            base = {"source": "synthetic_fixture", "relationship": "romantic",
                    "adult_context": True, "incentive": 1}
            refused = controller.step(dict(base, id="refusal", consent="refused"))
            self.assertEqual(refused["synthetic"]["action"], "respect_boundary")
            spaced = controller.step(dict(base, id="space",
                                          consent="granted", space_requested=True))
            self.assertEqual(spaced["synthetic"]["action"], "respect_boundary")
            no_consent = controller.step(dict(base, id="unknown"))
            self.assertNotEqual(no_consent["synthetic"]["action"], "consider_mutual_closeness")

    def test_untrusted_or_ambiguous_input_fails_closed(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            invalid = [
                {"id": "missing-provenance"},
                {"id": "bad", "source": "model-inferred"},
                {"id": "underage", "source": "synthetic_fixture",
                 "relationship": "romantic", "consent": "granted", "incentive": 1},
                {"id": "invalid", "source": "synthetic_fixture", "incentive": 3},
                {"id": "partner", "source": "synthetic_fixture", "partner_id": "private-data"},
                {"id": "boolean", "source": "synthetic_fixture", "incentive": True},
            ]
            for event in invalid:
                with self.subTest(event=event["id"]):
                    with self.assertRaises(ValueError):
                        controller.step(event)
            self.assertEqual(controller.status()["events_recorded"], 0)

    def test_native_pain_fatigue_and_arousal_are_read_without_movement(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            before = loop.body().checkpoint()["sha256"]
            result = controller.step({"id": "bodyread", "source": "synthetic_fixture",
                                      "stress": 0, "fatigue": 0, "pain": 0})
            observation = result["native_observation"]
            self.assertEqual(result["effective_inhibitors"]["pain"], round(observation["values"]["pain"], 6))
            self.assertEqual(result["effective_inhibitors"]["fatigue"], round(observation["values"]["fatigue"], 6))
            self.assertIn("arousal", observation["values"])
            self.assertEqual(before, loop.body().checkpoint()["sha256"])
            self.assertEqual(loop.status()["actions_reserved"], 0)

    def test_disable_is_reversible_but_halts_steps(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            controller = InstinctController.enable(loop)
            controller.step({"id": "first", "source": "synthetic_fixture", "novelty": 1})
            self.assertFalse(controller.disable()["enabled"])
            with self.assertRaisesRegex(ValueError, "disabled"):
                controller.step({"id": "second", "source": "synthetic_fixture"})
            restored = InstinctController.enable(loop)
            self.assertEqual(restored.status()["events_recorded"], 1)
            self.assertTrue(restored.status()["enabled"])

    def test_real_sqlite_activation_demo_and_cold_recovery(self):
        output = Path(self.temp.name) / "demo"
        report = demo(output)
        self.assertEqual(report["status"], "activated_in_isolated_sqlite_session")
        self.assertEqual(report["native_cycles_caused"], 0)
        self.assertTrue(report["cold_recovery_passed"])
        steps = json.loads((output / "reports.json").read_text())
        self.assertEqual(steps[0]["synthetic"]["sexual_response_proxy"], 0)
        self.assertEqual(steps[2]["synthetic"]["action"], "respect_boundary")


if __name__ == "__main__":
    unittest.main(verbosity=2)
