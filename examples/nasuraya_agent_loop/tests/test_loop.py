import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_agent_loop.local import (
    Action, FixturePolicy, Journal, State, ToolHost, ToolRejected,
    evaluate, run_local, write_report,
)


class LocalLoopTests(unittest.TestCase):
    def host(self, **kwargs):
        return ToolHost(State(), Journal(), **kwargs)

    def test_complete_observe_choose_execute_evaluate_cycle(self):
        host = self.host()
        result = run_local(host)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["actions_used"], 5)
        self.assertEqual(result["final_state"], {
            "energy": 25, "heat": 70, "pending_jobs": 0, "completed_jobs": 3, "tick": 5})
        actions = [e["name"] for e in host.journal.events if e["kind"] == "action_selected"]
        self.assertEqual(actions, ["process_job", "recover", "process_job", "recover", "process_job"])
        self.assertEqual(sum(e["kind"] == "outcome_evaluated" for e in host.journal.events), 5)
        self.assertTrue(result["evaluation"]["goal_reached"])

    def test_independent_runs_produce_identical_entire_traces(self):
        first, second = self.host(), self.host()
        self.assertEqual(run_local(first), run_local(second))
        self.assertEqual(first.journal.events, second.journal.events)

    def test_cold_low_energy_and_hot_high_energy_choose_recovery(self):
        for state in [State(0, 0, 1), State(100, 100, 1)]:
            with self.subTest(state=state):
                host = ToolHost(state, Journal())
                self.assertEqual(run_local(host)["status"], "completed")
                first = next(e for e in host.journal.events if e["kind"] == "action_selected")
                self.assertEqual(first["name"], "recover")

    def test_observe_mode_rejects_mutation(self):
        host = self.host(mode="observe")
        self.assertEqual(run_local(host)["status"], "rejected")
        self.assertEqual(host.state, State())
        self.assertEqual(host.actions_used, 0)

    def test_host_budget_stops_even_with_larger_loop_budget(self):
        host = self.host(max_actions=2)
        result = run_local(host, max_steps=100)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["actions_used"], 2)
        self.assertEqual(host.state.pending_jobs, 2)

    def test_step_limit_reports_unmet_goal(self):
        result = run_local(self.host(), max_steps=1)
        self.assertEqual(result["status"], "step_limit")
        self.assertFalse(result["evaluation"]["goal_reached"])

    def test_zero_steps_and_already_complete(self):
        self.assertEqual(run_local(self.host(), max_steps=0)["status"], "step_limit")
        host = ToolHost(State(pending_jobs=0), Journal())
        self.assertEqual(run_local(host, max_steps=0)["status"], "completed")
        self.assertEqual(host.actions_used, 0)

    def test_empty_queue_with_unsafe_state_recovers_before_success(self):
        host = ToolHost(State(0, 100, 0), Journal())
        result = run_local(host)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["evaluation"]["safe"])

    def test_invalid_tool_inputs_never_mutate(self):
        cases = [("shell", {"command": "irrelevant"}), ("recover", {"ticks": 100}),
                 ("recover", {"ticks": True}), ("recover", {"ticks": 1.0}),
                 ("recover", {"ticks": 1, "path": "ignored"}),
                 ("recover", {}), ("observe_state", {"path": "ignored"}),
                 ("process_job", {"units": 3}), ("recover", "{}")]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                host = self.host()
                host.call("observe_state", {})
                with self.assertRaises(ToolRejected):
                    host.call(name, args)
                self.assertEqual(host.state, State())
                self.assertEqual(host.actions_used, 0)

    def test_fresh_observation_required_before_each_mutation(self):
        host = self.host()
        with self.assertRaises(ToolRejected):
            host.call("process_job", {})
        host.call("observe_state", {})
        host.call("process_job", {})
        with self.assertRaises(ToolRejected):
            host.call("recover", {"ticks": 1})

    def test_policy_cannot_mutate_host_through_observation(self):
        class BadPolicy:
            def choose(self, observation):
                observation["pending_jobs"] = 0
                return Action("process_job", {})
        host = self.host()
        run_local(host, BadPolicy(), max_steps=1)
        self.assertEqual(host.state.pending_jobs, 2)
        self.assertEqual(host.journal.events[1]["before"]["pending_jobs"], 3)

    def test_policy_exception_is_reported_without_message(self):
        class Broken:
            def choose(self, observation):
                raise RuntimeError("secret sentinel")
        host = self.host()
        self.assertEqual(run_local(host, Broken())["status"], "policy_error")
        self.assertNotIn("secret sentinel", json.dumps(host.journal.events))

    def test_tool_failure_is_not_success(self):
        host = self.host()
        original = host.call
        def broken(name, args):
            if name == "process_job":
                raise RuntimeError("failure")
            return original(name, args)
        with patch.object(host, "call", side_effect=broken):
            self.assertEqual(run_local(host)["status"], "tool_error")
        self.assertEqual(host.state, State())

    def test_state_and_limits_reject_invalid_values(self):
        for kwargs in [{"energy": -1}, {"energy": True}, {"heat": 101},
                       {"pending_jobs": 21}, {"pending_jobs": 20, "completed_jobs": 1}]:
            with self.assertRaises(ValueError):
                State(**kwargs)
        for kwargs in [{"mode": "anything"}, {"max_actions": -1}, {"max_actions": True}]:
            with self.assertRaises(ValueError):
                self.host(**kwargs)

    def test_recovery_clamps_and_preserves_jobs(self):
        host = ToolHost(State(95, 5, 2), Journal())
        host.call("observe_state", {})
        result = host.call("recover", {"ticks": 3})
        self.assertEqual((result["energy"], result["heat"], result["tick"]), (100, 0, 3))
        self.assertEqual((result["pending_jobs"], result["completed_jobs"]), (2, 0))

    def test_disk_journal_matches_memory_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            host = ToolHost(State(), Journal(path))
            result = run_local(host)
            self.assertEqual([json.loads(s) for s in path.read_text().splitlines()], host.journal.events)
            report = Path(directory) / "report.md"
            write_report(report, result, host.journal)
            self.assertIn("status: `completed`", report.read_text())
            with self.assertRaises(FileExistsError):
                Journal(path)
            with self.assertRaises(FileExistsError):
                write_report(report, result, host.journal)

    def test_cli_offline_needs_no_key_and_writes_reviewable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            import os
            env = dict(os.environ)
            env.pop("OPENAI_API_KEY", None)
            command = [sys.executable, "-m", "examples.nasuraya_agent_loop", "--output-dir", str(output)]
            proc = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["status"], "completed")
            self.assertEqual({p.name for p in output.iterdir()}, {"events.jsonl", "summary.json", "report.md"})
            self.assertNotEqual(subprocess.run(command, capture_output=True, env=env).returncode, 0)


if __name__ == "__main__":
    unittest.main()
