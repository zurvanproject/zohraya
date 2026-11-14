"""Restore encrypted Windows Awake SQLite from GitHub Issue #216 on Ubuntu.
Only verified RSA recipient key on this VPS can decrypt. Preserve raw original
bytes and keep the imported working database paused (no duplicate scheduler).
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import urllib.request
import zlib

ROOT=Path("/var/lib/nasuraya")
PRIVATE=ROOT/"migration"/"recipient-private.pem"
ORIGINAL=ROOT/"migration"
STAGE=ROOT/"awake-stage"/"awake.sqlite3"
OWNER="zurvanproject"
URL="https://api.github.com/repos/zurvanproject/zohraya/issues/216/comments"
SHA_RE=re.compile(r"^[a-f0-9]{64}$")
ID_RE=re.compile(r"^[a-f0-9]{32}$")
def digest(blob): return hashlib.sha256(blob).hexdigest()
def fetch():
    comments=[]
    for page in range(1,5):
        request=urllib.request.Request(URL+"?per_page=100&page="+str(page),
            headers={"User-Agent":"Nasuraya-Migration-Importer","Accept":"application/vnd.github+json"})
        with urllib.request.urlopen(request,timeout=25) as response:
            content=response.read(2_000_001)
        if len(content)>2_000_000: raise ValueError("oversized public manifest")
        batch=json.loads(content)
        if not isinstance(batch,list):raise ValueError("invalid response")
        comments += [c["body"] for c in batch if
                     c.get("user",{}).get("login")==OWNER and isinstance(c.get("body"),str)]
        if len(batch)<100:break
    return comments

def kv(line):
    fields=line.split()
    result={}
    for part in fields[1:]:
        k,_,v=part.partition("=")
        if not k or not v or k in result:raise ValueError("invalid manifest fields")
        result[k]=v
    return result

def archive(comments):
    done=[]
    chunks=[]
    for body in comments:
        if body.startswith("NSAB1_DONE "):
            value=kv(body)
            if ID_RE.fullmatch(value.get("ID","")):done.append(value)
        elif body.startswith("NSAB1 "):
            first,sep,armored=body.partition("\n")
            if not sep:continue
            meta=kv(first)
            if (meta.get("ROLE") in ("iran","offsite") and
                ID_RE.fullmatch(meta.get("ID","")) and
                SHA_RE.fullmatch(meta.get("RAW","")) and
                SHA_RE.fullmatch(meta.get("ZLIB","")) and
                SHA_RE.fullmatch(meta.get("ENC",""))):
                chunks.append((meta,armored.strip()))
    for completed in reversed(done):
        archive_id=completed["ID"]
        data={}
        for role in ("iran","offsite"):
            seq=[(meta,armored) for meta,armored in chunks if meta["ID"]==archive_id and meta["ROLE"]==role]
            if not seq:break
            first=seq[0][0]
            match=re.fullmatch(r"([0-9]+)/([0-9]+)",first.get("PART",""))
            if not match:break
            total=int(match.group(2))
            if not 1<=total<=8 or len(seq)!=total:break
            ordered={}
            for meta,armored in seq:
                if any(meta.get(k)!=first.get(k) for k in ("RAW","ZLIB","ENC","EV","Q","T","L")):
                    raise ValueError("inconsistent archive metadata")
                part=re.fullmatch(r"([0-9]+)/([0-9]+)",meta["PART"])
                if part is None or int(part.group(2))!=total or int(part.group(1)) in ordered:
                    raise ValueError("duplicate or invalid archive part")
                ordered[int(part.group(1))]=armored
            if set(ordered)!=set(range(1,total+1)):break
            sealed=base64.b64decode("".join(ordered[i] for i in range(1,total+1)),validate=True)
            if digest(sealed)!=first["ENC"]:raise ValueError("encrypted hash mismatch")
            data[role]=(first,sealed)
        if len(data)!=2:continue
        ir,off=data["iran"][0],data["offsite"][0]
        if any(ir[k]!=off[k] for k in ("RAW","ZLIB","EV","Q","T","L")):
            raise ValueError("two recipients disagree")
        if any(ir[k]!=completed.get(k) for k in ("EV","Q","T","L")):
            raise ValueError("completed count mismatch")
        return archive_id,data
    raise ValueError("no verified two-recipient backup")

def decrypt(sealed):
    if not PRIVATE.is_file() or PRIVATE.is_symlink():
        raise ValueError("missing dedicated recipient key")
    if len(sealed)%384 or not 384<=len(sealed)<=384*1000:
        raise ValueError("invalid encrypted block count")
    pieces=[]
    for offset in range(0,len(sealed),384):
        result=subprocess.run(["/usr/bin/openssl","pkeyutl","-decrypt","-inkey",str(PRIVATE),
              "-pkeyopt","rsa_padding_mode:oaep","-pkeyopt","rsa_oaep_md:sha256",
              "-pkeyopt","rsa_mgf1_md:sha256"],input=sealed[offset:offset+384],
              capture_output=True,timeout=10,check=False)
        if result.returncode!=0:raise ValueError("RSA recipient key could not decrypt")
        pieces.append(result.stdout)
    return b"".join(pieces)

def inspect_db(path):
    conn=sqlite3.connect(path)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("damaged imported SQLite")
        schema=conn.execute("SELECT value FROM control WHERE name='schema'").fetchone()
        counts=[conn.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                for table in ("evidence","questions","ticks","ledger")]
        if schema!=("tadash-awake/1",):raise ValueError("invalid database schema")
        return counts
    finally:conn.close()

def verify_superset(older_path, newer_path, previous_counts, new_counts):
    """Preserve monotonic immutable evidence and earlier execution records."""
    if any(before>after for before,after in zip(previous_counts,new_counts)):
        raise ValueError("new snapshot has fewer records")
    with sqlite3.connect(older_path) as old, sqlite3.connect(newer_path) as new:
        if old.execute("SELECT value FROM control WHERE name='paused'").fetchone()!=("1",):
            raise ValueError("older stage is active; refusing to overwrite")
        for table, primary in (("evidence","id"),("ticks","seq"),("ledger","seq")):
            for row in old.execute("SELECT * FROM "+table):
                candidate=new.execute("SELECT * FROM "+table+" WHERE "+primary+"=?", (row[0],)).fetchone()
                if candidate!=row:
                    raise ValueError("history changed or missing in candidate")
        for topic,ident,revision,created in old.execute(
                "SELECT topic,id,revision,created_at FROM questions"):
            row=new.execute("SELECT id,revision,created_at FROM questions WHERE topic=?",(topic,)).fetchone()
            if row is None or row[0]!=ident or row[1]<revision or row[2]!=created:
                raise ValueError("earlier question continuity invalid")

def checkpoint_idle_stage(stage):
    """Safely finalize an idle, paused SQLite WAL before a verified state swap."""
    first=sqlite3.connect(stage,timeout=15)
    try:
        if first.execute("SELECT value FROM control WHERE name='paused'").fetchone()!=("1",):
            raise ValueError("stage must be paused to checkpoint")
        row=first.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is None or row[0]!=0:
            raise ValueError("stage SQLite WAL is busy")
    finally:
        first.close()
    second=sqlite3.connect(stage,timeout=15)
    try:
        mode=second.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if mode.lower()!="delete":
            raise ValueError("could not seal idle SQLite WAL")
    finally:
        second.close()
    for suffix in ("-wal","-shm"):
        if (stage.parent/(stage.name+suffix)).exists():
            raise ValueError("stage sqlite sidecar exists; refusing overwrite")

def backup_old_stage(stage, original_dir, old_report):
    ident=old_report.get("id")
    if not ID_RE.fullmatch(str(ident)):
        raise ValueError("old migration receipt ID invalid")
    destination=original_dir/("stage-before-"+ident+".sqlite3")
    if destination.exists():
        if inspect_db(destination)!=old_report.get("counts"):
            raise ValueError("old stage backup conflict")
        return
    tmp=original_dir/("stage-before-"+ident+".tmp")
    if tmp.exists():raise ValueError("interrupted previous stage backup")
    with sqlite3.connect(stage) as source, sqlite3.connect(tmp) as snapshot:
        source.backup(snapshot)
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("old backup integrity failure")
    os.chmod(tmp,0o600)
    tmp.replace(destination)

def run():
    os.umask(0o077)
    if os.geteuid()==0:raise ValueError("must run without root")
    archive_id,data=archive(fetch())
    meta,sealed=data["iran"]
    compressed=decrypt(sealed)
    if digest(compressed)!=meta["ZLIB"]:raise ValueError("compressed hash mismatch")
    inflater=zlib.decompressobj()
    raw=inflater.decompress(compressed,16_000_001)
    if not inflater.eof or inflater.unused_data or len(raw)>16_000_000:
        raise ValueError("invalid or oversized decompressed SQLite")
    if digest(raw)!=meta["RAW"]:raise ValueError("original database hash mismatch")
    ORIGINAL.mkdir(mode=0o700,parents=True,exist_ok=True)
    STAGE.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=ORIGINAL,prefix="candidate-",suffix=".sqlite3",delete=False) as t:
        t.write(raw);candidate=Path(t.name)
    try:
        counts=inspect_db(candidate)
        expected=[int(meta[k]) for k in ("EV","Q","T","L")]
        if counts!=expected:raise ValueError("Windows source counts do not match")
        rawfile=ORIGINAL/("windows-awake-"+meta["RAW"][:16]+".sqlite3")
        if not rawfile.exists():candidate.replace(rawfile)
        elif digest(rawfile.read_bytes())!=meta["RAW"]:raise ValueError("old original backup conflict")
        if STAGE.exists():
            current=inspect_db(STAGE)
            previous_report_path=ORIGINAL/"latest-import.json"
            if (ORIGINAL/"awake-control.json").exists():
                raise ValueError("unexpected activation path")
            control=ROOT/"awake-control.json"
            if control.exists():
                gate=json.loads(control.read_text())
                if gate.get("enabled"):
                    raise ValueError("cannot overwrite an activated Awake state")
            if current!=[0,0,0,0]:
                if not previous_report_path.is_file():
                    raise ValueError("previous imported source receipt missing")
                previous=json.loads(previous_report_path.read_text(encoding="utf-8"))
                if previous.get("counts")!=current or previous.get("paused") is not True:
                    raise ValueError("local state differs from previous import")
                if previous.get("raw_sha256")==meta["RAW"] and current==expected:
                    return "IMPORT=ALREADY;EV="+str(counts[0])+";Q="+str(counts[1])+";T="+str(counts[2])+";L="+str(counts[3])
                verify_superset(STAGE,rawfile,current,expected)
            checkpoint_idle_stage(STAGE)
            if current!=[0,0,0,0]:
                backup_old_stage(STAGE,ORIGINAL,previous)
        incoming=STAGE.parent/("awake-"+archive_id+".sqlite3")
        if incoming.exists():raise ValueError("unreviewed imported staging file")
        incoming.write_bytes(raw)
        with sqlite3.connect(incoming) as db:
            db.execute("UPDATE control SET value='1' WHERE name='paused'")
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("PRAGMA journal_mode=DELETE")
        if inspect_db(incoming)!=expected:raise ValueError("working copy was corrupted")
        incoming.replace(STAGE)
        report={"id":archive_id,"raw_sha256":meta["RAW"],"counts":expected,
                "offsite_cipher_sha256":data["offsite"][0]["ENC"],
                "paused":True,"local_original":str(rawfile)}
        (ORIGINAL/"latest-import.json").write_text(json.dumps(report,sort_keys=True))
        return "IMPORT=OK;EV="+str(counts[0])+";Q="+str(counts[1])+";T="+str(counts[2])+";L="+str(counts[3])+";PAUSED=1;OFFSITE=YES"
    finally:
        if candidate.exists():candidate.unlink()

if __name__=="__main__":
    try:status=run()
    except BaseException as exc:
        labels={
            "previous imported source receipt missing":"OLD_RECEIPT",
            "local state differs from previous import":"LOCAL_DRIFT",
            "stage is nonempty and differs":"NONEMPTY_STAGE",
            "new snapshot has fewer records":"NONMONOTONIC",
            "history changed or missing in candidate":"HISTORY_MISMATCH",
            "earlier question continuity invalid":"QUESTION_MISMATCH",
            "stage sqlite sidecar exists; refusing overwrite":"SIDECAR",
            "stage SQLite WAL is busy":"WAL_BUSY",
            "stage must be paused to checkpoint":"STAGE_ACTIVE",
            "could not seal idle SQLite WAL":"WAL_SEAL",
            "old stage backup conflict":"OLD_BACKUP",
            "old migration receipt ID invalid":"RECEIPT_ID",
            "old backup integrity failure":"OLD_BACKUP_INTEGRITY",
            "interrupted previous stage backup":"INCOMPLETE_BACKUP",
            "unreviewed imported staging file":"INCOMING_EXISTS",
            "source schema/count invalid":"SCHEMA",
            "original snapshot hash differs":"HASH",
            "cannot overwrite an activated Awake state":"ALREADY_ACTIVE",
            "inconsistent archive metadata":"INCONSISTENT_ARCHIVE",
        }
        detail=labels.get(str(exc),"UNKNOWN")
        if isinstance(exc, sqlite3.OperationalError):
            detail="SQLITE_LOCKED" if str(exc)=="database is locked" else "SQLITE_OPERATIONAL"
        status="IMPORT=BLOCKED;CAUSE="+type(exc).__name__+";DETAIL="+detail
    print(status)
