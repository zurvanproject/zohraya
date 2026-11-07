"""Native-goal persistence and exactly-once receipt reconciliation tests, no API."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
JOB=ROOT/"tools/bridge_jobs/tadash_goal_call.py"


class TadashGoalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.account=Path(self.temp.name)
        self.root=self.account/"NasurayaTadashV1"
        spec=importlib.util.spec_from_file_location("installer",ROOT/"tools/bridge_jobs/tadash_install.py")
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        installer.perform("install",self.root,(ROOT/"deploy/tadash_vps_v01.bundle.b64").read_bytes())

    def call(self,label,name="observe_body",arguments=None,good=True):
        call={"goal_id":"nasuraya-review-20261107-v1",
              "call_key":hashlib.sha256(label.encode()).hexdigest(),
              "name":name,"arguments":arguments or {}}
        source=re.sub(r"^CALL = .*?$","CALL = "+json.dumps(call),JOB.read_text(encoding="utf-8"),count=1,flags=re.M)
        script=self.account/"one-call.py";script.write_text(source,encoding="utf-8")
        env=dict(os.environ);env["LOCALAPPDATA"]=str(self.account)
        run=subprocess.run([sys.executable,"-I","-X","utf8",str(script)],capture_output=True,text=True,
                           encoding="utf-8",env=env,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        output=json.loads(run.stdout)
        if good:
            self.assertNotIn("REJECTED",output["summary"],output)
            self.assertRegex(output["summary"],r"\A[a-zA-Z0-9 .,:;=/_()+-]{1,180}\Z")
        else:
            self.assertIn("REJECTED",output["summary"])
        return output

    def cycles(self):
        with closing(sqlite3.connect(self.root/"state/session.sqlite")) as db:
            return db.execute("SELECT count(*) FROM decisions").fetchone()[0]

    def test_goal_survives_process_restart_and_caps_three_cycles(self):
        self.assertIn("N=0/3",self.call("observe")["summary"])
        for index in range(3):
            result=self.call("step"+str(index),"request_body_action",{"action":"observe"})
            self.assertIn("N="+str(index+1)+"/3",result["summary"])
        self.assertIn("G=DONE",self.call("evaluate","evaluate_goal")["summary"])
        self.call("fourth","request_body_action",{"action":"observe"},good=False)
        self.assertEqual(self.cycles(),3)

    def test_same_call_replay_returns_same_receipt_and_no_effect(self):
        self.call("observe")
        one=self.call("one","request_body_action",{"action":"observe"})
        two=self.call("one","request_body_action",{"action":"observe"})
        self.assertEqual(one,two);self.assertEqual(self.cycles(),1)

    def test_payload_conflict_does_not_repeat_native_cycle(self):
        self.call("observe");self.call("one","request_body_action",{"action":"observe"})
        self.call("one","request_body_action",{"action":"walk"},good=False)
        self.assertEqual(self.cycles(),1)

    def test_missing_observation_refused_before_reservation(self):
        self.call("one","request_body_action",{"action":"walk"},good=False)
        self.assertEqual(self.cycles(),0)
        with closing(sqlite3.connect(self.root/"state/agent-goals.sqlite")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM calls").fetchone()[0],0)

    def test_native_completion_before_goal_save_is_reconciled_without_repeat(self):
        self.call("observe");self.call("one","request_body_action",{"action":"observe"})
        key=hashlib.sha256(b"one").hexdigest()
        with closing(sqlite3.connect(self.root/"state/agent-goals.sqlite")) as db:
            db.execute("UPDATE calls SET phase='started',output=NULL WHERE call_key=?",(key,));db.commit()
        restored=self.call("one","request_body_action",{"action":"observe"})
        self.assertIn("N=1/3",restored["summary"]);self.assertIn("X=0",restored["summary"])
        self.assertEqual(self.cycles(),1)

    def test_foreign_goal_ledger_preserved(self):
        path=self.root/"state/agent-goals.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE unrelated (value TEXT)");db.commit()
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        self.call("observe",good=False)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_tool_arguments_and_identity_checked_before_effect(self):
        self.call("observe")
        self.call("bad","request_body_action",{"action":"shell"},good=False)
        self.call("bad2","observe_body",{"action":"walk"},good=False)
        self.assertEqual(self.cycles(),0)


if __name__=="__main__":unittest.main()

