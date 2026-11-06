#!/usr/bin/env python3
"""Local, read-only health report for the Nasuraya/Moltbook Windows bridge.

This tool never reads API credentials, uploads anything, or prints public posts.
It does not establish remote access or prove persistence after a reboot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import stat
import subprocess

SCHEMA = "nasuraya-moltbook-public-snapshot/1"
TASK_NAME = "NasurayaMoltbookReadOnly"
SNAPSHOT = "public_social_snapshot.json"
MAX_SNAPSHOT_BYTES = 1024 * 1024
DEFAULT_FRESHNESS_MINUTES = 45

# Only literal, unprivileged Task Scheduler reads; no network, scripts, or commands.
_POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
try {
    $task = Get-ScheduledTask -TaskName 'NasurayaMoltbookReadOnly' -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        @{ installed = $false; state = 'missing' } | ConvertTo-Json -Compress
    } else {
        $info = Get-ScheduledTaskInfo -TaskName 'NasurayaMoltbookReadOnly'
        @{ installed = $true; state = [string]$task.State;
           last_result = [int64]$info.LastTaskResult;
           last_run_utc = $info.LastRunTime.ToUniversalTime().ToString('o') } | ConvertTo-Json -Compress
    }
} catch {
    @{ installed = $false; state = 'unavailable' } | ConvertTo-Json -Compress
}
'''


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError("not a bounded timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone missing")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def snapshot_status(directory: Path, now: datetime, freshness_minutes: int) -> dict:
    result = {"state": "missing", "checked_at_utc": None}
    if directory.is_symlink():
        result["state"] = "unsafe_path"
        return result
    path = directory / SNAPSHOT
    if path.is_symlink():
        result["state"] = "unsafe_path"
        return result
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return result
    except OSError:
        result["state"] = "read_error"
        return result
    if not stat.S_ISREG(metadata.st_mode):
        result["state"] = "unsafe_path"
        return result
    if metadata.st_size < 2 or metadata.st_size > MAX_SNAPSHOT_BYTES:
        result["state"] = "invalid_size"
        return result
    try:
        with path.open("rb") as item:
            raw = item.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            result["state"] = "invalid_size"
            return result
        data = json.loads(raw.decode("utf-8"), parse_constant=lambda _x: (_ for _ in ()).throw(ValueError()))
    except (OSError, UnicodeError, ValueError, TypeError):
        result["state"] = "invalid_json"
        return result
    if not isinstance(data, dict) or any((
        data.get("schema") != SCHEMA,
        data.get("source") != "https://www.moltbook.com",
        data.get("agent") != "nasuraya",
        data.get("claim_status") != "claimed",
        not isinstance(data.get("posts"), list),
    )):
        result["state"] = "invalid_header"
        return result
    try:
        checked = _utc(data.get("checked_at_utc"))
    except (ValueError, OverflowError):
        result["state"] = "invalid_timestamp"
        return result
    result["checked_at_utc"] = _iso(checked)
    modified = datetime.fromtimestamp(metadata.st_mtime, tz=timezone.utc)
    # Both the source timestamp and file mtime must be fresh and non-future.
    if checked > now + timedelta(minutes=5) or modified > now + timedelta(minutes=5):
        result["state"] = "clock_anomaly"
    elif checked < now - timedelta(minutes=freshness_minutes) or modified < now - timedelta(minutes=freshness_minutes):
        result["state"] = "stale"
    else:
        result["state"] = "fresh"
    return result


def task_status(now: datetime, freshness_minutes: int, *, skip: bool = False) -> dict:
    result = {"state": "not_checked", "last_run_utc": None, "last_result": None}
    if skip:
        return result
    if platform.system() != "Windows":
        result["state"] = "not_windows"
        return result
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if proc.returncode != 0 or len(proc.stdout) > 2048:
            raise ValueError("invalid task query")
        data = json.loads(proc.stdout)
        if not isinstance(data, dict):
            raise ValueError("invalid task response")
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        result["state"] = "unavailable"
        return result
    if data.get("installed") is not True:
        result["state"] = "missing" if data.get("state") == "missing" else "unavailable"
        return result
    state = data.get("state")
    if not isinstance(state, str) or state.lower() not in {"ready", "running", "queued", "disabled"}:
        result["state"] = "unavailable"
        return result
    if state.lower() == "disabled":
        result["state"] = "disabled"
        return result
    code = data.get("last_result")
    if not isinstance(code, int) or isinstance(code, bool):
        result["state"] = "unavailable"
        return result
    result["last_result"] = code
    try:
        last = _utc(data.get("last_run_utc"))
    except (ValueError, OverflowError):
        result["state"] = "not_run"
        return result
    if last.year < 2020:
        result["state"] = "not_run"
        return result
    result["last_run_utc"] = _iso(last)
    if code != 0:
        result["state"] = "failed"
    elif last > now + timedelta(minutes=5):
        result["state"] = "clock_anomaly"
    elif last < now - timedelta(minutes=freshness_minutes):
        result["state"] = "stale"
    else:
        result["state"] = "recent_success"
    return result


def report(directory: Path, now: datetime, freshness_minutes: int = DEFAULT_FRESHNESS_MINUTES,
           skip_task: bool = False) -> dict:
    snap = snapshot_status(directory, now, freshness_minutes)
    task = task_status(now, freshness_minutes, skip=skip_task)
    if snap["state"] == "fresh" and task["state"] == "recent_success":
        overall = "recent_local_evidence"
    elif snap["state"] == "fresh" and task["state"] in ("not_checked", "not_windows"):
        overall = "snapshot_only"
    else:
        overall = "needs_attention"
    # Fixed, non-sensitive keys only. Never echo file contents, posts, machine or user names.
    return {
        "schema": "nasuraya-local-bridge-health/1",
        "generated_at_utc": _iso(now),
        "snapshot": snap,
        "scheduled_task": task,
        "overall": overall,
        "posting_enabled": False,
        "remote_control_enabled": False,
        "private_state_modified": False,
        "logoff_or_reboot_persistence_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local bridge status; never prints credentials or posts")
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Nasuraya" / "Moltbook")
    parser.add_argument("--freshness-minutes", type=int, default=DEFAULT_FRESHNESS_MINUTES)
    parser.add_argument("--skip-task", action="store_true", help="Do not query Windows Task Scheduler")
    args = parser.parse_args()
    if not 5 <= args.freshness_minutes <= 1440:
        parser.error("freshness minutes must be between 5 and 1440")
    result = report(args.state_dir, datetime.now(timezone.utc), args.freshness_minutes, args.skip_task)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
