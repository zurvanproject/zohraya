#!/usr/bin/env python3
"""Offline continuity ledger: local heartbeat, hash chain, and SQLite backups.
No internet, GitHub, API key, paid model or third-party Python packages needed.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path("/var/lib/nasuraya/continuity")
ZERO = "0" * 64

def open_db(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(root / "continuity.sqlite3", timeout=30, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS observations(
        id INTEGER PRIMARY KEY, hour TEXT NOT NULL UNIQUE,
        observed_at TEXT NOT NULL, metrics TEXT NOT NULL,
        previous TEXT NOT NULL, digest TEXT NOT NULL)""")
    return db

def observe():
    stat = os.statvfs("/")
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                memory[key] = int(value.strip().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        uptime = round(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        uptime = None
    try:
        load = round(os.getloadavg()[0], 3)
    except OSError:
        load = None
    try:
        revision = subprocess.run(
            ["/usr/bin/git", "-C", "/var/lib/nasuraya/zohraya", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=8, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        commit = revision.stdout.strip() if revision.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    return {"schema": "offline-monitor-v1", "load": load, "uptime": uptime,
            "memory_kib": memory, "disk_available_bytes": stat.f_bavail * stat.f_frsize,
            "git_revision": commit}

def digest(prev, hour, observed, metrics):
    return hashlib.sha256(("\n".join((prev, hour, observed, metrics))).encode()).hexdigest()

def verify(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity failed")
    prev = ZERO
    last_hour = None
    count = 0
    for hour, when, metrics, previous, checksum in db.execute(
            "SELECT hour,observed_at,metrics,previous,digest FROM observations ORDER BY id"):
        if previous != prev or digest(prev, hour, when, metrics) != checksum:
            raise RuntimeError("Continuity ledger hash chain mismatch")
        if last_hour is not None and hour <= last_hour:
            raise RuntimeError("Continuity ledger order invalid")
        prev, last_hour = checksum, hour
        count += 1
    return {"integrity": "ok", "records": count, "last_hour": last_hour,
            "last_hash": prev}

def backup(db, root, now):
    target_dir = root / "backups"
    target_dir.mkdir(mode=0o700, exist_ok=True)
    name = "continuity-" + now.strftime("%Y-%m-%d") + ".sqlite3"
    tmp = target_dir / (name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    target = target_dir / name
    dest = sqlite3.connect(tmp)
    try:
        db.backup(dest)
    finally:
        dest.close()
    os.chmod(tmp, 0o600)
    checksum = hashlib.sha256(tmp.read_bytes()).hexdigest()
    tmp.replace(target)
    manifest = target_dir / (name + ".sha256")
    manifest_tmp = target_dir / (name + ".sha256.tmp")
    manifest_tmp.write_text(checksum + "  " + name + "\n", encoding="utf-8")
    os.chmod(manifest_tmp, 0o600)
    manifest_tmp.replace(manifest)
    return {"file": str(target), "sha256": checksum}

def tick(db, root, now):
    hour = now.strftime("%Y-%m-%dT%H:00Z")
    observed_at = now.isoformat(timespec="seconds")
    readings = json.dumps(observe(), sort_keys=True, separators=(",", ":"))
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT hour,digest FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        if row and hour < row[0]:
            raise RuntimeError("Clock rollback")
        already = db.execute("SELECT digest FROM observations WHERE hour=?", (hour,)).fetchone()
        if already:
            db.execute("COMMIT")
            return {"status": "already_recorded", "hour": hour, "hash": already[0]}
        previous = row[1] if row else ZERO
        checksum = digest(previous, hour, observed_at, readings)
        db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) VALUES(?,?,?,?,?)",
                   (hour, observed_at, readings, previous, checksum))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    checked = verify(db)
    saved = backup(db, root, now)
    return {"status": "recorded", "hour": hour, "records": checked["records"],
            "hash": checksum, "backup_sha256": saved["sha256"]}

def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("tick", "status", "verify", "backup"))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    db = open_db(args.root)
    try:
        if args.action == "tick":
            result = tick(db, args.root, now)
        elif args.action == "backup":
            result = backup(db, args.root, now)
        else:
            result = verify(db)
            if args.action == "status":
                result["mode"] = "offline_monitor"
                path = args.root / "backups"
                result["backup_days"] = len(list(path.glob("*.sqlite3"))) if path.exists() else 0
    finally:
        db.close()
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
