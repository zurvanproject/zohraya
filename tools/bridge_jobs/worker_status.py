"""Public aggregate only: independent task, heartbeat, receipts and limits."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

def main():
 root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 ps="$ErrorActionPreference='Stop';$t=Get-ScheduledTask -TaskName 'NasurayaModelWorker';[ordered]@{state=[string]$t.State;system=($t.Principal.UserId -in @('SYSTEM','S-1-5-18'));startup=(@($t.Triggers|Where-Object {$_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger'}).Count -gt 0)}|ConvertTo-Json -Compress"
 result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15)
 if result.returncode:
  detail="NONE"
  if (root/"startup-error.json").exists():detail=json.loads((root/"startup-error.json").read_text()).get("error","UNKNOWN")
  return "WORKER=TASK_MISSING;ERROR="+(detail if re.fullmatch(r"[A-Za-z]{1,40}",detail) else "UNKNOWN")
 task=json.loads(result.stdout)
 health=json.loads((root/"health.json").read_text())
 config=json.loads((root/"config.json").read_text())
 if health["installation_id"]!=config["installation_id"]:raise ValueError("foreign heartbeat")
 fresh=time.time()-health["updated_epoch"]<45
 private=root/"state/worker.sqlite"
 with closing(sqlite3.connect(private.resolve().as_uri()+"?mode=ro",uri=True)) as db:
  row=db.execute("SELECT record FROM goals ORDER BY admitted DESC LIMIT 1").fetchone()
  record=json.loads(row[0]) if row else {}
 native=(record.get("result") or {}).get("native",{})
 goal=record.get("status","none").upper()
 if not re.fullmatch(r"[A-Z_]{1,16}",goal):goal="UNKNOWN"
 error=record.get("error") or "none"
 if not re.fullmatch(r"[A-Za-z0-9_]{1,32}",error):error="unknown"
 signature=native.get("checkpoint_sha256","none")[:16]
 return (f"WORKER={health['state'].upper()};FRESH={int(fresh)};TASK={task['state']};SYSTEM={int(task['system'] and health['system'])};KEY={int(health['key_protected'])};STARTUP={int(task['startup'])};GOAL={goal};N={native.get('completed_cycles',0)};R={native.get('revision',0)};DEL={int(record.get('session_deleted',False))};ERR={error};SIG={signature}")

if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="WORKER=STATUS_FAILED;ERROR="+type(error).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
