"""Persistence, replay, checkpoint coupling and non-actuation acceptance tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .host import BodyLoop
from .autonomic_recovery_memory import RecoveryMemory
from .instinct import InstinctController


class AutonomicRecoveryMemoryTests(unittest.TestCase):
    def test_opt_in_required_and_source_is_real_software_checkpoint(self):
        with TemporaryDirectory() as tmp:
            with BodyLoop.start(Path(tmp) / "memory.sqlite",
                                fixture="normal", mode="observe", max_actions=0) as loop:
                before = loop.body().checkpoint()["sha256"]
                with self.assertRaisesRegex(ValueError, "not enabled"):
                    RecoveryMemory(loop)
                controller = RecoveryMemory.enable(loop)
                status = controller.status()
                self.assertTrue(status["enabled"])
                self.assertEqual(status["baseline_sha256"], before)
                self.assertEqual(status["events_recorded"], 0)
                self.assertEqual(status["projected_autonomic_state"],
                                 InstinctController.enable(loop).status()["native_body"]["values"])
                self.assertEqual(loop.body().checkpoint()["sha256"], before)
                self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_forecast_persists_across_cold_restart_without_body_cycles(self):
        with TemporaryDirectory() as tmp:
            session = Path(tmp) / "memory.sqlite"
            with BodyLoop.start(session, fixture="normal", mode="observe", max_actions=0) as loop:
                initial_hash = loop.body().checkpoint()["sha256"]
                recovery = RecoveryMemory.enable(loop)
                one = recovery.step("recover-1", steps=4)
                first_status = recovery.status()
                self.assertFalse(one["actuation_authorized"])
                self.assertFalse(one["replayed"])
                self.assertEqual(one["native_cycles_caused"], 0)
                self.assertEqual(first_status["events_recorded"], 1)
                self.assertTrue(first_status["native_checkpoint_unchanged"])
            with BodyLoop(session) as loop:
                recovery = RecoveryMemory(loop)
                self.assertEqual(recovery.status()["projected_autonomic_state"],
                                 first_status["projected_autonomic_state"])
                prior = recovery.step("recover-1", steps=4)
                self.assertTrue(prior["replayed"])
                self.assertEqual(recovery.status()["events_recorded"], 1)
                self.assertEqual(recovery.status()["baseline_sha256"], initial_hash)
                next_step = recovery.step("recover-2", steps=1)
                self.assertEqual(recovery.status()["events_recorded"], 2)
                self.assertEqual(next_step["trajectory"][0]["sympathetic"],
                                 first_status["projected_autonomic_state"]["sympathetic"])
                self.assertEqual(loop.body().checkpoint()["sha256"], initial_hash)
                self.assertEqual(loop.status()["actions_reserved"], 0)
                self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_conflicting_replay_and_invalid_requests_do_not_mutate(self):
        with TemporaryDirectory() as tmp:
            with BodyLoop.start(Path(tmp) / "memory.sqlite",
                                mode="observe", max_actions=0) as loop:
                recovery = RecoveryMemory.enable(loop)
                recovery.step("one", steps=2)
                expected = recovery.status()
                for event, steps in (("one", 3), ("bad id", 1), ("two", 0),
                                     ("two", 21), ("two", True)):
                    with self.subTest(event=event, steps=steps):
                        with self.assertRaises(ValueError):
                            recovery.step(event, steps=steps)
                self.assertEqual(recovery.status(), expected)

    def test_disable_stops_steps_and_preserves_memory(self):
        with TemporaryDirectory() as tmp:
            with BodyLoop.start(Path(tmp) / "memory.sqlite",
                                mode="observe", max_actions=0) as loop:
                recovery = RecoveryMemory.enable(loop)
                recovery.step("one")
                stopped = recovery.disable()
                self.assertFalse(stopped["enabled"])
                with self.assertRaisesRegex(ValueError, "disabled"):
                    recovery.step("two")
                restored = RecoveryMemory.enable(loop)
                self.assertTrue(restored.status()["enabled"])
                self.assertEqual(restored.status()["events_recorded"], 1)
                self.assertEqual(loop.status()["completed_cycles"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
