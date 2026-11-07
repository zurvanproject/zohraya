"""Caller state/identity tests; no SDK, key file or network is needed."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("agent_client",ROOT/"deploy/tadash_agent/client.py")
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


class Session:
    id="sess_test"
    def __init__(self,actions):self.actions=actions
    def to_dict(self):return {"id":self.id,"status":"requires_action","required_actions":self.actions}


def action(name="observe_body",arguments=None):
    return {"type":"function_call","turn_id":"turn_test","call_id":"call_test","name":name,"arguments":arguments or {}}


class FakeSessions:
    def __init__(self):
        self.creations=0;self.submissions=0;self.actions=[action()];self.fail_after_submit=False
        self.events=SimpleNamespace(create=self.create_event)
    def create(self,**kwargs):self.creations+=1;return Session(self.actions)
    def retrieve(self,identity):return Session(self.actions)
    def create_event(self,identity,**kwargs):
        self.submissions+=1;self.actions=[]
        if self.fail_after_submit:raise TimeoutError("synthetic lost acknowledgement")


class ClientStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)
        self.sessions=FakeSessions();self.api=SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=self.sessions)))
        self.sessions.turns=SimpleNamespace(list=lambda identity:SimpleNamespace(data=[]))

    def start(self):
        data=client.create_or_resume(self.api,self.state)
        report=client.pending(self.api,data,self.state)
        return data,report["pending"][0]["call_key"]

    def test_restart_reuses_same_goal_and_session(self):
        first=client.create_or_resume(self.api,self.state)
        resumed=client.create_or_resume(self.api,self.state)
        self.assertEqual(first,resumed);self.assertEqual(self.sessions.creations,1)

    def test_same_api_identity_changed_payload_is_rejected(self):
        data,key=self.start()
        self.sessions.actions=[action("request_body_action",{"action":"walk"})]
        with self.assertRaises(ValueError):client.pending(self.api,data,self.state)

    def test_tool_result_replay_is_idempotent(self):
        data,key=self.start()
        client.submit(self.api,data,key,{"complete":False},self.state)
        client.submit(self.api,data,key,{"complete":False},self.state)
        self.assertEqual(self.sessions.submissions,1)

    def test_conflicting_result_does_not_get_submitted(self):
        data,key=self.start()
        client.submit(self.api,data,key,{"complete":False},self.state)
        with self.assertRaises(ValueError):client.submit(self.api,data,key,{"complete":True},self.state)
        self.assertEqual(self.sessions.submissions,1)

    def test_uncertain_api_ack_reconciles_without_repeat(self):
        data,key=self.start();self.sessions.fail_after_submit=True
        with self.assertRaises(TimeoutError):client.submit(self.api,data,key,{"n":1},self.state)
        resumed=client.load(self.state);self.sessions.fail_after_submit=False
        client.submit(self.api,resumed,key,{"n":1},self.state)
        self.assertEqual(self.sessions.submissions,1)

    def test_arguments_reject_arbitrary_tools_and_actions(self):
        for item in (action("shell"),action("observe_body",{"path":"private"}),action("request_body_action",{"action":"reset"})):
            with self.assertRaises(ValueError):client.normalized("sess_test",item)


if __name__=="__main__":unittest.main()

