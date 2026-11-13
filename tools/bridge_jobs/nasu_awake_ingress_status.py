"""Independent read-only status of scheduled offline PR198 -> Awake ingress."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from datetime import datetime, timezone

EXPECTED = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"
TASK = "NasurayaAwakeIngress"

def query_task():
    ps = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = ("$t=Get-ScheduledTask -TaskName 'NasurayaAwakeIngress' -ErrorAction SilentlyContinue; "
              "if ($null -eq $t) {'ABSENT'} else {$t.State.ToString()}")
    p = subprocess.run([str(ps), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                       stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=12)
    value = p.stdout.strip()
    return value if p.returncode == 0 and value in ("ABSENT","Ready","Running","Disabled","Queued") else "UNKNOWN"

def main():
    if os.name != "nt":
        return "INGRESS=NOT_WINDOWS"
    root = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "NasurayaAwake"
    if not root.is_dir() or root.is_symlink():
        return "INGRESS=ABSENT"
    if not (root / "ingress_task.py").is_file() or not (root / "source_manifest.json").is_file():
        return "INGRESS=ABSENT"
    state = root / "state" / "awake.sqlite3"
    if not state.is_file() or state.is_symlink():
        return "INGRESS=BLOCKED;CAUSE=STATE_ABSENT"
    db = sqlite3.connect(state.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        n = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        q = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        t = db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
    finally:
        db.close()
    last = "PENDING"
    revision = 0
    at_age = "U"
    record = root / "last_ingress.json"
    if record.is_file() and not record.is_symlink() and record.stat().st_size <= 2048:
        data = json.loads(record.read_text(encoding="utf-8"))
        if (data.get("source_commit") == EXPECTED
                and data.get("source_kind") == "simulated_workshop_not_physical_sensors"
                and data.get("network_calls") == 0 and data.get("model_calls") == 0
                and data.get("external_actions") == 0):
            last = data.get("status", "UNKNOWN")
            revision = data.get("revision", 0)
            if last not in ("imported_simulation","recovered_uningested","deferred_hourly","capacity_review"):
                last = "UNKNOWN"
            if type(revision) is not int or not 0 <= revision <= 48:
                return "INGRESS=BLOCKED;CAUSE=REV_INVALID"
    task = query_task()
    mode = "ACTIVE" if task in ("Ready","Running") and n >= 6 and revision >= 1 else "PENDING"
    return ("INGRESS="+mode+";TASK="+task+";REV="+str(revision)+
            ";EVENTS="+str(min(99999,n))+";QUESTIONS="+str(min(99999,q))+
            ";TICKS="+str(min(99999,t))+";LAST="+last+
            ";SOURCE=SIM;API=0")

if __name__ == "__main__":
    try:
        summary = main()
    except BaseException:
        summary = "INGRESS=BLOCKED;CAUSE=STATUS_ERROR"
    print(json.dumps({"status":"ok","summary":summary}, separators=(",", ":")))
