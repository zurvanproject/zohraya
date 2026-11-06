"""Read-only decision arbitration tests over a genuine synthetic BodyLoop."""
from pathlib import Path
import tempfile
import unittest

from .host import BodyLoop
from .instinct import InstinctController
from .drive_decision_bridge import advise


class BodyDriveDecisionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session = Path(self.tmp.name) / "bridge.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def test_refusal_overrides_high_wanting_without_motor_action(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            ch = InstinctController.enable(loop)
            before = loop.body().checkpoint()["sha256"]
            ch.step({"id":"welcome", "source":"synthetic_fixture",
                     "relationship":"romantic", "adult_context":True,
                     "consent":"granted", "incentive":1})
            report = ch.step({"id":"refusal", "source":"synthetic_fixture",
                              "relationship":"romantic", "adult_context":True,
                              "consent":"refused", "incentive":1})
            self.assertGreater(report["synthetic"]["wanting"], 0.3)
            choice = advise(report)
            self.assertEqual(choice["proposal"], "respect_boundary")
            self.assertFalse(choice["actuation_authorized"])
            self.assertEqual(choice["native_cycles_caused"], 0)
            self.assertEqual(loop.body().checkpoint()["sha256"], before)
            self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_protection_before_exploration_and_rest_is_reversible(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            ch = InstinctController.enable(loop)
            report = ch.step({"id":"strain", "source":"synthetic_fixture",
                              "relationship":"romantic", "adult_context":True,
                              "consent":"granted", "incentive":.9,
                              "pain":.85, "stress":.9})
            self.assertEqual(advise(report)["proposal"], "regulate_and_rest")
            stopped = ch.disable()
            self.assertFalse(stopped["enabled"])
            self.assertEqual(loop.status()["actions_reserved"], 0)

    def test_family_affection_remains_nonsexual(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            ch = InstinctController.enable(loop)
            report = ch.step({"id":"family", "source":"synthetic_fixture",
                              "relationship":"familial", "warmth":1,
                              "incentive":1})
            self.assertEqual(report["synthetic"]["sexual_response_proxy"], 0)
            self.assertEqual(advise(report)["proposal"], "nonsexual_affiliation")

    def test_invalid_and_forged_inputs_fail_closed(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            report = InstinctController.enable(loop).step(
                {"id":"valid", "source":"synthetic_fixture", "novelty":.5})
            for field, val in (("decision_scope","actuate"), ("native_cycles_caused",1),
                               ("claim_scope","real_physiology")):
                bad = dict(report, **{field: val})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    advise(bad)
            bad = dict(report)
            bad["synthetic"] = dict(report["synthetic"], action="run_shell")
            with self.assertRaises(ValueError):
                advise(bad)
            bad = dict(report)
            bad["native_observation"] = dict(
                report["native_observation"], source="live_human")
            with self.assertRaises(ValueError):
                advise(bad)

    def test_cold_restart_is_consistent(self):
        with BodyLoop.start(self.session, mode="observe", max_actions=0) as loop:
            ch = InstinctController.enable(loop)
            original = ch.step({"id":"novelty", "source":"synthetic_fixture",
                                "novelty":.8})
            choice = advise(original)
        with BodyLoop(self.session) as loop:
            replay = InstinctController(loop).step(
                {"id":"novelty", "source":"synthetic_fixture", "novelty":.8})
            self.assertTrue(replay["replayed"])
            self.assertEqual(choice, advise(replay))
            self.assertEqual(loop.status()["completed_cycles"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
