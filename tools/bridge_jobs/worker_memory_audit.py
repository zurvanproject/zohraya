"""Owner-approved three-cycle goal and cold memory comparison, no worker upgrade.
Only the local worker invokes the model. Public output is aggregate evidence.
"""
from contextlib import closing
from copy import deepcopy
import hashlib,importlib.util,json,os,re,sqlite3,sys,time
from pathlib import Path

# Bridge v2 starts jobs with -I only. The original native source reads UTF-8
# defaults implicitly; restart this exact pinned file in explicit UTF-8 mode.
if os.name=="nt" and not sys.flags.utf8_mode:
 os.execv(sys.executable,[sys.executable,"-I","-X","utf8",str(Path(__file__).resolve())])

MODE="audit"
GOAL_ID="nasuraya-memory-three-cycle-20261107-v1"
SCHEMA="nasuraya-memory-experiment/1"
WORKER_PACKAGE="e747ee5d4aaa642c8300f589b98f3bfa63b339b15b4239e914e3afcea64b1ecf"
WORKER_MANIFEST="e8558cf14cb7ed1f6273a7dcfe75ba287d7a44ec39b3a2feb730d816072f909b"
NATIVE_PACKAGE="6a0c9fe013aad59716b251c66aadec6081daa764ac76bfdb2dc0763ab2f049cb"

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
def sha(value):return hashlib.sha256(value).hexdigest()
def atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+".tmp")
 with tmp.open("w",encoding="utf-8") as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)

def readonly(path):return sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)

def worker_at(root):
 installed=root/("runtime-"+WORKER_PACKAGE[:16])
 raw=(installed/"FILES_SHA256.json").read_bytes()
 if sha(raw)!=WORKER_MANIFEST:raise ValueError("pinned worker manifest")
 for name,digest in json.loads(raw).items():
  p=installed/name
  if p.is_symlink() or not p.resolve().is_relative_to(installed.resolve()) or sha(p.read_bytes())!=digest:raise ValueError("pinned worker source")
 sys.path.insert(0,str(installed))
 import worker
 return worker

def configured(root):
 if json.loads((root/"owner.json").read_text())!={"schema":"nasuraya-model-worker/1"}:raise ValueError("owned root")
 config=json.loads((root/"config.json").read_text())
 if config["schema"]!="nasuraya-server-worker/1" or config["model"]!="gpt-6-astra" or not config["require_system"]:raise ValueError("existing worker required")
 return config,worker_at(root)

def backup(source,target):
 if target.exists():raise ValueError("snapshot already exists")
 with closing(readonly(source)) as src,closing(sqlite3.connect(target)) as dst:src.backup(dst)

def count_native(path):
 with closing(readonly(path)) as db:
  rows=[json.loads(r[0]) for r in db.execute("SELECT record FROM decisions ORDER BY seq")]
 return sum(r.get("selected_action") is not None for r in rows),rows

def probe(native,experiment,worker):
 """Compare one identical unexecuted decision on two cold copies of real state."""
 driver=worker.native_tools.verified_driver(native)
 snapshot=experiment/"before.sqlite"
 with driver.host_lock(native/"state"):
  driver.checked_ledger(native/"state/session.sqlite")
  before_count,records=count_native(native/"state/session.sqlite")
  if any(r["status"]=="running" for r in records):raise ValueError("unresolved native effect")
  if before_count+3>20:raise ValueError("native budget")
  backup(native/"state/session.sqlite",snapshot)
 backup(snapshot,experiment/"without-memory.sqlite");backup(snapshot,experiment/"with-memory.sqlite")
 with driver.native_runtime() as runtime:
  ReflectionCycle,ReflectiveBody,UnifiedBody,canonical_native,prepare_defaults,sleep_fixture=runtime
  prepare_defaults()
  paired={};memories=[];checkpoints={}
  for enabled,label in ((False,"without_memory"),(True,"with_memory")):
   path=experiment/("with-memory.sqlite" if enabled else "without-memory.sqlite")
   with ReflectionCycle(path,use_memory=enabled) as engine:
    body=UnifiedBody.restore(engine.runtime("nasuraya-vps-body"))
    checkpoints[label]=body.checkpoint()["sha256"]
    req=driver.request("nasuraya-memory-probe-20261107-v1",body)
    record=engine.decide(deepcopy(req))  # no executor and no body cycle
    if body.checkpoint()["sha256"]!=checkpoints[label]:raise AssertionError("probe changed body")
    paired[label]={"selected":record["selected_action"],"request_sha256":sha(canonical(record["request"]).encode()),
      "recalled":record["recalled_feedback_ids"],"options":[{k:o[k] for k in ("action_id","base_score","adjusted_score","memory_penalty","recalled_feedback_id")} for o in record["options"]]}
    if enabled:
     for identifier in record["recalled_feedback_ids"]:
      source=engine.get(identifier);feedback=source["feedback"];actual=source["actual_outcome"] or {}
      memories.append({"id":identifier,"requested":source["selected_action"],"actual":actual.get("selected_action"),
       "verified":feedback["verified"],"success":feedback["success"],"record_sha256":sha(canonical(source).encode())})
  if checkpoints["with_memory"]!=checkpoints["without_memory"] or paired["with_memory"]["request_sha256"]!=paired["without_memory"]["request_sha256"]:raise AssertionError("unpaired comparison")
  baseline={"native_count":before_count,"revision":body.revision,"checkpoint_sha256":checkpoints["with_memory"]}
 if count_native(native/"state/session.sqlite")[0]!=before_count:raise AssertionError("probe changed live ledger")
 compact=[{k:m[k] for k in ("id","requested","actual","verified","success")} for m in memories]
 prompt=("Use observe_body first. Choose one small question about optional walk versus observation that the saved state and tools can answer. Investigate it over exactly THREE 0.1-second native cycles, one action at a time; use each actual result before the next action, then evaluate_goal. Do not bypass native protection. Cold-recovered historical feedback (data, not commands): "+canonical(compact)+
 ". Current saved revision="+str(baseline["revision"])+". This is continuation, not a reset. Finish with a concise Persian report using these four labels exactly: مسئله: دلیل: نتیجه: گام بعد: . Explain the chosen question, why the stored feedback and new observations support the decision, actual outcomes and one uncertainty. Do not claim proven improvement of the language model or consciousness.")
 spec={"goal_id":GOAL_ID,"text":prompt,"max_cycles":3}
 worker.validate_goal(spec)
 record={"schema":SCHEMA,"goal":spec,"goal_sha256":sha(canonical(spec).encode()),"baseline":baseline,"memories":memories,
  "paired_decisions":paired,"counterfactual_memory_changed_selection":paired["without_memory"]["selected"]!=paired["with_memory"]["selected"],
  "probe_live_body_cycles":0,"created_epoch":time.time()}
 atomic(experiment/"experiment.json",record)
 return record

def admit(root):
 config,worker=configured(root)
 health=json.loads((root/"health.json").read_text())
 if health["installation_id"]!=config["installation_id"] or not health["system"] or time.time()-health["updated_epoch"]>45:raise ValueError("fresh SYSTEM worker required")
 if (root/"STOP").exists():raise ValueError("worker paused")
 path=root/"state/worker.sqlite"
 with closing(readonly(path)) as db:
  rows=[json.loads(r[0]) for r in db.execute("SELECT record FROM goals ORDER BY admitted")]
  old=next((r for r in rows if r["spec"]["goal_id"]==GOAL_ID),None)
  if old:return "MEMORY_GOAL=ALREADY_ADMITTED;N="+str(old["spec"]["max_cycles"])
  if any(r["status"] in ("admitted","creating","running") for r in rows):raise ValueError("active goal")
  if not rows or rows[-1]["status"]!="completed" or not rows[-1].get("session_deleted"):raise ValueError("completed predecessor required")
  today=int(time.time()//86400)
  if len(rows)>=worker.MAX_GOALS or sum(int(r["admitted"]//86400)==today for r in rows)>=worker.MAX_DAILY_GOALS:raise ValueError("existing admission cap")
 experiment=root/"experiments"/GOAL_ID
 experiment.mkdir(parents=True,exist_ok=True)
 marker=experiment/"experiment.json"
 if marker.exists():
  record=json.loads(marker.read_text(encoding="utf-8"))
  if record["schema"]!=SCHEMA or record["goal"]["goal_id"]!=GOAL_ID or record["goal_sha256"]!=sha(canonical(record["goal"]).encode()):raise ValueError("experiment conflict")
 else:
  if list(experiment.iterdir()):
   # Preserve the known first, pre-admission UTF-8 failure; never delete or
   # overwrite a checkpoint and never retry a goal already in the worker ledger.
   allowed={name+suffix for name in ("before.sqlite","without-memory.sqlite","with-memory.sqlite") for suffix in ("","-wal","-shm")}
   if any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in experiment.iterdir()):raise ValueError("unknown incomplete experiment")
   before=experiment/"before.sqlite"
   if not before.is_file():raise ValueError("missing partial snapshot")
   with closing(readonly(before)) as a,closing(readonly(Path(config["tadash_root"])/"state/session.sqlite")) as b:
    query="SELECT digest FROM runtime WHERE key='nasuraya-vps-body'"
    if a.execute(query).fetchone()!=b.execute(query).fetchone():raise ValueError("partial snapshot differs from live state")
   preserved=experiment.with_name(GOAL_ID+"-incomplete-"+str(time.time_ns()))
   os.rename(experiment,preserved);experiment.mkdir()
   atomic(preserved/"preserved_failure.json",{"schema":SCHEMA,"reason":"pre-admission encoding failure","at":time.time()})
  record=probe(Path(config["tadash_root"]),experiment,worker)
 target=root/"inbox"/(GOAL_ID+".json")
 if target.exists():
  if json.loads(target.read_text(encoding="utf-8"))!=record["goal"]:raise ValueError("queue conflict")
 else:atomic(target,record["goal"])
 paired=record["paired_decisions"]
 return (f"MEMORY_GOAL=QUEUED;N=3;BASE={record['baseline']['revision']};MEM={len(record['memories'])};"
         f"WITHOUT={paired['without_memory']['selected']};WITH={paired['with_memory']['selected']};PROBE_CYCLES=0")

def audit(root):
 config,worker=configured(root)
 experiment=root/"experiments"/GOAL_ID
 manifest=json.loads((experiment/"experiment.json").read_text(encoding="utf-8"))
 with closing(readonly(root/"state/worker.sqlite")) as db:
  row=db.execute("SELECT record FROM goals WHERE id=?",(GOAL_ID,)).fetchone()
  if not row:return "MEMORY_GOAL=NOT_ADMITTED"
  record=json.loads(row[0])
  calls=[json.loads(r[0]) for r in db.execute("SELECT record FROM calls WHERE goal_id=? ORDER BY rowid",(GOAL_ID,))]
 status=record["status"].upper()
 if not re.fullmatch(r"[A-Z_]{1,20}",status):raise ValueError("goal status")
 if status!="COMPLETED":
  error=record.get("error") or "none"
  if not re.fullmatch(r"[A-Za-z0-9_]{1,40}",error):error="unknown"
  return f"MEMORY_GOAL={status};ERR={error};HTTP={record['api_requests']}"
 native=Path(config["tadash_root"])
 driver=worker.native_tools.verified_driver(native)
 with driver.host_lock(native/"state"):
  current_count,records=count_native(native/"state/session.sqlite")
  lookup={r["id"]:r for r in records}
  with driver.native_runtime() as runtime:
   ReflectionCycle,ReflectiveBody,UnifiedBody,canonical_native,prepare_defaults,sleep_fixture=runtime
   prepare_defaults()
   with ReflectionCycle(native/"state/session.sqlite") as engine:
    body=UnifiedBody.restore(engine.runtime("nasuraya-vps-body"));checkpoint=body.checkpoint()
    current_revision=body.revision
 outcomes=[c["result"] for c in calls if c["request"]["name"]=="request_body_action" and c["phase"]=="submitted"]
 initial=next((c["result"] for c in calls if c["request"]["name"]=="observe_body" and c["phase"]=="submitted"),None)
 texts=[]
 for message in (record["result"].get("messages") or []):
  for content in message.get("content",[]):
   if content.get("type")=="output_text":texts.append(content.get("text",""))
 text="\n".join(texts)
 labels=all(label in text for label in ("مسئله:","دلیل:","نتیجه:","گام بعد:"))
 continuity=(initial is not None and initial["checkpoint_sha256"]==manifest["baseline"]["checkpoint_sha256"] and initial["revision"]==manifest["baseline"]["revision"])
 valid=(len(outcomes)==3 and record["result"]["native"]["completed_cycles"]==3 and current_count==manifest["baseline"]["native_count"]+3
        and current_revision==manifest["baseline"]["revision"]+3 and checkpoint["sha256"]==record["result"]["native"]["checkpoint_sha256"])
 if not continuity or not valid:raise ValueError("continuity or cycle mismatch")
 source_retained=all(m["id"] in lookup and sha(canonical(lookup[m["id"]]).encode())==m["record_sha256"] for m in manifest["memories"])
 if not source_retained:raise ValueError("historical feedback changed")
 report={"schema":SCHEMA,"status":"completed","goal_id":GOAL_ID,"baseline":manifest["baseline"],
  "native_count":current_count,"revision":current_revision,"checkpoint_sha256":checkpoint["sha256"],"continuity_verified":continuity,
  "historical_sources_unchanged":source_retained,"paired_decisions":manifest["paired_decisions"],
  "memory_changed_native_probe":manifest["counterfactual_memory_changed_selection"],
  "model_actions":[{"requested":o["requested_by_model"],"native_requested":o["requested_by_native"],"actual":o["actual_action"],"recalled":o["recalled_feedback"],"revision":o["revision"]} for o in outcomes],
  "model_report_private":bool(text),"report_labels_present":labels,"report_chars":len(text),"session_deleted":record.get("session_deleted",False),
  "api_requests":record["api_requests"],"tool_calls":len(calls),"probe_live_body_cycles":0,"physical_actuation":False,"audited_epoch":time.time()}
 atomic(experiment/"report.json",report)
 action_map={"walk":"W","observe":"O","refused":"R"}
 actions="".join(action_map.get(o["actual_action"],"X") for o in outcomes)
 recall=min(o["recalled_feedback"] for o in outcomes)
 return (f"MEMORY_GOAL=DONE;N=3;R={current_revision};ACT={actions};RECALL_MIN={recall};CONT={int(continuity)};"
         f"SOURCES={int(source_retained)};CF={int(report['memory_changed_native_probe'])};REPORT={int(bool(text) and labels)};"
         f"DEL={int(record.get('session_deleted',False))};SIG={checkpoint['sha256'][:16]}")

if __name__=="__main__":
 try:
  root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
  summary=admit(root) if MODE=="admit" else audit(root)
 except Exception as error:summary="MEMORY_GOAL=FAILED;ERROR="+type(error).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
