"""Optional real-SDK serialization and SSE tests using an in-memory transport.

No live key, socket, API request, or model inference is involved.
"""

import importlib.util
import json
import unittest

from examples.nasuraya_agent_loop.agents_api import run_api
from examples.nasuraya_agent_loop.local import Journal, State, ToolHost


SDK_AVAILABLE = bool(importlib.util.find_spec("openai") and importlib.util.find_spec("httpx2"))


def required(name, index, arguments=None):
    return {"type": "agent.session.requires_action", "session": {
        "id": "sess-sdk-test", "required_actions": [{"type": "function_call",
        "turn_id": "turn-sdk-test", "call_id": f"call-{index}",
        "name": name, "arguments": arguments or {}}]}}


def completed():
    return {"type": "agent.session.turn.completed", "turn": {
        "id": "turn-sdk-test", "subagent_id": None}}


@unittest.skipUnless(SDK_AVAILABLE, "optional SDK dependencies not installed")
class InstalledSDKTests(unittest.TestCase):
    def execute(self, events, *, create_status=200):
        import httpx2
        from openai import OpenAI
        captured = []
        creation = {"type": "agent.session.created", "session": {"id": "sess-sdk-test"}}
        stream_body = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
                              for event in [creation] + events).encode()

        def respond(request):
            body = json.loads(request.content) if request.content else None
            captured.append({"method": request.method, "path": request.url.path,
                             "beta": request.headers.get("OpenAI-Beta"), "body": body})
            if request.method == "POST" and request.url.path == "/v1/agents/sessions":
                if create_status != 200:
                    return httpx2.Response(create_status, json={"error": {
                        "message": "sensitive sentinel", "type": "authentication_error",
                        "code": "invalid_api_key"}})
                if body.get("stream") is not True or not body.get("input"):
                    return httpx2.Response(400, json={"error": {"code": "missing_initial_input"}})
                return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=stream_body)
            if request.method == "GET" and request.url.path.endswith("/events"):
                return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=stream_body)
            if request.method == "POST" and request.url.path.endswith("/events"):
                return httpx2.Response(202)
            if request.method == "DELETE":
                return httpx2.Response(200, json={"id": "sess-sdk-test", "deleted": True})
            raise AssertionError("unexpected SDK request")

        http_client = httpx2.Client(transport=httpx2.MockTransport(respond), trust_env=False)
        host = ToolHost(State(), Journal(), max_actions=5)
        with OpenAI(api_key="in-memory-transport-only", http_client=http_client, max_retries=0) as client:
            result = run_api(host, client, model="fixture-model")
        return host, result, captured

    def test_real_sdk_serializes_calls_and_decodes_sse_through_full_loop(self):
        events, index = [], 0
        for name in ["process_job", "recover", "process_job", "recover", "process_job"]:
            index += 1
            events.append(required("observe_state", index))
            index += 1
            events.append(required(name, index, {"ticks": 1} if name == "recover" else {}))
        events.append(completed())
        host, result, captured = self.execute(events)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(host.actions_used, 5)
        self.assertEqual(host.state.completed_jobs, 3)
        self.assertFalse(result["live_api_verified"])
        self.assertTrue(all(request["beta"] == "agents=v1" for request in captured))
        self.assertEqual(captured[0]["body"]["environment"], {"type": "none"})
        self.assertTrue(captured[0]["body"]["stream"])
        self.assertTrue(captured[0]["body"]["input"])
        self.assertFalse(any(r["method"] == "GET" for r in captured))
        outputs = [r["body"]["events"][0] for r in captured
                   if r["method"] == "POST" and r["path"].endswith("/events")]
        self.assertEqual(len(outputs), 10)
        self.assertTrue(all(r["type"] == "agent.session.input.tool_result" and r["success"] for r in outputs))
        self.assertEqual(captured[-1]["method"], "DELETE")

    def test_real_sdk_rejection_returns_matching_error_then_deletes_session(self):
        host, result, captured = self.execute([
            required("observe_state", 1), required("recover", 2, {"ticks": 99}), completed()])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(host.actions_used, 0)
        response = captured[-2]["body"]["events"][0]
        self.assertFalse(response["success"])
        self.assertEqual(response["call_id"], "call-2")
        self.assertEqual(captured[-1]["method"], "DELETE")

    def test_real_sdk_http_auth_error_is_reported_without_message(self):
        host, result, captured = self.execute([], create_status=401)
        self.assertEqual(result["status"], "api_error")
        self.assertEqual(len(captured), 1)
        self.assertNotIn("sensitive sentinel", json.dumps(host.journal.events))
        error = next(e for e in host.journal.events if e["kind"] == "api_error")
        self.assertEqual(error["http_status"], 401)
        self.assertEqual(error["api_code"], "invalid_api_key")

    def test_real_sdk_closed_idle_stream_does_not_report_success(self):
        _, result, captured = self.execute([{"type": "agent.session.idle"}])
        self.assertEqual(result["status"], "stream_incomplete")
        self.assertEqual(captured[-1]["method"], "DELETE")


if __name__ == "__main__":
    unittest.main()
