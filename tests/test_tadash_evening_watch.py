"""No network. Real native SQLite fixture plus bounded-watch coverage tests."""
from copy import deepcopy
from contextlib import closing
import hashlib,importlib.util,json,sqlite3,sys,tempfile,time,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("watch",ROOT/"deploy/tadash_watch/watch.py")
watch=importlib.util.module_from_spec(spec);spec.loader.exec_module(watch)

class WatchTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.native=self.base/"native";self.worker=self.base/"worker";self.worker.mkdir()
  spec=importlib.util.spec_from_file_location("native_installer",ROOT/"tools/bridge_jobs/tadash_install.py")
  installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
  installer.perform("install",self.native,(ROOT/"deploy/tadash_vps_v01.bundle.b64").read_bytes())
  (self.worker/"state").mkdir()
  with closing(sqlite3.connect(self.worker/"state/worker.sqlite")) as db:
   db.execute("CREATE TABLE goals(id TEXT PRIMARY KEY,admitted REAL,record TEXT)");db.commit()
  self.start=10000.
  watch.atomic(self.worker/"config.json",{"installation_id":"fixture"})
  watch.atomic(self.worker/"health.json",{"installation_id":"fixture","system":True,"updated_epoch":self.start,"state":"idle","boot_id":"boot-a"})
  self.probe=lambda:{"state":"Running","enabled":True,"system":True,"sampler_system":True}
  self.baseline=watch.snapshot(self.worker,self.native,self.start,self.probe)
  self.monitor=self.base/"monitor";self.monitor.mkdir()
  watch.atomic(self.monitor/"config.json",{"schema":watch.SCHEMA,"started":self.start,"deadline":self.start+1200,
   "worker_root":str(self.worker),"native_root":str(self.native),"baseline":self.baseline})
 def frozen(self,*args,**kwargs):
  value=deepcopy(self.baseline);value["at"]=kwargs["now"];return value
 def test_real_native_snapshot_checks_hash_and_reads_both_ledgers_without_changes(self):
  paths=[self.native/"state/session.sqlite",self.worker/"state/worker.sqlite"]
  before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
  sample=watch.snapshot(self.worker,self.native,self.start,self.probe)
  self.assertEqual(sample["issues"],[]);self.assertEqual(sample["native_revision"],0)
  self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
  with closing(sqlite3.connect(paths[0])) as db:
   raw=json.loads(db.execute("SELECT value FROM runtime").fetchone()[0])
   raw["payload"]["revision"]+=1
   db.execute("UPDATE runtime SET value=?",(json.dumps(raw),))
   db.commit()
  with self.assertRaisesRegex(ValueError,"native_checksum"):watch.snapshot(self.worker,self.native,self.start,self.probe)
 def test_same_slot_is_idempotent_and_changed_api_counter_is_flagged(self):
  watch.sample(self.monitor,self.start,self.frozen)
  watch.sample(self.monitor,self.start+50,self.frozen)
  self.assertEqual(len(watch.read_samples(self.monitor)),1)
  def changed(*a,**kw):
   value=self.frozen(*a,**kw);value["api_requests"]+=1;return value
  value=watch.sample(self.monitor,self.start+600,changed)
  self.assertIn("changed_api_requests",value["issues"])
  result=watch.finalize(self.monitor,self.start+1200,self.frozen)
  self.assertEqual(result["samples"],3);self.assertEqual(result["bad_samples"],1)
  self.assertTrue(result["coverage_ok"]);self.assertEqual(result["missing_regular_slots"],0)
 def test_missing_slots_and_late_samples_are_not_reported_as_continuous_uptime(self):
  watch.sample(self.monitor,self.start,self.frozen)
  self.assertIn("WATCH=ACTIVE",watch.report(self.monitor,self.start+100))
  with self.assertRaisesRegex(ValueError,"deadline_not_reached"):watch.finalize(self.monitor,self.start+1199,self.frozen)
  result=watch.finalize(self.monitor,self.start+1300,self.frozen)
  self.assertFalse(result["coverage_ok"]);self.assertEqual(result["missing_regular_slots"],1)
  self.assertGreater(result["maximum_observation_gap_seconds"],900)
  again=watch.finalize(self.monitor,self.start+1500,self.frozen)
  self.assertEqual(result,again);self.assertEqual(len(watch.read_samples(self.monitor)),2)
  self.assertEqual(result["api_calls_by_monitor"],0)

 def test_host_clock_offset_preserves_reference_deadline_and_coverage(self):
  cfg=watch.read_json(self.monitor/"config.json")
  cfg.update(clock_offset_seconds=18000,deadline_reference_utc=cfg["deadline"]-18000)
  watch.atomic(self.monitor/"config.json",cfg)
  watch.sample(self.monitor,self.start,self.frozen)
  watch.sample(self.monitor,self.start+600,self.frozen)
  result=watch.finalize(self.monitor,self.start+1200,self.frozen)
  self.assertTrue(result["coverage_ok"])
  self.assertEqual(result["deadline_reference_utc"],self.start+1200-18000)
  self.assertEqual(result["started_reference_utc"],self.start-18000)

if __name__=="__main__":unittest.main()
