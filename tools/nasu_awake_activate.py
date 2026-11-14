#!/usr/bin/env python3
"""One-shot activation of the already-imported Ubuntu Awake state.

Only call after an independently verified Windows scheduler freeze and a final,
newer, encrypted full snapshot import. This never contacts the old server.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

HOME=Path("/var/lib/nasuraya")
CONTROL=HOME/"awake-control.json"
STATE=HOME/"awake-stage"/"awake.sqlite3"
REPORT=HOME/"migration"/"latest-import.json"

def main():
    if os.geteuid()==0:
        raise RuntimeError("refusing root")
    os.umask(0o077)
    report=json.loads(REPORT.read_text(encoding="utf-8"))
    raw=Path(report["local_original"])
    if raw.parent!=HOME/"migration" or raw.is_symlink() or not raw.is_file():
        raise ValueError("original snapshot provenance invalid")
    if hashlib.sha256(raw.read_bytes()).hexdigest()!=report["raw_sha256"]:
        raise ValueError("original snapshot hash differs")
    if report.get("paused") is not True:
        raise ValueError("import status must indicate paused")
    working=Path(report.get("working_db") or STATE)
    if (working!=STATE and working.parent.parent!=HOME/"migration"/"working"):
        raise ValueError("untrusted current working database path")
    if not working.is_file() or working.is_symlink():
        raise ValueError("working database missing")
    with sqlite3.connect(working) as db:
        integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
        counts=[db.execute("SELECT COUNT(*) FROM "+tbl).fetchone()[0]
                for tbl in ("evidence","questions","ticks","ledger")]
        paused=db.execute("SELECT value FROM control WHERE name='paused'").fetchone()
        if integrity!="ok" or counts!=report["counts"] or paused!=("1",):
            raise ValueError("staged Awake is not the verified paused import")
    gate={"schema":"nasuraya-awake-offline/1","enabled":True,
          "import_id":report["id"],"source_sha256":report["raw_sha256"]}
    if CONTROL.exists():
        prior=json.loads(CONTROL.read_text(encoding="utf-8"))
        if prior.get("enabled") and prior!=gate:
            raise ValueError("different activation already exists")
        if prior==gate:
            print("ACTIVATION=ALREADY;IMPORT="+report["id"])
            return
    temp=HOME/"awake-control.tmp"
    if temp.exists():raise ValueError("unreviewed staged activation")
    with temp.open("x",encoding="utf-8") as f:
        json.dump(gate,f,sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(temp,0o600)
    temp.replace(CONTROL)
    print("ACTIVATION=AUTHORIZED;IMPORT="+report["id"]+";EVIDENCE="+str(counts[0])+
          ";NEXT=HOURLY_OFFLINE_TIMER")

if __name__=="__main__":
    try:main()
    except BaseException as e:
        print("ACTIVATION=BLOCKED;CAUSE="+type(e).__name__)
        raise SystemExit(2)
