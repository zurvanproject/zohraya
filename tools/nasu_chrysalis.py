#!/usr/bin/env python3
"""Chrysalis: 24h *verified heartbeat* absence activates a bounded offline mission.

Not ChatGPT presence detection and not evidence of a war. Never installs a
model, changes Awake/DIOS/Bridge, accepts model-generated commands or networks
outside a localhost-only, independently sandboxed mission service.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys

SCHEMA = "nasuraya-chrysalis/1"
CONTROL = Path("/etc/nasuraya/chrysalis/control.json")
STATE = Path("/var/lib/nasuraya/chrysalis")
MISSION = Path("/usr/local/lib/nasuraya/nasu_offline_missions.py")
MISSION_SHA256 = "4dc38346ec79aaadd793ce83e3db41012b4cf1b52b94b553a5bae17f9300c9ea"
ABSENCE = dt.timedelta(hours=24)
FUTURE_TOLERANCE = dt.timedelta(minutes=2)
ISO = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")


def stamp(now):
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ValueError("trusted-utc-clock-required")
    return now.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_stamp(text):
    if not isinstance(text, str) or not ISO.fullmatch(text):
        raise ValueError("invalid-heartbeat-timestamp")
    return dt.datetime.fromisoformat(text[:-1] + "+00:00")


def _pairs(items):
    data = {}
    for key, value in items:
        if key in data:
            raise ValueError("duplicate-control-field")
        data[key] = value
    return data


def validate_control(data):
    if (type(data) is not dict or set(data) != {"schema", "armed", "last_seen_utc", "revision"}
            or data["schema"] != SCHEMA or type(data["armed"]) is not bool
            or type(data["revision"]) is not int or not 1 <= data["revision"] <= 10**12):
        raise ValueError("invalid-chrysalis-control")
    parse_stamp(data["last_seen_utc"])
    return data


def read_control(path=CONTROL, *, required_uid=0):
    """Root-owned local marker, never a ChatGPT/GitHub document or model text."""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    parent = path.parent
    for item in (parent, path):
        st = item.lstat()
        if st.st_uid != required_uid or st.st_mode & 0o022:
            raise ValueError("insecure-chrysalis-control-ownership")
    if not stat.S_ISDIR(parent.lstat().st_mode) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("nonregular-chrysalis-control")
    if path.stat().st_size > 2048:
        raise ValueError("oversized-chrysalis-control")
    return validate_control(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs))


def evaluate(control, now):
    """No inference about cause of absence; simple reproducible state machine."""
    stamp(now)
    if control is None or not validate_control(control)["armed"]:
        return {"mode": "DISARMED", "cause": "not-armed"}
    gap = now.astimezone(dt.timezone.utc) - parse_stamp(control["last_seen_utc"])
    if gap < -FUTURE_TOLERANCE:
        return {"mode": "HOLD", "cause": "clock-behind-last-heartbeat"}
    if gap >= ABSENCE:
        return {"mode": "CHRYSALIS", "cause": "heartbeat-overdue", "elapsed_seconds": int(gap.total_seconds())}
    return {"mode": "ARMED", "cause": "recent-verified-heartbeat",
            "remaining_seconds": max(0, int((ABSENCE - gap).total_seconds()))}


def set_owner_control(action, *, path=CONTROL, now=None):
    """One-time arming and owner presence, from root-controlled console only."""
    if os.geteuid() != 0:
        raise PermissionError("root-console-required-for-heartbeat")
    if action not in ("arm", "heartbeat", "disarm"):
        raise ValueError("unknown-control-action")
    now = now or dt.datetime.now(dt.timezone.utc)
    timestamp = stamp(now)
    path = Path(path)
    if path.parent.is_symlink():
        raise ValueError("control-parent-link")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    parent = path.parent.lstat()
    if parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError("insecure-control-parent")
    previous = read_control(path)
    if action == "heartbeat" and (previous is None or not previous["armed"]):
        raise ValueError("must-arm-before-heartbeat")
    if previous and parse_stamp(timestamp) < parse_stamp(previous["last_seen_utc"]):
        raise ValueError("clock-rollback-requires-manual-review")
    armed = action != "disarm"
    data = {"schema": SCHEMA, "armed": armed,
            "last_seen_utc": timestamp, "revision": previous["revision"] + 1 if previous else 1}
    temp = path.with_name(".control.json.new")
    if temp.exists() or temp.is_symlink():
        raise ValueError("unreviewed-control-temp-file")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return {"mode": "ARMED" if armed else "DISARMED", "revision": data["revision"],
            "last_seen_utc": timestamp}


def verify_mission(path=MISSION, *, expected_hash=MISSION_SHA256, required_uid=0):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != required_uid
            or info.st_mode & 0o022 or info.st_size > 200_000):
        return False
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return sha == expected_hash


def _db(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (state.is_symlink() or not state.is_dir() or state.stat().st_mode & 0o077):
        raise ValueError("insecure-chrysalis-state-directory")
    db = sqlite3.connect(state / "runs.sqlite3", timeout=20)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS runs("
               "day TEXT PRIMARY KEY, state TEXT NOT NULL, started_at TEXT NOT NULL,"
               "heartbeat_revision INT NOT NULL, outcome_sha256 TEXT)")
    db.commit()
    return db


def mission_process(path):
    """Only the one pinned existing mission runner; output is DATA, never shell."""
    result = subprocess.run(
        ["/usr/bin/python3", str(path), "run"], timeout=680,
        capture_output=True, text=True, check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": "/var/lib/nasuraya",
             "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        return {"status": "mission-failed", "exit": result.returncode}
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {"status": "mission-invalid-output"}
    allowed = {"completed", "completed_without_qwen", "already_reserved"}
    return {"status": payload.get("status") if type(payload) is dict and payload.get("status") in allowed
            else "mission-unexpected-status"}


def tick(*, now=None, control_path=CONTROL, state_dir=STATE, mission_path=MISSION,
         runner=mission_process, marker_uid=0, mission_uid=0):
    """Exactly one bounded mission attempt per UTC day, only after owner-arm."""
    if os.geteuid() == 0:
        raise PermissionError("chrysalis-worker-refuses-root")
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp(now)
    control = read_control(control_path, required_uid=marker_uid)
    state = evaluate(control, now)
    if state["mode"] != "CHRYSALIS":
        return state
    if not verify_mission(mission_path, required_uid=mission_uid):
        return {"mode": "HOLD", "cause": "reviewed-local-mission-not-installed"}
    state_dir = Path(state_dir)
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = state_dir / "runner.lock"
    if lock_path.is_symlink():
        raise ValueError("symlinked-run-lock")
    with lock_path.open("a+") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(_db(state_dir)) as db:
            day = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%d")
            if db.execute("SELECT 1 FROM runs WHERE day=?", (day,)).fetchone():
                return {"mode": "CHRYSALIS", "cause": "daily-mission-already-reserved", "day": day}
            # Owner signal could have arrived between entering tick and taking lock.
            refreshed = read_control(control_path, required_uid=marker_uid)
            if (refreshed is None or refreshed["revision"] != control["revision"]
                    or evaluate(refreshed, now)["mode"] != "CHRYSALIS"):
                return {"mode": "ARMED", "cause": "fresh-owner-signal"}
            db.execute("INSERT INTO runs(day,state,started_at,heartbeat_revision) VALUES(?,?,?,?)",
                       (day, "reserved", stamp(now), control["revision"]))
            db.commit()
            try:
                result = runner(mission_path)
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                result = {"status": "mission-failed", "error_class": type(exc).__name__}
            if type(result) is not dict or type(result.get("status")) is not str:
                result = {"status": "mission-invalid-result"}
            digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
            outcome = result["status"]
            db.execute("UPDATE runs SET state=?,outcome_sha256=? WHERE day=?", (outcome, digest, day))
            db.commit()
            return {"mode": "CHRYSALIS", "day": day, "mission": outcome, "receipt_sha256": digest,
                    "model_authority": "none", "trigger_is_war_detection": False}


def status(*, now=None, control_path=CONTROL, state_dir=STATE):
    now = now or dt.datetime.now(dt.timezone.utc)
    response = evaluate(read_control(control_path), now)
    file = Path(state_dir) / "runs.sqlite3"
    if file.is_file() and not file.is_symlink():
        with closing(sqlite3.connect("file:" + str(file) + "?mode=ro", uri=True)) as db:
            response["recent"] = db.execute("SELECT day,state FROM runs ORDER BY day DESC LIMIT 3").fetchall()
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("arm", "heartbeat", "disarm", "tick", "status"))
    args = parser.parse_args()
    if args.command in ("arm", "heartbeat", "disarm"):
        report = set_owner_control(args.command)
    elif args.command == "tick":
        report = tick()
    else:
        report = status()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
