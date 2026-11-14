"""Read-only bounded Windows preflight for an hourly offline Awake task."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def main():
    if os.name != "nt":
        return "AWAKE=NOT_WINDOWS"
    if sys.version_info < (3, 11):
        return "AWAKE=BLOCKED;CAUSE=PYTHON_OLD"
    root = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "NasurayaAwake"
    try:
        free_mb = shutil.disk_usage(root.parent).free // (1024 * 1024)
    except OSError:
        return "AWAKE=BLOCKED;CAUSE=DISK_UNKNOWN"
    if free_mb < 100:
        return "AWAKE=BLOCKED;CAUSE=DISK_LOW"
    try:
        ps = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run(
            [str(ps), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference='Stop';"
             "$t=Get-ScheduledTask -TaskName 'NasurayaAwakeHourly' -ErrorAction SilentlyContinue;"
             "if ($null -eq $t) {'ABSENT'} else {'PRESENT'}"],
            text=True, capture_output=True, timeout=12, check=False
        )
        task = result.stdout.strip()
        if result.returncode != 0 or task not in ("ABSENT", "PRESENT"):
            return "AWAKE=BLOCKED;CAUSE=SCHEDULER_UNAVAILABLE"
        mode = "PRESENT" if root.exists() else "ABSENT"
        return "AWAKE=PREFLIGHT_OK;PY=3."+str(sys.version_info.minor)+";TASK="+task+";STATE="+mode+";FREE_MB="+str(min(99999, free_mb))
    except (OSError, ValueError, subprocess.SubprocessError):
        return "AWAKE=BLOCKED;CAUSE=PROBE_FAILED"

if __name__ == "__main__":
    try:
        summary = main()
    except BaseException:
        summary = "AWAKE=BLOCKED;CAUSE=UNEXPECTED"
    print(json.dumps({"status": "ok", "summary": summary}, separators=(",", ":")))
