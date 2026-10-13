"""Contract fixtures derived from official docs; no network or model invocation."""

from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest

from examples.nasuraya_agent_loop.agents_api import PendingCalls, run_api
from examples.nasuraya_agent_loop.local import Journal, State, ToolHost, ToolRejected


def call(name, arguments=None, call_id="call-1", turn_id="turn-1"):
    return {"type": "function_call", "name": name, "arguments": arguments or {},
            "turn_id": turn_id, "call_id": call_id}


def requires(*actions, session_id="sess-1"):
    return {"type": "agent.session.requires_action",
            "session": {"id": session_id, "required_actions": list(actions)}}


def terminal(kind="completed", subagent_id=None):
    return {"type": f"agent.session.turn.{kind}",
            "turn": {"id": "turn-1", "subagent_id": subagent_id}}


class FakeStream:
    def __init__(self, events):
        self.events, self.closed = events, False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        return iter(self.events)

    def close(self):
        self.closed = True


class FakeSessions:
    def __init__(self, events, *, cleanup_fails=False, create_fails=False):
        self.stream_object = FakeStream(events)
        self.sent, self.deleted, self.created = [], [], []
        self.cleanup_fails, self.create_fails = cleanup_fails, create_fails
        self.events = SimpleNamespace(stream=self.stream, create=self.send)

    def create(self, **kwargs):
        self.created.append(kwargs)
        if self.create_fails:
            raise RuntimeError("secret sentinel")
        if kwargs.get("stream") is not True or not kwargs.get("input"):
            raise ValueError("none environment requires streamed initial input")
        self.stream_object.events = [{"type": "agent.session.created", "session": {"id": "sess-1"}}] + self.stream_object.events
        return self.stream_object

    def stream(self, session_id):
        return self.stream_object

    def send(self, session_id, *, events):
        self.sent.extend(events)

    def delete(self, session_id):
        if self.cleanup_fails:
            raise RuntimeError("secret sentinel")
        self.deleted.append(session_id)


class ApiContractTests(unittest.TestCase):
    def setup_run(self, events, state=None, **session_kwargs):
        host = ToolHost(state or State(pending_jobs=1), Journal())
        sessions = FakeSessions(events, **session_kwargs)
        client = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=sessions)))
        return host, sessions, client

    def test_required_actions_execute_and_return_matched_results(self):
        host, sessions, client = self.setup_run([
            requires(call("observe_state", call_id="o")),
            requires(call("process_job", call_id="p")),
            requires(call("evaluate_state", call_id="e")), terminal()])
        result = run_api(host, client, model="explicit-test-model")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(host.state.completed_jobs, 1)
        results = [r for r in sessions.sent if r["type"] == "agent.session.input.tool_result"]
        self.assertEqual([r["call_id"] for r in results], ["o", "p", "e"])
        self.assertTrue(all(r["success"] for r in results))
        self.assertTrue(json.loads(results[-1]["output"])["goal_reached"])
        self.assertEqual(sessions.created[0]["environment"], {"type": "none"})
        self.assertEqual(len(sessions.created[0]["agent"]["tools"]), 4)
        self.assertEqual(sessions.deleted, ["sess-1"])
        self.assertTrue(sessions.stream_object.closed)
        self.assertFalse(result["live_api_verified"])
        self.assertEqual(result["api_transport"], "injected_client")
        self.assertEqual(sum(e["kind"] == "outcome_evaluated" for e in host.journal.events), 1)

    def test_duplicate_mutation_reuses_result_without_repeating_side_effect(self):
        host, sessions, client = self.setup_run([
            requires(call("observe_state", call_id="o")),
            requires(call("process_job", call_id="p")),
            requires(call("process_job", call_id="p")), terminal()])
        result = run_api(host, client, model="test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(host.actions_used, 1)
        outputs = [r for r in sessions.sent if r.get("call_id") == "p"]
        self.assertEqual(outputs[0], outputs[1])

    def test_duplicate_id_with_new_payload_is_rejected(self):
        host, sessions, client = self.setup_run([
            requires(call("observe_state", call_id="o")),
            requires(call("process_job", call_id="p")),
            requires(call("recover", {"ticks": 1}, call_id="p")), terminal()])
        self.assertEqual(run_api(host, client, model="test")["status"], "rejected")
        self.assertEqual(host.actions_used, 1)

    def test_history_call_item_does_not_trigger_execution(self):
        host, sessions, client = self.setup_run([
            {"type": "agent.session.turn.item.completed", "item": call("process_job")}, terminal()])
        self.assertEqual(run_api(host, client, model="test")["status"], "goal_unmet")
        self.assertEqual(host.actions_used, 0)

    def test_idle_or_closed_stream_is_not_success(self):
        for events in [[], [{"type": "agent.session.idle"}]]:
            with self.subTest(events=events):
                host, sessions, client = self.setup_run(events)
                self.assertEqual(run_api(host, client, model="test")["status"], "stream_incomplete")
                self.assertEqual(sessions.deleted, ["sess-1"])

    def test_turn_complete_without_goal_is_goal_unmet(self):
        host, _, client = self.setup_run([terminal()])
        self.assertEqual(run_api(host, client, model="test")["status"], "goal_unmet")

    def test_reached_goal_without_completed_turn_is_incomplete(self):
        host, _, client = self.setup_run([
            requires(call("observe_state", call_id="o")), requires(call("process_job", call_id="p"))])
        result = run_api(host, client, model="test")
        self.assertTrue(result["evaluation"]["goal_reached"])
        self.assertEqual(result["status"], "stream_incomplete")

    def test_subagent_completion_does_not_end_top_level_turn(self):
        host, _, client = self.setup_run([terminal(subagent_id="other"), terminal("failed")])
        self.assertEqual(run_api(host, client, model="test")["status"], "api_failed")

    def test_failed_cancelled_and_session_error_are_distinct(self):
        for event, status in [(terminal("failed"), "api_failed"),
                              (terminal("cancelled"), "api_cancelled"),
                              ({"type": "error"}, "api_error"),
                              ({"type": "agent.session.failed"}, "api_error")]:
            with self.subTest(status=status):
                host, sessions, client = self.setup_run([event])
                self.assertEqual(run_api(host, client, model="test")["status"], status)
                self.assertEqual(sessions.deleted, ["sess-1"])

    def test_invalid_arguments_return_error_and_end_run(self):
        host, sessions, client = self.setup_run([
            requires(call("observe_state", call_id="o")),
            requires(call("recover", {"ticks": 999}, call_id="bad")), terminal()])
        self.assertEqual(run_api(host, client, model="test")["status"], "rejected")
        result = sessions.sent[-1]
        self.assertFalse(result["success"])
        self.assertEqual(result["call_id"], "bad")
        self.assertEqual(host.actions_used, 0)

    def test_session_mismatch_and_unsupported_action_are_rejected(self):
        for event in [requires(call("observe_state"), session_id="wrong"),
                      requires({"type": "approval"})]:
            host, _, client = self.setup_run([event])
            self.assertEqual(run_api(host, client, model="test")["status"], "rejected")
            self.assertEqual(host.actions_used, 0)

    def test_unique_call_budget_limits_read_only_spam(self):
        events = [requires(call("observe_state", call_id=str(i))) for i in range(3)]
        host, sessions, client = self.setup_run(events)
        self.assertEqual(run_api(host, client, model="test", max_calls=2)["status"], "rejected")
        self.assertEqual(len([r for r in sessions.sent if "call_id" in r]), 2)

    def test_event_limit_stops_repeated_idle_events(self):
        host, sessions, client = self.setup_run([{"type": "agent.session.idle"}] * 501)
        self.assertEqual(run_api(host, client, model="test")["status"], "event_limit")
        self.assertEqual(sessions.deleted, ["sess-1"])

    def test_action_budget_enforced_in_api_path(self):
        host, sessions, client = self.setup_run([
            requires(call("observe_state", call_id="o")), requires(call("process_job", call_id="p"))])
        host.max_actions = 0
        self.assertEqual(run_api(host, client, model="test")["status"], "rejected")
        self.assertEqual(host.actions_used, 0)

    def test_timeout_deletes_session_without_executing_late_action(self):
        host, sessions, client = self.setup_run([requires(call("process_job"))])
        ticks = iter([0, 100, 100])
        self.assertEqual(run_api(host, client, model="test", clock=lambda: next(ticks))["status"], "timeout")
        self.assertEqual(host.actions_used, 0)
        self.assertEqual(sessions.deleted, ["sess-1"])

    def test_creation_error_and_cleanup_failure_do_not_leak_messages(self):
        for kwargs in [{"create_fails": True}, {"cleanup_fails": True}]:
            host, sessions, client = self.setup_run([terminal()], **kwargs)
            run_api(host, client, model="test")
            self.assertNotIn("secret sentinel", json.dumps(host.journal.events))
            kind = "api_error" if "create_fails" in kwargs else "api_cleanup_failed"
            self.assertIn(kind, [e["kind"] for e in host.journal.events])

    def test_cleanup_failure_is_exposed_in_summary(self):
        host, _, client = self.setup_run([terminal()], cleanup_fails=True)
        result = run_api(host, client, model="test")
        self.assertEqual(result["cleanup_status"], "failed")
        self.assertEqual(result["session_id"], "sess-1")

    def test_busy_session_is_cancelled_before_delete_retry(self):
        host, sessions, client = self.setup_run([terminal()])
        attempts = []

        class BusySession(Exception):
            status_code = 409

        def delete(session_id):
            attempts.append(session_id)
            if len(attempts) == 1:
                raise BusySession()
            self.assertIn({"type": "agent.session.input.cancel"}, sessions.sent)
            sessions.deleted.append(session_id)

        sessions.delete = delete
        result = run_api(host, client, model="test")
        self.assertEqual(result["cleanup_status"], "deleted")
        self.assertEqual(attempts, ["sess-1", "sess-1"])
        self.assertEqual(sessions.deleted, ["sess-1"])

    def test_wrong_terminal_turn_cannot_claim_success_after_goal(self):
        wrong = terminal()
        wrong["turn"]["id"] = "wrong-turn"
        host, _, client = self.setup_run([
            requires(call("observe_state", call_id="o")),
            requires(call("process_job", call_id="p")), wrong])
        result = run_api(host, client, model="test")
        self.assertTrue(result["evaluation"]["goal_reached"])
        self.assertEqual(result["status"], "rejected")

    def test_wrong_action_turn_is_rejected_before_mutation(self):
        host, _, client = self.setup_run([
            requires(call("observe_state", call_id="o")),
            requires(call("process_job", call_id="p", turn_id="wrong-turn"))])
        self.assertEqual(run_api(host, client, model="test")["status"], "rejected")
        self.assertEqual(host.actions_used, 0)

    def test_missing_terminal_identity_is_rejected(self):
        host, _, client = self.setup_run([{"type":"agent.session.turn.completed", "turn":{}}])
        self.assertEqual(run_api(host, client, model="test")["status"], "rejected")

    def test_session_disables_subagent_tools_in_configuration(self):
        host, sessions, client = self.setup_run([terminal()])
        run_api(host, client, model="test")
        self.assertEqual(sessions.created[0]["agent"]["multi_agent"], {"enabled": False})


if __name__ == "__main__":
    unittest.main()
