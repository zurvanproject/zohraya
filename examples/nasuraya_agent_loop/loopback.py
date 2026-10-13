"""Local protocol fixture: real HTTP/SSE, scripted selection, no model inference.

Listen only on 127.0.0.1, allocate a temporary port, and stop after the evaluation.
No cloud API key, repository access, or external network connection is used.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from queue import Queue, Empty
from threading import Thread

from .agents_api import run_api
from .local import FixturePolicy, Journal, State, ToolHost


class ProtocolFixture:
    def __init__(self, scenario):
        self.scenario = scenario
        self.queue, self.requests, self.seen = Queue(), [], set()
        self.call_index = 0
        self.calls = {}
        self.duplicated = False

    def emit_call(self, name, arguments=None):
        self.call_index += 1
        call_id = f"call-{self.call_index}"
        action = {"type":"function_call", "turn_id":"turn-loopback", "call_id":call_id,
                  "name":name, "arguments":arguments or {}}
        self.calls[call_id] = action
        event = {"type":"agent.session.requires_action", "session":{
            "id":"sess-loopback", "required_actions":[action]}}
        self.queue.put(event)
        if self.scenario == "duplicate" and name == "process_job" and not self.duplicated:
            self.queue.put(event)
            self.duplicated = True

    def terminal(self, kind="completed"):
        turn_id = "wrong-turn" if self.scenario == "wrong_turn" else "turn-loopback"
        self.queue.put({"type":f"agent.session.turn.{kind}",
                        "turn":{"id":turn_id,"subagent_id":None}})
        self.queue.put(None)

    def accept(self, event):
        if event["type"] == "agent.session.input.message":
            self.emit_call("observe_state")
            return
        call_id = event["call_id"]
        if call_id in self.seen:
            return
        self.seen.add(call_id)
        if not event["success"]:
            self.terminal("failed")
            return
        action, output = self.calls[call_id], json.loads(event["output"])
        if action["name"] == "observe_state":
            if self.scenario == "unknown_tool":
                self.emit_call("run_shell", {"command":"fixture-only"})
            elif output["pending_jobs"] == 0:
                self.emit_call("evaluate_state")
            else:
                # This is explicitly a scripted protocol fixture, not a live LLM.
                chosen = FixturePolicy().choose(output)
                self.emit_call(chosen.name, chosen.arguments)
        elif action["name"] in ("recover", "process_job"):
            if self.scenario == "incomplete" and action["name"] == "process_job":
                self.queue.put(None)
            else:
                self.emit_call("evaluate_state")
        elif action["name"] == "evaluate_state":
            if output["goal_reached"]:
                self.terminal()
            else:
                self.emit_call("observe_state")


@contextmanager
def local_fixture(scenario):
    fixture = ProtocolFixture(scenario)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def respond(self, status, body=None):
            payload = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            fixture.requests.append(("POST", self.path))
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100000:
                self.respond(413)
                return
            body = json.loads(self.rfile.read(length))
            if self.path == "/v1/agents/sessions":
                assert body["environment"] == {"type":"none"}
                assert body["agent"]["multi_agent"] == {"enabled":False}
                self.respond(200,{"id":"sess-loopback"})
            elif self.path == "/v1/agents/sessions/sess-loopback/events":
                for event in body["events"]:
                    fixture.accept(event)
                self.respond(202)
            else:
                self.respond(404)

        def do_GET(self):
            fixture.requests.append(("GET", self.path))
            if self.path != "/v1/agents/sessions/sess-loopback/events":
                self.respond(404)
                return
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream")
            self.send_header("Connection","close")
            self.end_headers()
            self.close_connection = True
            try:
                for _ in range(100):
                    try:
                        event = fixture.queue.get(timeout=5)
                    except Empty:
                        break
                    if event is None:
                        break
                    payload = "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
                    self.wfile.write(payload.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_DELETE(self):
            fixture.requests.append(("DELETE", self.path))
            fixture.queue.put(None)
            if fixture.scenario == "cleanup_error":
                self.respond(500,{"error":{"message":"fixture cleanup failure","type":"server_error"}})
            else:
                self.respond(200,{"id":"sess-loopback","deleted":True})

    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", fixture
    finally:
        fixture.queue.put(None)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def exercise(scenario, *, journal=None):
    import httpx2
    from openai import OpenAI
    if scenario not in ("normal","duplicate","incomplete","unknown_tool","cleanup_error","wrong_turn"):
        raise ValueError("unknown loopback scenario")
    host = ToolHost(State(),journal or Journal(),max_actions=5)
    with local_fixture(scenario) as (base_url,fixture):
        with OpenAI(api_key="loopback-fixture-only",base_url=base_url,max_retries=0,timeout=5,
                    http_client=httpx2.Client(trust_env=False)) as client:
            result = run_api(host,client,model="scripted-protocol-fixture",timeout_seconds=15)
        result.update(api_transport="loopback_http",selection_source="scripted_fixture",
                      http_requests=len(fixture.requests),external_model_api_used=False)
    return host,result
