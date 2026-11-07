"""Local fixture only; no API calls. Exercise the real admission and audit paths."""
from contextlib import closing
import base64,importlib.util,io,json,os,sqlite3,subprocess,sys,tempfile,time,unittest,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"deploy/tadash_server"))
sys.path.insert(0,str(ROOT/"tests"))
import worker
from test_tadash_server_worker import FakeAPI

class LabeledAPI(FakeAPI):
 def request(self,method,path,data=None,idempotency_key=None):
  result=super().request(method,path,data,idempotency_key)
  if method=="GET" and "/items" in path:
   result["data"][0]["content"][0]["text"]="مسئله: آزمون مصنوعی. دلیل: بازخورد ذخیره. نتیجه: مشاهده. گام بعد: بررسی."
  return result

class MemoryExperimentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name);self.service=self.base/"NasurayaModelWorker";self.service.mkdir()
  self.native=self.base/"Tadash"
  spec=importlib.util.spec_from_file_location("native_installer",ROOT/"tools/bridge_jobs/tadash_install.py")
  installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
  installer.perform("install",self.native,(ROOT/"deploy/tadash_vps_v01.bundle.b64").read_bytes())
  installer.invoke(self.native,"step") # real synthetic walk veto produces verified negative feedback
  self.store=worker.Store(self.service/"state/worker.sqlite");self.addCleanup(self.store.close)
  self.store.admit({"goal_id":"nasuraya-memory-predecessor","text":"Fixture predecessor","max_cycles":1})
  previous=worker.run_goal(self.store,self.store.active(),LabeledAPI(),self.native,sleeper=lambda _:None)
  self.assertEqual(previous["status"],"completed",previous.get("error"))
  runtime=self.service/"runtime-e747ee5d4aaa642c"
  runtime.mkdir()
  with zipfile.ZipFile(io.BytesIO(base64.b64decode((ROOT/"deploy/tadash_server_v01.bundle.b64").read_bytes()))) as z:z.extractall(runtime)
  (self.service/"inbox").mkdir();(self.service/"archive").mkdir()
  (self.service/"owner.json").write_text(json.dumps({"schema":"nasuraya-model-worker/1"}))
  (self.service/"config.json").write_text(json.dumps({"schema":worker.SCHEMA,"model":worker.MODEL,
   "installation_id":"fixture","require_system":True,"tadash_root":str(self.native)}))
  (self.service/"health.json").write_text(json.dumps({"installation_id":"fixture","system":True,"updated_epoch":time.time()}))
 def cli(self,name):
  env=dict(os.environ,PROGRAMDATA=str(self.base))
  # Match the actual bridge invocation, including Windows' default non-UTF-8
  # process; the pinned job must bootstrap its own UTF-8 native interpreter.
  p=subprocess.run([sys.executable,"-I",str(ROOT/"tools/bridge_jobs"/name)],env=env,capture_output=True,text=True,encoding="utf-8",timeout=35)
  self.assertEqual(p.returncode,0,p.stderr+p.stdout)
  return json.loads(p.stdout)["summary"]
 def native_count(self):
  with closing(sqlite3.connect(self.native/"state/session.sqlite")) as db:return db.execute("SELECT count(*) FROM decisions").fetchone()[0]
 def test_cold_paired_memory_changes_choice_without_live_execution_and_admission_is_idempotent(self):
  baseline=self.native_count()
  first=self.cli("worker_memory_goal.py")
  self.assertIn("MEMORY_GOAL=QUEUED",first);self.assertIn("WITHOUT=walk;WITH=observe",first)
  exp=self.service/"experiments/nasuraya-memory-three-cycle-20261107-v1"
  manifest=json.loads((exp/"experiment.json").read_text(encoding="utf-8"))
  paired=manifest["paired_decisions"]
  self.assertEqual(paired["with_memory"]["request_sha256"],paired["without_memory"]["request_sha256"])
  self.assertEqual(manifest["probe_live_body_cycles"],0);self.assertEqual(self.native_count(),baseline)
  queued=(self.service/"inbox"/(manifest["goal"]["goal_id"]+".json")).read_bytes()
  again=self.cli("worker_memory_goal.py")
  self.assertIn("MEMORY_GOAL=QUEUED",again)
  self.assertEqual(queued,(self.service/"inbox"/(manifest["goal"]["goal_id"]+".json")).read_bytes())
  self.assertEqual(self.native_count(),baseline)
 def test_three_cycle_continuation_audit_checks_live_ledger_and_saved_report(self):
  self.assertIn("MEMORY_GOAL=QUEUED",self.cli("worker_memory_goal.py"))
  target=next((self.service/"inbox").glob("*.json"));goal=json.loads(target.read_text(encoding="utf-8"));target.unlink()
  self.store.admit(goal)
  record=worker.run_goal(self.store,self.store.active(),LabeledAPI(3),self.native,sleeper=lambda _:None)
  self.assertEqual(record["status"],"completed",record.get("error"))
  before=self.native_count()
  summary=self.cli("worker_memory_audit.py")
  self.assertIn("MEMORY_GOAL=DONE;N=3;R=5",summary)
  self.assertIn("CONT=1;SOURCES=1;CF=1;REPORT=1;DEL=1",summary)
  self.assertEqual(self.native_count(),before)
  self.assertIn("ALREADY_ADMITTED",self.cli("worker_memory_goal.py"))

 def test_pre_admission_partial_snapshot_is_preserved_and_live_state_is_unchanged(self):
  self.assertIn("MEMORY_GOAL=QUEUED",self.cli("worker_memory_goal.py"))
  parent=self.service/"experiments";experiment=parent/"nasuraya-memory-three-cycle-20261107-v1"
  (experiment/"experiment.json").unlink()
  next((self.service/"inbox").glob("*.json")).unlink()
  before=self.native_count()
  self.assertIn("MEMORY_GOAL=QUEUED",self.cli("worker_memory_goal.py"))
  preserved=list(parent.glob("*-incomplete-*"))
  self.assertEqual(len(preserved),1)
  self.assertTrue((preserved[0]/"before.sqlite").is_file())
  self.assertTrue((preserved[0]/"preserved_failure.json").is_file())
  self.assertEqual(self.native_count(),before)

if __name__=="__main__":unittest.main()
