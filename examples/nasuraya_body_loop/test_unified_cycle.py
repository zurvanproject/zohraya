"""Regression: one native software receipt is shared across all Tadash layers."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reflection_cycle import InterruptedExecution
from .host import BodyLoop, UnifiedBody
from .experience import ExperienceController, KEY
from . import unified_cycle


class UnifiedCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "unified.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def test_enable_is_opt_in_atomic_as_to_native_actions_and_idempotent(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            before = loop.status()
            ready = unified_cycle.enable(loop, desire_proxy=.6)
            self.assertTrue(ready["synchronized"])
            self.assertEqual(ready["completed_cycles"], 0)
            self.assertEqual(ready["actions_remaining"], before["actions_remaining"])
            self.assertEqual(loop.status()["actions_reserved"], 0)
            self.assertEqual(unified_cycle.enable(loop, desire_proxy=.6), ready)
            with self.assertRaisesRegex(ValueError, "another authored"):
                unified_cycle.enable(loop, desire_proxy=.9)
            self.assertEqual(loop.status()["actions_reserved"], 0)

    def test_invalid_proxy_cannot_create_experience_state(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            with self.assertRaises(ValueError):
                unified_cycle.enable(loop, desire_proxy=float("nan"))
            self.assertIsNone(loop.engine.db.execute(
                "SELECT value FROM meta WHERE key=?", (KEY,)).fetchone())
            self.assertEqual(loop.status()["actions_reserved"], 0)

    def test_five_stage_trace_and_shared_source_in_two_body_conditions(self):
        for fixture in ("normal", "sleep"):
            path = Path(self.tmp.name) / (fixture + ".sqlite")
            with BodyLoop.start(path, fixture=fixture, max_actions=2) as loop:
                unified_cycle.enable(loop, desire_proxy=.8)
                c = ExperienceController(loop)
                first = unified_cycle.step(c, "first")
                self.assertEqual(first["native_cycles_in_this_call"], 1)
                self.assertIn("body", first)
                self.assertIn("need", first)
                self.assertIn("memory", first)
                self.assertIn("decision", first)
                self.assertIn("learning", first)
                self.assertTrue(first["learning"]["all_layers_synchronized"])
                self.assertEqual(first["learning"]["learned_in_this_call"], 1)
                self.assertIn("native-decision://", first["learning"]["observed_native_source"])
                state = c.status()["state"]
                expected = [(e["id"], e["source"]) for e in state["episodes"]]
                for layer in unified_cycle.LAYERS:
                    actual = [(r["id"], r["source"]) for r in state[layer]["receipts"]]
                    self.assertEqual(actual, expected)
                self.assertEqual(first["need"]["pressure"]["energy_deficit"],
                                 round(1. - first["body"]["before"]["energy"], 7))
                self.assertEqual(first["decision"]["native_actual"],
                                 state["episodes"][-1]["actual_action"])
                if fixture == "sleep":
                    self.assertEqual(first["decision"]["final_requested"], "observe")
                second = unified_cycle.step(c, "second")
                self.assertEqual(second["learning"]["total_receipt_grounded_cycles"], 2)
                self.assertEqual(loop.status()["actions_remaining"], 0)
                self.assertFalse(second["subjective_experience_inferred"])

    def test_cold_restart_replay_does_not_learn_twice(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            unified_cycle.enable(loop, desire_proxy=.5)
            first = unified_cycle.step(ExperienceController(loop), "one")
            source = first["learning"]["observed_native_source"]
        with BodyLoop(self.path) as loop:
            c = ExperienceController(loop)
            self.assertTrue(unified_cycle.status(c)["synchronized"])
            replay = unified_cycle.step(c, "one")
            self.assertEqual(replay["learning"]["observed_native_source"], source)
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["native_cycles_in_this_call"], 0)
            self.assertEqual(replay["learning"]["learned_in_this_call"], 0)
            second = unified_cycle.step(c, "two")
            self.assertEqual(second["learning"]["learned_in_this_call"], 1)
            self.assertEqual(unified_cycle.status(c)["completed_cycles"], 2)

    def test_reconcile_crash_after_native_completion_without_reexecution(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            unified_cycle.enable(loop)
            c = ExperienceController(loop)
            with patch.object(c, "_finish", side_effect=RuntimeError("crash before cognitive save")):
                with self.assertRaises(RuntimeError):
                    unified_cycle.step(c, "one")
            self.assertEqual(loop.status()["completed_cycles"], 1)
        with BodyLoop(self.path) as loop:
            c = ExperienceController(loop)
            pending = unified_cycle.status(c)
            self.assertFalse(pending["synchronized"])
            self.assertEqual(pending["pending_intents"], ["one"])
            resumed = unified_cycle.step(c, "one")
            self.assertTrue(resumed["replayed"])
            self.assertEqual(resumed["native_cycles_in_this_call"], 0)
            self.assertEqual(resumed["learning"]["learned_in_this_call"], 1)
            self.assertTrue(unified_cycle.status(c)["synchronized"])
            self.assertEqual(loop.status()["completed_cycles"], 1)
            self.assertEqual(loop.status()["actions_reserved"], 1)

    def test_executor_failure_cannot_forge_learning(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            unified_cycle.enable(loop)
            c = ExperienceController(loop)
            with patch.object(UnifiedBody, "cycle", side_effect=RuntimeError("native failure")):
                failed = unified_cycle.step(c, "fail")
            self.assertNotEqual(failed["native_receipt_status"], "complete")
            self.assertIsNone(failed["body"]["observed_after"])
            self.assertIsNone(failed["learning"]["observed_native_source"])
            self.assertEqual(failed["learning"]["learned_in_this_call"], 0)
            self.assertTrue(unified_cycle.status(c)["synchronized"])

    def test_out_of_band_body_action_refused(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            unified_cycle.enable(loop)
            c = ExperienceController(loop)
            loop.observe()
            direct = loop.step(decision_id="direct-bypass", preferred_action="observe")
            self.assertEqual(direct["status"], "complete")
            self.assertFalse(unified_cycle.status(c)["synchronized"])
            with self.assertRaises(InterruptedExecution):
                unified_cycle.step(c, "after-bypass")

    def test_legacy_experience_with_existing_action_cannot_be_backfilled(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            c.step("earlier")
            with self.assertRaisesRegex(ValueError, "before any native action"):
                unified_cycle.enable(loop)
            self.assertNotIn("neurovisceral", c.status()["state"])

    def test_refuses_observe_only_body(self):
        with BodyLoop.start(self.path, mode="observe", max_actions=0) as loop:
            with self.assertRaisesRegex(ValueError, "bounded"):
                unified_cycle.enable(loop)


if __name__ == "__main__":
    unittest.main()
