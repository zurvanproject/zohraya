#!/usr/bin/env python3
"""Tadash Awake offline continuation on Ubuntu.

No network, remote command, model/API call, or patient data.
Imports three scalar Linux health observations per day from the verified local
continuity ledger, runs the existing bounded Tadash question loop hourly, and
makes a SQLite-consistent hourly backup. Source data remains distinguishable
from artificial body/sensory workshop evidence.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

HOME=Path("/var/lib/nasuraya")
SRC=HOME/"awake-src"
STATE=HOME/"awake-stage"
LEDGER=HOME/"continuity"/"continuity.sqlite3"
CONTROL=HOME/"awake-control.json"
BACKUPS=HOME/"awake-backups"
PIN="90692bde9f1e4b5b7f311162b7c83127715df710"
ZERO="0"*64
TOPICS=(("load","server.load"),("mem","server.memory_available"),("disk","server.disk_available"))

def locked_source():
    p=subprocess.run(["/usr/bin/git","-C",str(SRC),"rev-parse","HEAD"],
                     capture_output=True,text=True,timeout=8,check=False)
    if p.returncode or p.stdout.strip()!=PIN:
        raise RuntimeError("Awake source SHA does not match pinned version")
    sys.path.insert(0,str(SRC))
    from tadash_awake import core
    return core

def gate():
    if not CONTROL.is_file() or CONTROL.is_symlink():
        return {"enabled":False}
    data=json.loads(CONTROL.read_text(encoding="utf-8"))
    if data.get("schema")!="nasuraya-awake-offline/1" or type(data.get("enabled")) is not bool:
        raise ValueError("invalid Awake activation gate")
    if data["enabled"]:
        report=json.loads((HOME/"migration"/"latest-import.json").read_text(encoding="utf-8"))
        if data.get("import_id")!=report.get("id"):
            raise ValueError("Awake activated for different imported archive")
    return data

def first_daily_reading(now):
    if not LEDGER.is_file():
        raise RuntimeError("offline continuity ledger missing")
    connection=sqlite3.connect("file:"+str(LEDGER)+"?mode=ro",uri=True,timeout=5)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise ValueError("monitor SQLite integrity failure")
        rows=connection.execute(
            "SELECT hour,observed_at,metrics,previous,digest FROM observations ORDER BY id").fetchall()
    finally: connection.close()
    prev=ZERO
    chosen=None
    today=now.strftime("%Y-%m-%d")
    for hour,at,raw,parent,digest in rows:
        actual=hashlib.sha256(("\n".join((prev,hour,at,raw))).encode()).hexdigest()
        if parent!=prev or actual!=digest:
            raise ValueError("monitor hash-chain mismatch")
        prev=digest
        if hour.startswith(today) and chosen is None:
            chosen=(hour,at,json.loads(raw))
    return chosen

def observations(now):
    found=first_daily_reading(now)
    if found is None:
        return []
    hour,observed_at,raw=found
    metrics=[
        raw.get("load"),
        raw.get("memory_kib",{}).get("MemAvailable"),
        raw.get("disk_available_bytes"),
    ]
    day=hour[:10]
    result=[]
    for (slug,topic),value in zip(TOPICS,metrics):
        if type(value) not in (int,float):
            raise ValueError("invalid scalar telemetry")
        result.append({
            "event_id":"host-"+day+"-"+slug,
            "topic":topic,
            "source_ref":"tadash://server/telemetry",
            "observed_at":observed_at,
            "value":value,
            "confidence":1.0,
        })
    return result

def sqlite_backup(now):
    BACKUPS.mkdir(mode=0o700,parents=True,exist_ok=True)
    name="awake-"+now.strftime("%Y%m%dT%H")+"Z.sqlite3"
    target=BACKUPS/name
    if target.exists():
        return {"status":"existing","file":name}
    temp=BACKUPS/(name+".tmp")
    if temp.exists(): raise ValueError("unreviewed incomplete backup")
    with sqlite3.connect(STATE/"awake.sqlite3",timeout=10) as original:
        with sqlite3.connect(temp,timeout=10) as copy:
            original.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("backup SQLite corrupt")
    os.chmod(temp,0o600)
    digest=hashlib.sha256(temp.read_bytes()).hexdigest()
    temp.replace(target)
    marker=BACKUPS/(name+".sha256")
    mark_tmp=BACKUPS/(name+".sha256.tmp")
    mark_tmp.write_text(digest+"  "+name+"\n",encoding="ascii")
    os.chmod(mark_tmp,0o600)
    mark_tmp.replace(marker)
    return {"status":"created","file":name,"sha256":digest}

def run(now=None):
    os.umask(0o077)
    if os.geteuid()==0:
        raise RuntimeError("refusing root")
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset()!=dt.timedelta(0):
        raise ValueError("UTC time required")
    core=locked_source()
    data=gate()
    if not (STATE/"awake.sqlite3").exists():
        raise RuntimeError("Awake state is missing")
    if not data["enabled"]:
        return {"status":"standby","enabled":False,"backup":sqlite_backup(now)}
    status=core.status(STATE)
    if status["paused"]:
        core.set_paused(STATE,False,now)
    sample=observations(now)
    if sample:
        with sqlite3.connect(STATE/"awake.sqlite3",timeout=10) as db:
            existing={row[0] for row in db.execute(
                "SELECT id FROM evidence WHERE id IN (?,?,?)",
                tuple(x["event_id"] for x in sample))}
        if len(existing)<len(sample):
            ingestion=core.ingest(STATE,sample,now=now)
        else:
            ingestion={"status":"already_ingested"}
    else:
        ingestion={"status":"no_telemetry"}
    tick=core.tick(STATE,now)
    backup=sqlite_backup(now)
    after=core.status(STATE)
    return {"status":"active","ingest":ingestion["status"],"tick":tick.get("status"),
            "counts":after["counts"],"backup":backup["status"],"source":"linux_telemetry",
            "network":False,"model_calls":0}

if __name__=="__main__":
    try:
        result=run()
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    except BaseException as exc:
        print(json.dumps({"status":"failed","error_class":type(exc).__name__}))
        raise SystemExit(2)
