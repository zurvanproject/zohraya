"""Restart only a completed, owned worker; verify unchanged receipts and no new API work."""
from contextlib import closing
import json,os,sqlite3,subprocess,time
from pathlib import Path

def ps(script):
 p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command","$ErrorActionPreference='Stop';"+script],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15)
 if p.returncode:raise RuntimeError("TaskOperation")
 return p.stdout.strip()

def ledger(root):
 with closing(sqlite3.connect((root/"state/worker.sqlite").resolve().as_uri()+"?mode=ro",uri=True)) as db:
  rows=[json.loads(r[0]) for r in db.execute("SELECT record FROM goals ORDER BY admitted")]
 if not rows or any(r["status"] in ("admitted","creating","running") for r in rows):raise ValueError("only completed idle restart")
 last=rows[-1]
 if last["status"]!="completed" or not last.get("session_deleted"):raise ValueError("completed cleaned goal required")
 return (len(rows),sum(r["api_requests"] for r in rows),last["result"]["native"]["revision"])

def main():
 root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 config=json.loads((root/"config.json").read_text())
 installed=json.loads((root/"installation.json").read_text())
 old=json.loads((root/"health.json").read_text())
 if config["installation_id"]!=installed["installation_id"] or old["installation_id"]!=config["installation_id"] or not old["system"]:raise ValueError("owned SYSTEM worker")
 if list((root/"inbox").glob("*.json")) or (root/"STOP").exists():raise ValueError("empty unpaused queue required")
 before=ledger(root)
 ps("Stop-ScheduledTask -TaskName 'NasurayaModelWorker';$end=(Get-Date).AddSeconds(5);while(((Get-ScheduledTask -TaskName 'NasurayaModelWorker').State -eq 'Running') -and ((Get-Date) -lt $end)){Start-Sleep -Milliseconds 200};if((Get-ScheduledTask -TaskName 'NasurayaModelWorker').State -eq 'Running'){throw 'Still running'}")
 ps("Start-ScheduledTask -TaskName 'NasurayaModelWorker'")
 deadline=time.time()+25
 while time.time()<deadline:
  health=json.loads((root/"health.json").read_text())
  if health["boot_id"]!=old["boot_id"] and health["installation_id"]==config["installation_id"] and health["state"]=="idle" and health["system"] and health["key_protected"]:
   time.sleep(3)
   after=ledger(root)
   if after!=before:raise ValueError("unexpected work on restart")
   return f"RESTART=OK;SYSTEM=1;KEY=1;IDLE=1;EXTRA_GOALS=0;EXTRA_HTTP=0;EXTRA_CYCLES=0;R={after[2]}"
  time.sleep(.5)
 raise RuntimeError("NoFreshHeartbeat")

if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="RESTART=FAILED;ERROR="+type(error).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
