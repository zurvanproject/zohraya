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
    def __init__(self,actions,status="requires_action"):self.actions=actions;self.status=status
    def to_dict(self):return {"id":self.id,"status":self.status,"required_actions":self.actions}


def action(name="observe_body",arguments=None):
    return {"type":"function_call","turn_id":"turn_test","call_id":"call_test","name":name,"arguments":arguments or {}}


class FakeSessions:
    def __init__(self):
        self.creations=0;self.submissions=0;self.actions=[action()];self.fail_after_submit=False;self.status="requires_action"
        self.events=SimpleNamespace(create=self.create_event)
    def create(self,**kwargs):self.creations+=1;return Session(self.actions)
    def retrieve(self,identity):return Session(self.actions,self.status)
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

    def test_uncertain_api_ack_blocks_without_second_submission(self):
        data,key=self.start();self.sessions.fail_after_submit=True
        with self.assertRaises(TimeoutError):client.submit(self.api,data,key,{"n":1},self.state)
        resumed=client.load(self.state);self.sessions.fail_after_submit=False
        with self.assertRaises(ValueError):client.submit(self.api,resumed,key,{"n":1},self.state)
        self.assertEqual(self.sessions.submissions,1)

    def test_arguments_reject_arbitrary_tools_and_actions(self):
        for item in (action("shell"),action("observe_body",{"path":"private"}),action("request_body_action",{"action":"reset"})):
            with self.assertRaises(ValueError):client.normalized("sess_test",item)

    def test_completed_turn_resume_preserves_contract_and_is_idempotent(self):
        data,key=self.start();before=data["contract"].copy()
        self.sessions.status="idle";self.sessions.actions=[]
        observation={"goal_id":client.GOAL_ID,"goal_cycles_completed":0,"body_revision":2}
        client.continue_goal(self.api,data,observation,self.state)
        client.continue_goal(self.api,data,observation,self.state)
        self.assertEqual(self.sessions.creations,1);self.assertEqual(self.sessions.submissions,1)
        self.assertEqual(client.load(self.state)["contract"],before)

    def test_resume_rejects_foreign_goal_and_active_turn(self):
        data,key=self.start()
        with self.assertRaises(ValueError):client.continue_goal(self.api,data,{"goal_id":"other","goal_cycles_completed":0},self.state)
        with self.assertRaises(ValueError):client.continue_goal(self.api,data,{"goal_id":client.GOAL_ID,"goal_cycles_completed":0},self.state)
        self.assertEqual(self.sessions.submissions,0)




class BridgeReceiptTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location("bridge_parser",ROOT/"deploy/tadash_agent/bridge.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def receipt(self,summary=None):
        summary=summary or "G=DONE;N=3/3;R=5;E=0.900;F=0.100;P=0.000;S=0.940;Q=observe;D=observe;A=observe;MEM=1;X=0;SIG=0123456789abcdef;PHY=0"
        return {"id":2,"user":{"login":"zurvanproject"},
                "body":"Nasuraya Bridge v2 result; request_id=comment-1; command=run tadash_goal_call\nResult: OK "+summary}
    def test_exact_authenticated_receipt_is_converted(self):
        result=self.module().parse_reply(self.receipt(),1)
        self.assertTrue(result["goal_complete"]);self.assertEqual(result["goal_cycles_completed"],3)
        self.assertEqual(result["measurement_precision"],0.001)
    def test_wrong_author_request_and_rejection_are_refused(self):
        module=self.module()
        for kind in ("author","request","rejection"):
            value=self.receipt()
            if kind=="author":value["user"]["login"]="other"
            elif kind=="request":value["body"]=value["body"].replace("comment-1","comment-9")
            else:value=self.receipt("G=REJECTED;ERROR=ValueError")
            with self.assertRaises(ValueError):module.parse_reply(value,1)
    def test_completion_scope_and_range_tampering_are_refused(self):
        module=self.module();base=self.receipt()
        for old,new in (("G=DONE","G=ACTIVE"),("N=3/3","N=4/3"),("PHY=0","PHY=1"),("S=0.940","S=9.940"),("X=0","X=1")):
            value=dict(base);value["body"]=base["body"].replace(old,new)
            with self.assertRaises(ValueError):module.parse_reply(value,1)


if __name__=="__main__":unittest.main()

