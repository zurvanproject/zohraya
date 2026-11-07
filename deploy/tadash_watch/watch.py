"""Bounded evening stability sampling. Standard library; no network or API key access."""
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,math,os,sqlite3,subprocess,sys,time
from pathlib import Path

SCHEMA="nasuraya-evening-watch/1"
INTERVAL=600

def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def read_json(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def atomic(p,v):
 p=Path(p);tmp=p.with_name(p.name+".tmp")
 with tmp.open("w",encoding="utf-8") as f:f.write(canonical(v));f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
def ro(p):
 db=sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
 db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
 return db

def task_info():
 ps="$ErrorActionPreference='Stop';$t=Get-ScheduledTask -TaskName 'NasurayaModelWorker';[ordered]@{state=[string]$t.State;enabled=[bool]$t.Settings.Enabled;system=($t.Principal.UserId -in @('SYSTEM','S-1-5-18'));sampler_system=[Security.Principal.WindowsIdentity]::GetCurrent().IsSystem}|ConvertTo-Json -Compress"
 p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15)
 if p.returncode:raise RuntimeError("task_unavailable")
 return json.loads(p.stdout)

def snapshot(worker_root,native_root,now=None,probe=task_info):
 now=time.time() if now is None else now
 worker_root=Path(worker_root);native_root=Path(native_root)
 health=read_json(worker_root/"health.json");config=read_json(worker_root/"config.json")
 with closing(ro(native_root/"state/session.sqlite")) as db:
  if db.execute("PRAGMA quick_check").fetchall()!=[("ok",)]:raise ValueError("native_integrity")
  records={r[0]:json.loads(r[1]) for r in db.execute("SELECT id,record FROM decisions ORDER BY seq")}
  row=db.execute("SELECT digest,value FROM runtime WHERE key='nasuraya-vps-body'").fetchone()
  if row is None:raise ValueError("native_runtime_missing")
  body=json.loads(row[1])
  if digest(body)!=row[0] or digest(body["payload"])!=body["sha256"]:raise ValueError("native_checksum")
 with closing(ro(worker_root/"state/worker.sqlite")) as db:
  if db.execute("PRAGMA quick_check").fetchall()!=[("ok",)]:raise ValueError("worker_integrity")
  goals={r[0]:json.loads(r[1]) for r in db.execute("SELECT id,record FROM goals ORDER BY admitted")}
 task=probe()
 issues=[]
 if health.get("installation_id")!=config.get("installation_id"):issues.append("health_identity")
 if not -5<=now-health.get("updated_epoch",0)<=45:issues.append("stale_heartbeat")
 if task.get("state")!="Running" or not task.get("enabled") or not task.get("system") or not health.get("system"):issues.append("worker_task")
 if health.get("state") not in ("idle","running"):issues.append("worker_state")
 unresolved=sum(r.get("status")=="running" for r in records.values())
 if unresolved:issues.append("unresolved_native")
 return {"at":now,"issues":issues,"task":task,"worker_state":health.get("state"),"worker_boot_id":health.get("boot_id"),
  "installation_id":config.get("installation_id"),"native_revision":body["payload"]["revision"],"checkpoint":body["sha256"],
  "native_count":sum(r.get("selected_action") is not None for r in records.values()),"native_unresolved":unresolved,
  "native_records":{k:digest(v) for k,v in records.items()},"worker_goals":{k:digest(v) for k,v in goals.items()},
  "goal_count":len(goals),"api_requests":sum(g.get("api_requests",0) for g in goals.values())}

def compare(current,baseline):
 issues=list(current["issues"])
 for name in ("installation_id","worker_boot_id","native_revision","checkpoint","native_count","goal_count","api_requests"):
  if current.get(name)!=baseline.get(name):issues.append("changed_"+name)
 for name in ("native_records","worker_goals"):
  if current.get(name)!=baseline.get(name):issues.append("changed_"+name)
 if not current["task"].get("sampler_system"):issues.append("sampler_not_system")
 return sorted(set(issues))

def db_at(root):
 db=sqlite3.connect(Path(root)/"watch.sqlite",timeout=5,isolation_level=None)
 db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA synchronous=FULL")
 db.execute("CREATE TABLE IF NOT EXISTS samples(slot TEXT PRIMARY KEY,at REAL NOT NULL,record TEXT NOT NULL)")
 return db

def read_samples(root):
 with closing(db_at(root)) as db:return [json.loads(r[0]) for r in db.execute("SELECT record FROM samples ORDER BY at,slot")]

def sample(root,now=None,collector=snapshot,final=False):
 root=Path(root);config=read_json(root/"config.json");now=time.time() if now is None else now
 if config["schema"]!=SCHEMA:raise ValueError("watch_schema")
 if now>=config["deadline"] and not final:return finalize(root,now,collector)
 if final and now<config["deadline"]:raise ValueError("deadline_not_reached")
 slot="final" if final else str(max(0,int((now-config["started"])/INTERVAL)))
 with closing(db_at(root)) as db:
  old=db.execute("SELECT record FROM samples WHERE slot=?",(slot,)).fetchone()
  if old:return json.loads(old[0])
 try:
  value=collector(config["worker_root"],config["native_root"],now=now)
  value["issues"]=compare(value,config["baseline"])
 except Exception as error:
  value={"at":now,"issues":["sample_"+type(error).__name__],"native_revision":None,"checkpoint":None}
 value.update(slot=slot,sampler_pid=os.getpid())
 with closing(db_at(root)) as db:
  db.execute("INSERT OR IGNORE INTO samples VALUES(?,?,?)",(slot,now,canonical(value)))
 return value

def summary_of(config,rows,now):
 final=any(r["slot"]=="final" for r in rows)
 times=sorted(r["at"] for r in rows)
 end=min(now,config["deadline"])
 edges=[config["started"]]+times+[end]
 max_gap=max([max(0,b-a) for a,b in zip(edges,edges[1:])] or [0])
 expected=max(1,math.ceil((end-config["started"])/INTERVAL) if now>=config["deadline"] else int((end-config["started"])/INTERVAL)+1)
 observed={int(r["slot"]) for r in rows if r["slot"]!="final"}
 missing=len(set(range(expected))-observed)
 bad=sum(bool(r["issues"]) for r in rows)
 last=rows[-1] if rows else {}
 boot_ids={r["worker_boot_id"] for r in rows if r.get("worker_boot_id")}
 return {"schema":SCHEMA,"status":"completed" if final else ("incomplete" if now>=config["deadline"] else "active"),
  "started":config["started"],"deadline":config["deadline"],"generated":now,"samples":len(rows),"bad_samples":bad,
  "issue_codes":sorted({x for r in rows for x in r["issues"]}),"missing_regular_slots":missing,"maximum_observation_gap_seconds":round(max_gap,3),
  "worker_boot_ids_observed":len(boot_ids),"revision":last.get("native_revision"),"checkpoint":last.get("checkpoint"),
  "final_sample_recorded":final,"last_sample_epoch":last.get("at"),"api_calls_by_monitor":0,
  "coverage_ok":final and missing==0 and max_gap<=900 and bool(times) and times[-1]>=config["deadline"],
  "scope":"10-minute sampled health; outages between samples may not be detected"}

def finalize(root,now=None,collector=snapshot):
 root=Path(root);config=read_json(root/"config.json");now=time.time() if now is None else now
 if now<config["deadline"]:raise ValueError("deadline_not_reached")
 # The last repeated task and deadline task may overlap. Lock a separate DB
 # so the actual sample DB remains usable while one final report is committed.
 with closing(sqlite3.connect(root/"final.lock.sqlite",timeout=5,isolation_level=None)) as guard:
  guard.execute("BEGIN EXCLUSIVE")
  marker=root/"final-report.json"
  if marker.exists():return read_json(marker)
  sample(root,now,collector,final=True)
  result=summary_of(config,read_samples(root),now)
  atomic(marker,result)
  lines=["Nasuraya evening stability watch","Window ends 2026-11-07 22:00 Asia/Tehran",
   "Status: "+result["status"],"Samples: "+str(result["samples"]),"Unhealthy samples: "+str(result["bad_samples"]),
   "Missing regular slots: "+str(result["missing_regular_slots"]),"Largest observation gap seconds: "+str(result["maximum_observation_gap_seconds"]),
   "Final native revision: "+str(result["revision"]),"Issues: "+",".join(result["issue_codes"]),
   "No model API requests. This is sampled health, not proof of continuous uptime."]
  (root/"final-report.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
  return result

def report(root,now=None):
 root=Path(root);config=read_json(root/"config.json");now=time.time() if now is None else now
 marker=root/"final-report.json"
 result=read_json(marker) if marker.exists() else summary_of(config,read_samples(root),now)
 sig=(result.get("checkpoint") or "none")[:16]
 return (f"WATCH={result['status'].upper()};S={result['samples']};BAD={result['bad_samples']};MISS={result['missing_regular_slots']};"
         f"GAP={int(result['maximum_observation_gap_seconds'])};R={result['revision']};COVER={int(result['coverage_ok'])};"
         f"FINAL={int(result['final_sample_recorded'])};API=0;END=2200TEHRAN;SIG={sig}")

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("sample","final","report"));p.add_argument("--root",required=True,type=Path)
 args=p.parse_args();config=read_json(args.root/"config.json")
 if config["script_sha256"]!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError("watch_source")
 if args.mode=="sample":sample(args.root)
 elif args.mode=="final":finalize(args.root)
 print(report(args.root))

if __name__=="__main__":
 try:main()
 except Exception as error:
  print("WATCH=FAILED;ERROR="+type(error).__name__)
  raise SystemExit(1)
