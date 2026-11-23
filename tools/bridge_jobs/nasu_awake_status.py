"""Read-only verification receipt for dedicated Windows Tadash Awake hourly task."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from datetime import datetime, timezone


def main():
    if os.name != "nt":
        return "AWAKE=NOT_WINDOWS"
    program = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData"))
    root = program / "NasurayaAwake"
    if not root.exists():
        return "AWAKE=ABSENT"
    if root.is_symlink() or not root.is_dir():
        return "AWAKE=BLOCKED;CAUSE=ROOT_INVALID"
    path = root / "state" / "awake.sqlite3"
    run = root / "last_run.json"
    if not path.is_file() or path.is_symlink():
        return "AWAKE=PARTIAL;CAUSE=STATE_MISSING"
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            schema = db.execute("SELECT value FROM control WHERE name='schema'").fetchone()
            paused = db.execute("SELECT value FROM control WHERE name='paused'").fetchone()
            ticks = db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
            evidence = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            questions = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        finally:
            db.close()
        if schema != ("tadash-awake/1",) or paused not in (("0",), ("1",)):
            return "AWAKE=BLOCKED;CAUSE=SCHEMA"
        task = "UNKNOWN"
        exe = program.parent / "Windows" / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        exe = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        script = "$t=Get-ScheduledTask -TaskName 'NasurayaAwakeHourly' -ErrorAction SilentlyContinue; if ($null -eq $t) {'ABSENT'} else {$t.State.ToString()}"
        p = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=10, check=False)
        if p.returncode == 0 and p.stdout.strip() in ("Ready", "Running", "Disabled", "ABSENT", "Queued"):
            task = p.stdout.strip()
        last = "MISSING"
        if run.is_file() and not run.is_symlink() and run.stat().st_size < 2048:
            record = json.loads(run.read_text(encoding="utf-8"))
            if record.get("source") == "af98b4c88fceeaf1addaf809e669d6726580a212" and record.get("model_calls") == 0:
                last = record.get("status", "UNKNOWN")
        mode = "PAUSED" if paused == ("1",) else "ACTIVE"
        return "AWAKE=" + mode + ";TASK=" + task + ";TICKS=" + str(min(ticks,99999)) + ";EVENTS=" + str(min(evidence,99999)) + ";QUESTIONS=" + str(min(questions,99999)) + ";LAST=" + (last if last in ("paused","idle_no_evidence","idle_no_new_evidence","deferred_cooldown","deferred_budget","question_created","question_revised") else "UNKNOWN") + ";API=0"
    except (OSError, sqlite3.Error, json.JSONDecodeError, ValueError, subprocess.SubprocessError):
        return "AWAKE=BLOCKED;CAUSE=STATUS_READ_FAILED"

if __name__ == "__main__":
    try:
        summary=main()
    except BaseException:
        summary="AWAKE=BLOCKED;CAUSE=UNEXPECTED"
    print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
