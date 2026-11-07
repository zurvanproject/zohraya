"""Safety, restart, attention broadcast and feedback tests for real software BodyLoop.

No LLM, tokens, tool access, physical actuation or background tasks.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reflection_cycle import InterruptedExecution
from .experience import ExperienceController, KEY, plan
from .host import BodyLoop, UnifiedBody
from . import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "native.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def test_old_experience_sessions_remain_unmodified_without_opt_in(self):
        with BodyLoop.start(self.path, fixture="sleep", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            self.assertIsNone(c.status()["integrated_workspace"])
            first = c.step("one")
            self.assertEqual(first["plan"]["preferred"], "walk")
            self.assertEqual(first["native_receipt"]["actual_action"], "protect")
            self.assertNotIn("workspace", c.status()["state"])

    def test_workspace_integrates_real_observations_and_changes_preference(self):
        with BodyLoop.start(self.path, fixture="sleep", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            remaining = loop.status()["actions_remaining"]
            enabled = c.enable_workspace()
            self.assertEqual(remaining, loop.status()["actions_remaining"])
            self.assertEqual(enabled["learned_native_cycles"], 0)
            first = c.step("one")
            self.assertEqual(first["plan"]["base_preferred"], "walk")
            self.assertEqual(first["plan"]["preferred"], "observe")
            self.assertEqual(first["plan"]["workspace"]["reason"], "high_body_load")
            self.assertEqual(first["native_receipt"]["actual_action"], "observe")
            self.assertEqual(first["plan"]["action_forecast"]["preferred"], "observe")
            self.assertIn("safety", first["plan"]["workspace"]["attention"])
            self.assertEqual(first["plan"]["workspace"]["broadcast"]["planner"],
                             first["plan"]["workspace"]["broadcast"]["memory"])
            self.assertEqual(first["plan"]["workspace"]["broadcast"]["planner"],
                             first["plan"]["workspace"]["broadcast"]["monitor"])
            summary = c.status()["integrated_workspace"]
            self.assertEqual(summary["learned_native_cycles"], 1)
            self.assertEqual(summary["retained_recent_receipts"], 1)
            self.assertEqual(summary["api_calls"], 0)

    def test_normal_workload_does_not_block_walk(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            first = c.step("one")
            self.assertEqual(first["plan"]["preferred"], "walk")
            self.assertEqual(first["plan"]["workspace"]["reason"], "base_policy")
            self.assertEqual(first["native_receipt"]["actual_action"], "walk")

    def test_cold_restart_recovers_working_memory_without_replaying_native(self):
        with BodyLoop.start(self.path, fixture="sleep", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            c.step("one")
            saved = deepcopy(c.status()["state"]["workspace"])
        with BodyLoop(self.path) as loop:
            c = ExperienceController(loop)
            self.assertEqual(c.status()["state"]["workspace"], saved)
            second = c.step("two")
            self.assertEqual(second["plan"]["workspace"]["prior_feedback_count"], 1)
            count = c.status()["integrated_workspace"]["learned_native_cycles"]
            replay = c.step("one")
            self.assertTrue(replay["replayed"])
            self.assertEqual(c.status()["integrated_workspace"]["learned_native_cycles"], count)
            self.assertEqual(loop.status()["completed_cycles"], 2)

    def test_enable_does_not_reset_budget_or_existing_episodes(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            c.step("one")
            previous = c.status()
            c.enable_workspace()
            self.assertEqual(loop.status()["actions_remaining"], previous["native"]["actions_remaining"])
            self.assertEqual(len(c.status()["state"]["episodes"]), 1)
            c.enable_workspace()
            self.assertEqual(c.status()["integrated_workspace"]["learned_native_cycles"], 0)

    def test_pending_native_intent_blocks_workspace_enable(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            with patch.object(loop, "step", side_effect=RuntimeError("before native call")):
                with self.assertRaises(RuntimeError):
                    c.step("one")
            with self.assertRaises(InterruptedExecution):
                c.enable_workspace()
            self.assertNotIn("workspace", c.status()["state"])
            c.step("one")

    def test_failed_native_cycle_does_not_fabricate_learning(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            with patch.object(UnifiedBody, "cycle", side_effect=RuntimeError("software-body failure")):
                r = c.step("one")
            self.assertEqual(r["native_receipt"]["status"], "executor_failed")
            self.assertEqual(c.status()["integrated_workspace"]["learned_native_cycles"], 0)
            self.assertEqual(c.status()["state"]["episodes"], [])

    def test_native_outcome_reserved_workspace_plan_is_frozen_before_step(self):
        with BodyLoop.start(self.path, fixture="sleep", max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            def before_execution(**kwargs):
                reserved = c._load()["intents"]["one"]
                self.assertIsNone(reserved["result"])
                p = reserved["plan"]
                self.assertIn("workspace", p)
                self.assertEqual(p["workspace"]["preferred"], "observe")
                self.assertNotIn("actual", p["workspace"])
                self.assertEqual(loop.status()["completed_cycles"], 0)
                raise RuntimeError("stop before native action")
            with patch.object(loop, "step", side_effect=before_execution):
                with self.assertRaisesRegex(RuntimeError, "stop before native"):
                    c.step("one")
            saved_plan = deepcopy(c._load()["intents"]["one"]["plan"])
            out = c.step("one")
            self.assertEqual(out["plan"], saved_plan)
            self.assertEqual(c.status()["integrated_workspace"]["learned_native_cycles"], 1)

    def test_tampered_workspace_envelope_is_rejected(self):
        with BodyLoop.start(self.path, fixture="normal", max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            c.step("one")
            meta = loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()[0]
            envelope = json.loads(meta)
            envelope["value"]["workspace"]["sequence"] = 99
            loop.engine.db.execute("UPDATE meta SET value=? WHERE key=?",
                                   (json.dumps(envelope), KEY))
            with self.assertRaisesRegex(ValueError, "integrity"):
                c.status()

    def test_memory_downgrades_walk_in_nearby_context_after_native_harm(self):
        snapshot = {"minimum_state": dict(energy=.8, fatigue=.1, pain=.1, sleep_pressure=.1)}
        base = dict(preferred="walk", prediction=dict(prior_samples=2))
        memory = workspace.initial()
        initial_plan = workspace.prepare(memory, snapshot, base)
        memory = workspace.record(memory, "past", initial_plan, snapshot,
                                  "protect", "native-decision://past/receipt", .1, 1.)
        later = {"minimum_state": dict(energy=.79, fatigue=.11, pain=.1, sleep_pressure=.1)}
        p = workspace.prepare(memory, later, base)
        self.assertEqual(p["preferred"], "observe")
        self.assertEqual(p["reason"], "prior_harm")
        self.assertEqual(p["retrieved_receipt_ids"], ["past"])
        self.assertEqual(workspace.summary(memory)["learned_native_cycles"], 1)

    def test_does_not_escalate_observe_to_walk(self):
        state = workspace.initial()
        snapshot = {"minimum_state": dict(energy=.8, fatigue=.1, pain=.1, sleep_pressure=.1)}
        p = workspace.prepare(state, snapshot, dict(preferred="observe", prediction=dict(prior_samples=2)))
        self.assertEqual(p["preferred"], "observe")

    def test_bounded_memory_and_duplicate_guard(self):
        state = workspace.initial()
        snapshot = {"minimum_state": dict(energy=.8, fatigue=.1, pain=.1, sleep_pressure=.1)}
        p = workspace.prepare(state, snapshot, dict(preferred="walk", prediction=dict(prior_samples=1)))
        for i in range(33):
            state = workspace.record(state, str(i), p, snapshot, "walk",
                                     "native-decision://x/receipt", .01, 0.)
        self.assertEqual(workspace.summary(state)["learned_native_cycles"], 33)
        self.assertEqual(workspace.summary(state)["retained_recent_receipts"], 32)
        self.assertEqual(state["receipts"][0]["id"], "1")
        with self.assertRaises(ValueError):
            workspace.record(state, "32", p, snapshot, "walk",
                             "native-decision://x/receipt", .01, 0.)

    def test_invalid_nonfinite_body_or_forged_output_rejected(self):
        state = workspace.initial()
        with self.assertRaises(ValueError):
            workspace.prepare(state, {"minimum_state": {"energy": float("nan"),
                "fatigue": .1, "pain": .1, "sleep_pressure": .1}},
                dict(preferred="walk", prediction=dict(prior_samples=1)))
        snapshot = {"minimum_state": dict(energy=.8, fatigue=.1, pain=.1, sleep_pressure=.1)}
        p = workspace.prepare(state, snapshot, dict(preferred="walk", prediction=dict(prior_samples=1)))
        with self.assertRaises(ValueError):
            workspace.record(state, "x", p, snapshot, "walk", "untrusted-source", .1, 0.)
        p["broadcast"]["memory"] = ["different"]
        with self.assertRaises(ValueError):
            workspace.record(state, "x", p, snapshot, "walk",
                             "native-decision://trusted/receipt", .1, 0.)


if __name__ == "__main__":
    unittest.main()
