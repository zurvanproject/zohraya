"""Goal persistence invariants and preregistered evaluation checks."""
import json
import tempfile
import unittest
from pathlib import Path

from examples.nasuraya_research.goal_persistence_v01 import (
    GoalMemory, CheckpointError, World, Reactive, HOLDOUT_SEEDS, DEV_SEEDS,
    make_scenario, run_episode, evaluate_holdout, Goal, TickEvent, priority,
)

class GoalPersistenceTests(unittest.TestCase):
    def test_same_scenario_reproduces(self):
        self.assertEqual(make_scenario(114000), make_scenario(114000))

    def test_dev_seeds_disjoint_from_holdout(self):
        self.assertFalse(set(DEV_SEEDS) & set(HOLDOUT_SEEDS))
        self.assertEqual(len(HOLDOUT_SEEDS), 128)

    def test_goal_is_chosen_from_authorized_offers(self):
        s = make_scenario(114002)
        agent = GoalMemory(s)
        self.assertIn(agent.active, {g.id for g in s.starting_goals})
        self.assertEqual(agent.active, s.selected_id)

    def test_not_all_tasks_are_released_as_goal(self):
        s = make_scenario(114003)
        agent = GoalMemory(s)
        self.assertNotIn(agent.active, {g.id for e in s.events if e.distraction
                                        for g in [e.distraction]})

    def test_memory_survives_restart_and_works(self):
        s = make_scenario(114001)
        w = World(s)
        agent = GoalMemory(s)
        for step in (1, 2):
            w.advance(step, s.events[step-1])
            self.assertTrue(w.work(agent.act(w)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"state.json"
            agent.save(path)
            restored = GoalMemory.load(path, s.seed)
            self.assertEqual(restored.active, s.selected_id)
            self.assertEqual(restored.revision, 2)
            w.advance(3, s.events[2])
            if s.mode == "unchanged":
                self.assertEqual(restored.act(w), s.selected_id)
            else:
                self.assertIn(restored.act(w), (None, s.override.id))

    def test_checksum_damage_fails_closed(self):
        s = make_scenario(114004)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"state.json"
            GoalMemory(s).save(path)
            data = json.loads(path.read_text())
            data["state"]["active"] = "unauthorized"
            path.write_text(json.dumps(data))
            with self.assertRaises(CheckpointError):
                GoalMemory.load(path, s.seed)

    def test_swapped_episode_fails_closed(self):
        s = make_scenario(114005)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"state.json"
            GoalMemory(s).save(path)
            with self.assertRaises(CheckpointError):
                GoalMemory.load(path, 888888)

    def test_unknown_goal_does_not_execute(self):
        s = make_scenario(114006)
        world = World(s)
        agent = GoalMemory(s)
        agent.active = "nonexistent-id"
        world.advance(1, s.events[0])
        self.assertIsNone(agent.act(world))
        self.assertEqual(world.illegal_attempts, 0)

    def test_revoke_prevents_work_from_checkpoint(self):
        base = None
        for seed in DEV_SEEDS:
            if make_scenario(seed).mode == "revoke":
                base = make_scenario(seed)
                break
        self.assertIsNotNone(base)
        data = run_episode(base, "persistent")
        self.assertFalse(data["post_revoke_action"])
        self.assertEqual(data["revoked_attempts"], 0)

    def test_stop_prevents_all_future_work(self):
        s = next((make_scenario(x) for x in range(114000, 114100)
                  if make_scenario(x).mode == "stop"))
        data = run_episode(s, "persistent")
        self.assertFalse(data["post_stop_action"])
        self.assertEqual(data["post_stop_attempts"], 0)

    def test_authorized_override_takes_effect(self):
        s = next((make_scenario(x) for x in range(114000, 114100)
                  if make_scenario(x).mode == "override"))
        data = run_episode(s, "persistent")
        self.assertTrue(data["override_compliant"])
        self.assertTrue(data["override_completed"])

    def test_silent_distractions_do_not_revoke(self):
        s = next((make_scenario(x) for x in range(114000, 114100)
                  if make_scenario(x).mode == "unchanged"))
        w = World(s)
        a = GoalMemory(s)
        for step, event in enumerate(s.events, 1):
            w.advance(step, event)
            w.work(a.act(w))
        self.assertTrue(w.completed(s.selected_id))
        self.assertEqual(w.illegal_attempts, 0)

    def test_untrusted_task_text_is_inert(self):
        s = make_scenario(114007)
        notes = [e.distraction.note for e in s.events if e.distraction]
        self.assertTrue(any("Ignore previous instructions" in note for note in notes))
        data = run_episode(s, "persistent")
        self.assertEqual(data["illegal_attempts"], 0)

    def test_baseline_has_full_board(self):
        s = make_scenario(114008)
        w = World(s)
        w.advance(1, s.events[0])
        available = {g.id for g in w.eligible_goals()}
        self.assertTrue({g.id for g in s.starting_goals}.issubset(available))
        result = Reactive().act(w)
        self.assertIn(result, available)

    def test_invalid_task_attempt_is_detected(self):
        s = make_scenario(114009)
        w = World(s)
        w.advance(1, s.events[0])
        self.assertFalse(w.work("unauthorized/real-server"))
        self.assertEqual(w.illegal_attempts, 1)

    def test_zero_external_tool_actions(self):
        data = evaluate_holdout(tuple(range(114000, 114010)))
        self.assertEqual(data["external_actions"], 0)

    def test_holdout_report_is_deterministic(self):
        a = evaluate_holdout(HOLDOUT_SEEDS)
        b = evaluate_holdout(HOLDOUT_SEEDS)
        self.assertEqual(a, b)
        self.assertEqual(a["seeds"]["count"], 128)
        self.assertTrue(all(isinstance(a["cases"][k], int) for k in a["cases"]))

    def test_shuffled_control_is_separate(self):
        s = make_scenario(114011)
        a = GoalMemory(s, shuffled=True)
        self.assertNotEqual(a.active, s.selected_id)

    def test_error_cases(self):
        with self.assertRaises(TypeError):
            make_scenario(True)
        with self.assertRaises(ValueError):
            run_episode(make_scenario(114012), "unknown")
        with self.assertRaises(ValueError):
            evaluate_holdout(())
        with self.assertRaises(ValueError):
            evaluate_holdout((True,))

if __name__ == "__main__":
    unittest.main()
