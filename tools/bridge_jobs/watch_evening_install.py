"""Install the finite owner-authorized evening watch, preserving the model worker."""
import base64,hashlib,importlib.util,json,os,sqlite3,subprocess,sys,time,zlib
from pathlib import Path
CODE_B64="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"
CODE_SHA256="e77d9b4abd809a7a87b9b5599c1d112192357c57250f21c50cbf01d5e679c98d"
DEADLINE=1794076200
SCHEMA="nasuraya-evening-watch/1"
PREFIX="NasurayaEveningWatch20261107"
WORKER_PACKAGE="e747ee5d4aaa642c8300f589b98f3bfa63b339b15b4239e914e3afcea64b1ecf"
WORKER_MANIFEST="e8558cf14cb7ed1f6273a7dcfe75ba287d7a44ec39b3a2feb730d816072f909b"

def psq(v):return "'"+str(v).replace("'","''")+"'"
def ps(code):
 p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command","$ErrorActionPreference='Stop';"+code],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=20)
 if p.returncode:raise RuntimeError("TaskOperation")
 return p.stdout.strip()
def load_watch(root):
 p=root/"watch.py"
 if hashlib.sha256(p.read_bytes()).hexdigest()!=CODE_SHA256:raise ValueError("watch source")
 s=importlib.util.spec_from_file_location("evening_watch",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def verify_schedule(config,source):
 code="$epoch=[DateTime]::SpecifyKind([DateTime]'1970-01-01',[DateTimeKind]::Utc);"
 for mode,name in (("sample",config["sample_task"]),("final",config["final_task"])):
  arguments='-I -X utf8 "'+str(source)+'" '+mode+' --root "'+str(source.parent)+'"'
  code+=("$t=Get-ScheduledTask -TaskName "+psq(name)+";if(($t.Principal.UserId -notin @('SYSTEM','S-1-5-18')) -or ($t.Actions[0].Execute -ne "+psq(sys.executable)+") -or ($t.Actions[0].Arguments -ne "+psq(arguments)+")){throw 'Task definition'};")
  if mode=="sample":code+="if($t.Triggers[0].Repetition.Interval -ne 'PT10M'){throw 'Task cadence'};"
  else:code+="if([Math]::Abs((([DateTimeOffset]::Parse($t.Triggers[0].StartBoundary)).UtcDateTime-$epoch).TotalSeconds-"+str(DEADLINE)+") -gt 1){throw 'Task deadline'};"
 ps(code)

def main():
 if os.name!="nt" or time.time()>=DEADLINE-120:raise ValueError("Windows evening window")
 worker=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 if json.loads((worker/"owner.json").read_text(encoding="utf-8"))!={"schema":"nasuraya-model-worker/1"}:raise ValueError("worker ownership")
 cfg=json.loads((worker/"config.json").read_text(encoding="utf-8"))
 runtime=worker/("runtime-"+WORKER_PACKAGE[:16])
 raw=(runtime/"FILES_SHA256.json").read_bytes()
 if hashlib.sha256(raw).hexdigest()!=WORKER_MANIFEST:raise ValueError("worker manifest")
 for name,expected in json.loads(raw).items():
  p=runtime/name
  if p.is_symlink() or not p.resolve().is_relative_to(runtime.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError("worker source")
 root=worker/"monitoring/evening-20261107"
 marker=root/"owner.json"
 if root.exists() and (root.is_symlink() or root.is_junction() or (any(root.iterdir()) and not marker.is_file())):raise ValueError("monitor directory")
 root.mkdir(parents=True,exist_ok=True)
 if marker.exists():
  if json.loads(marker.read_text(encoding="utf-8"))!={"schema":SCHEMA}:raise ValueError("monitor owner")
 else:marker.write_text(json.dumps({"schema":SCHEMA}),encoding="utf-8")
 raw=zlib.decompress(base64.b64decode(CODE_B64,validate=True))
 if len(raw)>32000 or hashlib.sha256(raw).hexdigest()!=CODE_SHA256:raise ValueError("pinned sampler")
 source=root/"watch.py"
 if source.exists() and source.read_bytes()!=raw:raise ValueError("existing sampler differs")
 if not source.exists():source.write_bytes(raw)
 watch=load_watch(root)
 config_path=root/"config.json"
 if config_path.exists():
  config=watch.read_json(config_path)
  if config["schema"]!=SCHEMA or config["deadline"]!=DEADLINE or config["script_sha256"]!=CODE_SHA256:raise ValueError("watch config conflict")
 else:
  baseline=watch.snapshot(worker,Path(cfg["tadash_root"]))
  if baseline["issues"] or baseline["native_revision"]!=9 or baseline["checkpoint"][:16]!="36ef52e76264c1bb":raise ValueError("healthy saved revision9 required")
  config={"schema":SCHEMA,"started":time.time(),"deadline":DEADLINE,"interval_seconds":600,"worker_root":str(worker),
          "native_root":cfg["tadash_root"],"baseline":baseline,"script_sha256":CODE_SHA256,"sample_task":PREFIX+"Sample","final_task":PREFIX+"Final"}
  watch.atomic(config_path,config)
 names=[config["sample_task"],config["final_task"]]
 existing=ps("@("+",".join(psq(n) for n in names)+") | ForEach-Object {if(Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue){$_}}")
 if existing:
  if set(existing.splitlines())!=set(names):raise ValueError("partial task installation")
  verify_schedule(config,source)
  return "WATCH=ALREADY_INSTALLED;"+watch.report(root)
 created=[]
 try:
  for mode,name in (("sample",names[0]),("final",names[1])):
   arguments='-I -X utf8 "'+str(source)+'" '+mode+' --root "'+str(root)+'"'
   end="$end=[DateTime]::SpecifyKind([DateTime]'1970-01-01',[DateTimeKind]::Utc).AddSeconds("+str(DEADLINE)+").ToLocalTime();"
   trigger=("$begin=(Get-Date).AddSeconds(4);$t=New-ScheduledTaskTrigger -Once -At $begin -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration ($end-$begin);"
            if mode=="sample" else "$t=New-ScheduledTaskTrigger -Once -At $end;")
   script=(end+trigger+"$a=New-ScheduledTaskAction -Execute "+psq(sys.executable)+" -Argument "+psq(arguments)+" -WorkingDirectory "+psq(root)+";"
    "$p=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;"
    "$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -StartWhenAvailable;"
    "Register-ScheduledTask -TaskName "+psq(name)+" -Action $a -Trigger $t -Principal $p -Settings $s -Description 'Read-only sampled worker and memory stability until 22:00 Tehran; no model API' | Out-Null")
   ps(script);created.append(name)
  verify_schedule(config,source)
  ps("Start-ScheduledTask -TaskName "+psq(names[0]))
  end=time.time()+25
  while time.time()<end:
   rows=watch.read_samples(root)
   if rows:
    first=rows[0]
    if first["issues"] or not first.get("task",{}).get("sampler_system"):raise RuntimeError("FirstSampleUnhealthy")
    watch.atomic(root/"installation.json",{"schema":SCHEMA,"installed":time.time(),"tasks":names,"script_sha256":CODE_SHA256,"deadline":DEADLINE})
    return "WATCH=INSTALLED;SYSTEM=1;S=1;BAD=0;EVERY=10MIN;END=2200TEHRAN;R=9;API=0"
   time.sleep(1)
  raise RuntimeError("NoSystemSample")
 except Exception:
  for name in reversed(created):
   try:ps("Stop-ScheduledTask -TaskName "+psq(name)+" -ErrorAction SilentlyContinue;Unregister-ScheduledTask -TaskName "+psq(name)+" -Confirm:$false")
   except Exception:pass
  watch.atomic(root/"installation-failed.json",{"schema":SCHEMA,"at":time.time()})
  raise

if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="WATCH=INSTALL_FAILED;ERROR="+type(error).__name__+((":"+str(error)) if type(error) is RuntimeError and str(error).isalnum() else "")
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
