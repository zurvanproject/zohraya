"""Install pinned private model worker as a SYSTEM AtStartup scheduled task.
Existing bridge, native ledger and source are preserved. No plaintext key here.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
import zipfile

PACKAGE_COMMIT="df08e5cb113991e5a22bedabe2ea7ba984d79f9a"
PACKAGE_SHA256="e747ee5d4aaa642c8300f589b98f3bfa63b339b15b4239e914e3afcea64b1ecf"
MANIFEST_SHA256="e8558cf14cb7ed1f6273a7dcfe75ba287d7a44ec39b3a2feb730d816072f909b"
URL="https://raw.githubusercontent.com/zurvanproject/zohraya/"+PACKAGE_COMMIT+"/deploy/tadash_server_v01.bundle.b64"
SCHEMA="nasuraya-server-worker/1"
TASK="NasurayaModelWorker"
NAMES={"worker.py","api.py","native_tools.py","cacert.pem","CERTIFI_LICENSE","FILES_SHA256.json"}
SMOKE={"goal_id":"nasuraya-server-install-smoke-20261107-v1","text":"Inspect the saved Tadash body. Perform exactly one safe bounded cycle, using observe when sleep pressure is high. Then evaluate_goal and report confirmed completion in Persian.","max_cycles":1}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def psq(text):return "'"+str(text).replace("'","''")+"'"
def powershell(script,timeout=20):
 p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command","$ErrorActionPreference='Stop';"+script],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
 if p.returncode:raise RuntimeError("ScheduledTaskOperation")
 return p.stdout.strip()

class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def fetch():
 try:
  import certifi
  context=ssl.create_default_context(cafile=certifi.where())
 except ImportError:context=ssl.create_default_context()
 with build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=context)).open(Request(URL,headers={"User-Agent":"NasurayaServerInstaller/1"}),timeout=20) as response:
  raw=response.read(800001)
 if len(raw)>800000:raise ValueError("bounded package")
 return raw

def verify(directory):
 directory=Path(directory)
 raw=(directory/"FILES_SHA256.json").read_bytes()
 if sha(raw)!=MANIFEST_SHA256:raise ValueError("worker manifest")
 manifest=json.loads(raw)
 if set(manifest)!=(NAMES-{"FILES_SHA256.json"}):raise ValueError("worker allowlist")
 for name,digest in manifest.items():
  path=directory/name
  if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or sha(path.read_bytes())!=digest:raise ValueError("worker file")
 return directory

def unpack(raw,directory):
 if len(raw)>800000 or sha(raw)!=PACKAGE_SHA256:raise ValueError("worker package")
 with zipfile.ZipFile(io.BytesIO(base64.b64decode(raw,validate=True))) as archive:
  entries=archive.infolist()
  if len(entries)!=6 or {e.filename for e in entries}!=NAMES or sum(e.file_size for e in entries)>500000:raise ValueError("archive bounds")
  for entry in entries:
   path=PurePosixPath(entry.filename)
   if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename or not stat.S_ISREG(entry.external_attr>>16):raise ValueError("regular archive")
   (Path(directory)/entry.filename).write_bytes(archive.read(entry))
 return verify(directory)

def atomic_json(path,value):
 path=Path(path);tmp=path.with_name(path.name+".tmp")
 with tmp.open("w",encoding="utf-8") as stream:
  stream.write(json.dumps(value,sort_keys=True,separators=(",",":")));stream.flush();os.fsync(stream.fileno())
 os.replace(tmp,path)

def main():
 if os.name!="nt":raise ValueError("Windows host")
 root=(Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker").resolve()
 if root.is_symlink() or root.is_junction() or json.loads((root/"owner.json").read_text())!={"schema":"nasuraya-model-worker/1"}:raise ValueError("dedicated service directory")
 acl=subprocess.run(["icacls.exe",str(root),"/inheritance:r","/grant:r","*S-1-5-18:(OI)(CI)F","*S-1-5-32-544:(OI)(CI)F"],capture_output=True,timeout=10)
 if acl.returncode:raise ValueError("private service ACL")
 if not (root/"api-key.dpapi").is_file() or not (root/"credential-installed.json").is_file():raise ValueError("protected credential required")
 if (root/"STOP").exists():raise ValueError("explicit pause active")
 marker=root/"installation.json"
 existing=powershell("if (Get-ScheduledTask -TaskName "+psq(TASK)+" -ErrorAction SilentlyContinue) { 'EXISTS' }")
 if existing:
  if not marker.is_file() or json.loads(marker.read_text()).get("package_sha256")!=PACKAGE_SHA256:raise ValueError("existing task requires explicit upgrade")
  return "WORKER=ALREADY_INSTALLED;TASK=OWNED"
 if (root/"config.json").exists():raise ValueError("existing configuration requires recovery")
 native=(Path(os.environ["LOCALAPPDATA"])/"NasurayaTadashV1").resolve()
 runtime=root/("runtime-"+PACKAGE_SHA256[:16])
 if not runtime.exists():
  payload=fetch()
  with tempfile.TemporaryDirectory(prefix="stage-",dir=root) as tmp:
   stage=Path(tmp)/"runtime";stage.mkdir();unpack(payload,stage);os.rename(stage,runtime)
 verify(runtime)
 # Check the exact installed native sources and original durable budget before
 # admitting a model goal; never initialize or reset the existing body here.
 p=subprocess.run([sys.executable,"-I","-X","utf8","-c",
  "import sys;sys.path.insert(0,sys.argv[1]);import native_tools;native_tools.verified_driver(sys.argv[2]);import worker;worker.native_budget(sys.argv[2],1)",
  str(runtime),str(native)],capture_output=True,timeout=15)
 if p.returncode:raise ValueError("existing native verification")
 for name in ("inbox","archive","state"):(root/name).mkdir(exist_ok=True)
 installation_id=uuid.uuid4().hex
 atomic_json(root/"config.json",{"schema":SCHEMA,"model":"gpt-6-astra","installation_id":installation_id,"require_system":True,"tadash_root":str(native)})
 args='-I -X utf8 "'+str(runtime/"worker.py")+'" --root "'+str(root)+'"'
 created=False;phase="register"
 try:
  script=(
   "$a=New-ScheduledTaskAction -Execute "+psq(sys.executable)+" -Argument "+psq(args)+" -WorkingDirectory "+psq(runtime)+";"
   "$t=New-ScheduledTaskTrigger -AtStartup;"
   "$p=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;"
   "$s=New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
   "Register-ScheduledTask -TaskName "+psq(TASK)+" -Action $a -Trigger $t -Principal $p -Settings $s -Description 'Private bounded Tadash worker; idle until owner admits a goal' | Out-Null")
  powershell(script);created=True;phase="startup"
  started=time.time()
  powershell("Start-ScheduledTask -TaskName "+psq(TASK))
  deadline=time.time()+25
  while time.time()<deadline:
   health_path=root/"health.json"
   if health_path.exists():
    health=json.loads(health_path.read_text(encoding="utf-8"))
    if health.get("installation_id")==installation_id and health.get("updated_epoch",0)>=started and health.get("system") is True and health.get("key_protected") is True:
     phase="admit"
     record={"schema":SCHEMA,"installation_id":installation_id,"package_commit":PACKAGE_COMMIT,"package_sha256":PACKAGE_SHA256,"manifest_sha256":MANIFEST_SHA256,"task":TASK,"installed_epoch":time.time(),"python":sys.version.split()[0]}
     atomic_json(marker,record)
     target=root/"inbox"/(SMOKE["goal_id"]+".json")
     if target.exists() or any((root/"archive").glob(SMOKE["goal_id"]+"*.json")):raise ValueError("smoke goal already admitted")
     atomic_json(target,SMOKE)
     return "WORKER=INSTALLED;SYSTEM=1;KEY=DPAPI;STARTUP=1;SMOKE=QUEUED;MODEL=G6ASTRA"
   time.sleep(1)
  raise RuntimeError("NoSystemHeartbeat")
 except Exception:
  if created:
   try:powershell("Stop-ScheduledTask -TaskName "+psq(TASK)+" -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName "+psq(TASK)+" -Confirm:$false",timeout=15)
   except Exception:pass
  for path in (root/"config.json",marker):
   try:path.unlink(missing_ok=True)
   except Exception:pass
  atomic_json(root/"installation-failed.json",{"phase":phase,"at":time.time()})
  raise

if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="WORKER=INSTALL_FAILED;ERROR="+type(error).__name__+((":"+str(error)) if type(error) is RuntimeError and str(error).isalnum() else "")
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
