"""Install the finite owner-authorized evening watch, preserving the model worker."""
import base64,hashlib,importlib.util,json,os,re,sqlite3,subprocess,sys,time,zlib,ssl,uuid
from email.utils import parsedate_to_datetime
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
from pathlib import Path
CODE_B64="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"
CODE_SHA256="ae07581fb7a5ecafb9274199364ab836a8529e07823b70e2ee1bbd867ecb3058"
DEADLINE=1794076200
SCHEMA="nasuraya-evening-watch/1"
PREFIX="NasurayaEveningWatch20261107"
WORKER_PACKAGE="e747ee5d4aaa642c8300f589b98f3bfa63b339b15b4239e914e3afcea64b1ecf"
WORKER_MANIFEST="e8558cf14cb7ed1f6273a7dcfe75ba287d7a44ec39b3a2feb730d816072f909b"

def psq(v):return "'"+str(v).replace("'","''")+"'"
def ps(code):
 p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command","$ErrorActionPreference='Stop';"+code],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=20)
 if p.returncode:
  phase=("register_sample" if PREFIX+"Sample" in code else "register_final") if "Register-ScheduledTask" in code else ("verify" if "Task definition" in code else ("start" if "Start-ScheduledTask" in code else "probe"))
  match=re.search(r"FullyQualifiedErrorId\s*:\s*([A-Za-z0-9_.,]+)",p.stderr)
  error_id=(match.group(1).split(",")[0] if match else "powershell")[:24]
  private=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker/monitoring/evening-20261107"
  if private.is_dir():
   (private/("task-error-"+phase+".json")).write_text(json.dumps({"phase":phase,"error_id":error_id,"stderr":p.stderr,"stdout":p.stdout,"at":time.time()}),encoding="utf-8")
  raise RuntimeError("TaskOperation_"+phase+"_"+error_id)
 return p.stdout.strip()
def load_watch(root):
 p=root/"watch.py"
 if hashlib.sha256(p.read_bytes()).hexdigest()!=CODE_SHA256:raise ValueError("watch source")
 s=importlib.util.spec_from_file_location("evening_watch",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def clock_reference(cafile):
 # Installer only: no token or private data. Bind the finite local schedule to
 # a fresh HTTPS Date header instead of changing the Windows system clock.
 url="https://api.github.com/repos/zurvanproject/zohraya/commits/64a7f40d57c06705ef8e692c4048f5b6c5cf36a1?nasuraya_watch="+uuid.uuid4().hex
 context=ssl.create_default_context(cafile=str(cafile))
 opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=context))
 start=time.time()
 with opener.open(Request(url,method="HEAD",headers={"User-Agent":"NasurayaEveningWatch/1","Cache-Control":"no-cache"}),timeout=10) as response:
  reference=parsedate_to_datetime(response.headers["Date"]).timestamp()
  if float(response.headers.get("Age","0"))>10:raise ValueError("stale clock reference")
 end=time.time()
 if end-start>10 or not 1794009600<=reference<DEADLINE-120:raise ValueError("reference outside evening window")
 return {"offset":(start+end)/2-reference,"reference_utc":reference,"host_epoch":(start+end)/2,"roundtrip_seconds":end-start,"source":"GitHub HTTPS Date; no-cache unique request"}

def verify_schedule(config,source):
 code="$epoch=[DateTime]::SpecifyKind([DateTime]'1970-01-01',[DateTimeKind]::Utc);"
 for mode,name in (("sample",config["sample_task"]),("final",config["final_task"])):
  arguments='-I -X utf8 "'+str(source)+'" '+mode+' --root "'+str(source.parent)+'"'
  code+=("$t=Get-ScheduledTask -TaskName "+psq(name)+";if($t.Principal.UserId -notin @('SYSTEM','S-1-5-18')){throw 'TaskPrincipal'};if($t.Actions[0].Execute -ne "+psq(sys.executable)+"){throw 'TaskExecutable'};if($t.Actions[0].Arguments -ne "+psq(arguments)+"){throw 'TaskArguments'};")
  if mode=="sample":code+="if($t.Triggers[0].Repetition.Interval -ne 'PT10M'){throw 'TaskCadence'};"
  else:code+="if([Math]::Abs((([DateTimeOffset]::Parse($t.Triggers[0].StartBoundary)).UtcDateTime-$epoch).TotalSeconds-"+str(config["deadline"])+") -gt 1){throw 'TaskDeadline'};"
 ps(code)

def main():
 if os.name!="nt":raise ValueError("Windows host required")
 worker=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 if json.loads((worker/"owner.json").read_text(encoding="utf-8"))!={"schema":"nasuraya-model-worker/1"}:raise ValueError("worker ownership")
 cfg=json.loads((worker/"config.json").read_text(encoding="utf-8"))
 runtime=worker/("runtime-"+WORKER_PACKAGE[:16])
 raw=(runtime/"FILES_SHA256.json").read_bytes()
 if hashlib.sha256(raw).hexdigest()!=WORKER_MANIFEST:raise ValueError("worker manifest")
 for name,expected in json.loads(raw).items():
  p=runtime/name
  if p.is_symlink() or not p.resolve().is_relative_to(runtime.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError("worker source")
 clock=clock_reference(runtime/"cacert.pem")
 host_deadline=int(round(DEADLINE+clock["offset"]))
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
  if config["schema"]!=SCHEMA or config.get("deadline_reference_utc")!=DEADLINE or config["script_sha256"]!=CODE_SHA256:raise ValueError("watch config conflict")
 else:
  baseline=watch.snapshot(worker,Path(cfg["tadash_root"]))
  if baseline["issues"] or baseline["native_revision"]!=9 or baseline["checkpoint"][:16]!="36ef52e76264c1bb":raise ValueError("healthy saved revision9 required")
  config={"schema":SCHEMA,"started":time.time(),"deadline":host_deadline,"deadline_reference_utc":DEADLINE,"clock_offset_seconds":clock["offset"],"clock_reference":clock,"interval_seconds":600,"worker_root":str(worker),
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
   end="$end=[DateTime]::SpecifyKind([DateTime]'1970-01-01',[DateTimeKind]::Utc).AddSeconds("+str(config["deadline"])+").ToLocalTime();"
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
    watch.atomic(root/"installation.json",{"schema":SCHEMA,"installed":time.time(),"tasks":names,"script_sha256":CODE_SHA256,"deadline_reference_utc":DEADLINE,"host_deadline":config["deadline"]})
    return "WATCH=INSTALLED;SYSTEM=1;S=1;BAD=0;EVERY=10MIN;END=2200TEHRAN;CLOCK=CALIBRATED;R=9;API=0"
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
 except Exception as error:
  detail=str(error).replace(" ","_")
  summary="WATCH=INSTALL_FAILED;ERROR="+type(error).__name__+((":"+detail) if type(error) in (RuntimeError,ValueError) and re.fullmatch(r"[A-Za-z0-9_]{1,70}",detail) else "")
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
