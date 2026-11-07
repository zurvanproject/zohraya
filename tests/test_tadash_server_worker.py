"""Independent worker behavior and native receipt tests; never call the live API."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"deploy/tadash_server"
sys.path.insert(0,str(SOURCE))
import worker
from api import APIError
import native_tools


class FakeAPI:
    def __init__(self,cycles=1):
        self.cycles=cycles;self.stage=0;self.deleted=False;self.posts=[]
    def action(self):
        if self.stage==0:name,args="observe_body",{}
        elif self.stage<=self.cycles:name,args="request_body_action",{"action":"observe"}
        else:name,args="evaluate_goal",{}
        return {"type":"function_call","turn_id":"turn_test","call_id":"call_"+str(self.stage),
                "name":name,"arguments":args}
    def request(self,method,path,data=None,idempotency_key=None):
        if method=="DELETE":self.deleted=True;return {"deleted":True}
        if method=="POST" and path=="/v1/agents/sessions":
            self.payload=data;return {"id":"sess_test","status":"in_progress"}
        if method=="POST":
            events=data["events"]
            if events[0]["type"].endswith("tool_result"):
                self.posts.append(events[0]);self.stage+=1
            return {}
        if "/turns" in path:return {"data":[{"id":"turn_test","status":"completed","subagent_id":None}]}
        if "/items" in path:return {"data":[{"type":"message","role":"assistant","turn_id":"turn_test",
                                          "phase":"final_answer","content":[{"type":"output_text","text":"fixture complete"}]}]}
        if self.stage>self.cycles+1:return {"id":"sess_test","status":"idle","required_actions":[]}
        return {"id":"sess_test","status":"requires_action","required_actions":[self.action()]}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.native=self.root/"NasurayaTadashV1"
        spec=importlib.util.spec_from_file_location("installer",ROOT/"tools/bridge_jobs/tadash_install.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.perform("install",self.native,(ROOT/"deploy/tadash_vps_v01.bundle.b64").read_bytes())
        self.store=worker.Store(self.root/"worker.sqlite");self.addCleanup(self.store.close)
    def spec(self,identity="nasuraya-server-test",cycles=1):
        return {"goal_id":identity,"text":"Inspect state, perform bounded safe cycles, then evaluate.","max_cycles":cycles}
    def run_native(self,call,root):
        # Source-pinned legacy modules are intentionally isolated per process.
        import subprocess
        code="import json,sys;sys.path.insert(0,sys.argv[1]);import native_tools;print(json.dumps(native_tools.operate(json.loads(sys.argv[2]),sys.argv[3])))"
        p=subprocess.run([sys.executable,"-I","-X","utf8","-c",code,str(SOURCE),json.dumps(call),str(root)],
                         capture_output=True,text=True,encoding="utf-8",timeout=20)
        self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        return json.loads(p.stdout)
    def native_count(self):
        with closing(sqlite3.connect(self.native/"state/session.sqlite")) as db:
            return db.execute("SELECT count(*) FROM decisions").fetchone()[0]

    def test_full_worker_goal_runs_native_without_work_callbacks(self):
        self.store.admit(self.spec())
        api=FakeAPI()
        result=worker.run_goal(self.store,self.store.active(),api,self.native,sleeper=lambda x:None,execute=self.run_native)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["result"]["native"]["completed_cycles"],1)
        self.assertEqual(result["result"]["native"]["revision"],1)
        self.assertEqual(self.native_count(),1)
        self.assertEqual(result["submitted_results"],3)
        self.assertTrue(result["session_deleted"]);self.assertTrue(api.deleted)
        self.assertEqual(api.payload["environment"],{"type":"none"})
        self.assertFalse(api.payload["agent"]["multi_agent"]["enabled"])

    def test_three_cycle_goal_and_unchanged_total_body_budget(self):
        self.store.admit(self.spec(cycles=3));api=FakeAPI(3)
        result=worker.run_goal(self.store,self.store.active(),api,self.native,sleeper=lambda x:None,execute=self.run_native)
        self.assertEqual(result["status"],"completed");self.assertEqual(self.native_count(),3)
        self.assertEqual(result["result"]["native"]["max_cycles"],3)

    def test_production_child_path_handles_three_calls_and_second_goal(self):
        self.store.admit(self.spec(cycles=3))
        result=worker.run_goal(self.store,self.store.active(),FakeAPI(3),self.native,sleeper=lambda x:None)
        self.assertEqual(result["status"],"completed",result.get("error"))
        self.store.admit(self.spec("nasuraya-production-second"))
        result=worker.run_goal(self.store,self.store.active(),FakeAPI(),self.native,sleeper=lambda x:None)
        self.assertEqual(result["status"],"completed",result.get("error"))
        self.assertEqual(self.native_count(),4)

    @unittest.skipIf(sys.platform=="win32","Linux isolated idle check; Windows DPAPI tested separately")
    def test_isolated_scheduled_entry_is_idle_without_api(self):
        import hashlib,shutil,subprocess
        install=self.root/"runtime";install.mkdir()
        names=["worker.py","api.py","native_tools.py","cacert.pem","CERTIFI_LICENSE"]
        for name in names:shutil.copyfile(SOURCE/name,install/name)
        (install/"FILES_SHA256.json").write_text(json.dumps({n:hashlib.sha256((install/n).read_bytes()).hexdigest() for n in names}))
        home=self.root/"service";home.mkdir();(home/"inbox").mkdir();(home/"archive").mkdir()
        (home/"config.json").write_text(json.dumps({"schema":worker.SCHEMA,"model":worker.MODEL,
             "installation_id":"idle-fixture","require_system":False,"tadash_root":str(self.native)}))
        p=subprocess.run([sys.executable,"-I","-X","utf8",str(install/"worker.py"),"--root",str(home),"--once"],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        health=json.loads((home/"health.json").read_text())
        self.assertEqual(health["state"],"idle");self.assertEqual(health["last_goal_status"],"none")
        self.assertEqual(self.native_count(),0)

    @unittest.skipUnless(sys.platform=="win32","Windows machine DPAPI interoperability")
    def test_machine_dpapi_roundtrip_with_service_entropy(self):
        import subprocess
        from api import protected_key
        path=self.root/"test-only.dpapi"
        script="Add-Type -AssemblyName System.Security; $p=[Text.Encoding]::ASCII.GetBytes('sk-'+('x'*40)); $e=[Text.Encoding]::ASCII.GetBytes('NasurayaModelWorker/api-key/v1'); [IO.File]::WriteAllBytes($args[0],[Security.Cryptography.ProtectedData]::Protect($p,$e,[Security.Cryptography.DataProtectionScope]::LocalMachine))"
        escaped=str(path).replace("'","''")
        script=script.replace("$args[0]","'"+escaped+"'")
        p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0)
        self.assertEqual(protected_key(path),"sk-"+"x"*40)

    def test_restart_replays_saved_native_tool_result_without_extra_cycle(self):
        self.store.admit(self.spec());record=self.store.active();record["session"]="sess_test"
        first={"type":"function_call","turn_id":"turn_test","call_id":"obs","name":"observe_body","arguments":{}}
        worker.handle_action(self.store,record,first,self.native,self.run_native)
        action={"type":"function_call","turn_id":"turn_test","call_id":"one","name":"request_body_action","arguments":{"action":"observe"}}
        key,one=worker.handle_action(self.store,record,action,self.native,self.run_native)
        restored=self.store.get(record["spec"]["goal_id"])
        key,two=worker.handle_action(self.store,restored,action,self.native,self.run_native)
        self.assertEqual(one["result"],two["result"]);self.assertEqual(self.native_count(),1)

    def test_changed_call_payload_cannot_repeat_native_effect(self):
        self.store.admit(self.spec());record=self.store.active();record["session"]="sess_test"
        obs={"type":"function_call","turn_id":"turn_test","call_id":"obs","name":"observe_body","arguments":{}}
        worker.handle_action(self.store,record,obs,self.native,self.run_native)
        action={"type":"function_call","turn_id":"turn_test","call_id":"one","name":"request_body_action","arguments":{"action":"observe"}}
        worker.handle_action(self.store,record,action,self.native,self.run_native)
        action["arguments"]["action"]="walk"
        with self.assertRaises(ValueError):worker.handle_action(self.store,record,action,self.native,self.run_native)
        self.assertEqual(self.native_count(),1)

    def test_goal_reservation_uses_per_goal_cap_and_keeps_prior_goals(self):
        self.store.admit(self.spec());api=FakeAPI()
        worker.run_goal(self.store,self.store.active(),api,self.native,sleeper=lambda x:None,execute=self.run_native)
        self.store.admit(self.spec("nasuraya-server-second"));api2=FakeAPI()
        result=worker.run_goal(self.store,self.store.active(),api2,self.native,sleeper=lambda x:None,execute=self.run_native)
        self.assertEqual(result["result"]["native"]["completed_cycles"],1)
        self.assertEqual(self.native_count(),2)

    def test_daily_lifetime_caps_and_repeated_goal_contract(self):
        self.store.admit(self.spec(),now=1)
        self.assertFalse(self.store.admit(self.spec(),now=1))
        with self.assertRaises(ValueError):self.store.admit(self.spec(cycles=3),now=1)
        self.store.admit(self.spec("nasuraya-second"),now=2)
        with self.assertRaises(ValueError):self.store.admit(self.spec("nasuraya-third"),now=3)
        for index in range(3):self.store.admit(self.spec("nasuraya-later-"+str(index)),now=(index+1)*86400)
        with self.assertRaises(ValueError):self.store.admit(self.spec("nasuraya-sixth"),now=10*86400)

    def test_unknown_tool_and_secret_text_are_rejected(self):
        with self.assertRaises(ValueError):worker.validate_goal({"goal_id":"nasuraya-x","text":"sk-"+("a"*40),"max_cycles":1})
        with self.assertRaises(ValueError):worker.call_identity("sess",{"type":"function_call","turn_id":"turn","call_id":"call","name":"shell","arguments":{}})
        with self.assertRaises(ValueError):self.store.admit(self.spec(cycles=4))
        self.assertEqual(self.native_count(),0)

    def test_native_ledger_exhaustion_stops_before_model_creation(self):
        self.store.admit(self.spec());api=FakeAPI()
        original=worker.native_budget
        try:
            worker.native_budget=lambda root,target:(_ for _ in ()).throw(ValueError("exhausted"))
            result=worker.run_goal(self.store,self.store.active(),api,self.native,sleeper=lambda x:None,execute=self.run_native)
        finally:worker.native_budget=original
        self.assertEqual(result["status"],"blocked")
        self.assertFalse(hasattr(api,"payload"));self.assertEqual(self.native_count(),0)

    def test_confirmed_session_cleanup_on_run_budget(self):
        self.store.admit(self.spec());record=self.store.active();record.update(session="sess_test",started=1,status="running")
        self.store.save(record);api=FakeAPI()
        result=worker.run_goal(self.store,record,api,self.native,clock=lambda:1000,sleeper=lambda x:None)
        self.assertEqual(result["error"],"run_budget");self.assertTrue(api.deleted)
        self.assertEqual(self.native_count(),0)


if __name__=="__main__":unittest.main()

