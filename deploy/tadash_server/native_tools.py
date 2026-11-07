"""One bounded local native invocation; isolated child of the private worker."""
from contextlib import closing
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

PACKAGE_SHA = "6a0c9fe013aad59716b251c66aadec6081daa764ac76bfdb2dc0763ab2f049cb"
MANIFEST_SHA = "1ffedf1f438a2e3b9178a19703cfb2037c5d0296a94743ff9391493edae65d15"
MAX_CYCLES = 3
MAX_CALLS = 12


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def validate(call):
    if not isinstance(call,dict) or set(call)!={"call_key","name","arguments","goal_id","max_cycles"} or not isinstance(call["goal_id"],str) or not re.fullmatch(r"nasuraya-[A-Za-z0-9_-]{1,80}",call["goal_id"]):
        raise ValueError("bounded goal contract")
    if not isinstance(call["call_key"],str) or not re.fullmatch(r"[0-9a-f]{64}",call["call_key"]):
        raise ValueError("hashed call identity")
    if type(call["max_cycles"]) is not int or not 1<=call["max_cycles"]<=3:
        raise ValueError("goal cycle cap")
    name,args=call["name"],call["arguments"]
    if not isinstance(args,dict) or name not in ("observe_body","request_body_action","evaluate_goal"):
        raise ValueError("declared tool required")
    if name=="request_body_action":
        if set(args)!={"action"} or args["action"] not in ("walk","observe"):
            raise ValueError("bounded action required")
    elif args:
        raise ValueError("empty arguments required")


def verified_driver(root):
    runtime=Path(root)/("runtime-"+PACKAGE_SHA[:16])
    raw=(runtime/"FILES_SHA256.json").read_bytes()
    if sha(raw)!=MANIFEST_SHA:
        raise ValueError("installed source manifest mismatch")
    for name,expected in json.loads(raw).items():
        path=runtime/name
        if path.is_symlink() or not path.resolve().is_relative_to(runtime.resolve()) or sha(path.read_bytes())!=expected:
            raise ValueError("installed source mismatch")
    spec=importlib.util.spec_from_file_location("tadash_vps_driver",runtime/"driver.py")
    driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
    return driver


def goal_ledger(path,baseline,goal_id,max_cycles):
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1:
            raise ValueError("regular goal ledger required")
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as probe:
            row=probe.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row is None or row[0]!="nasuraya-model-goal/1":
                raise ValueError("foreign goal ledger; no reset")
    db=sqlite3.connect(path,timeout=0,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls(
          call_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,name TEXT NOT NULL,
          phase TEXT NOT NULL,decision_id TEXT,request TEXT,output TEXT);
    """)
    config={"goal_id":goal_id,"max_cycles":max_cycles,"max_calls":MAX_CALLS,
            "baseline_cycles":baseline,"package_sha256":PACKAGE_SHA}
    old=db.execute("SELECT value FROM meta WHERE key='contract'").fetchone()
    if old is None:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("INSERT INTO meta VALUES('schema','nasuraya-model-goal/1')")
            db.execute("INSERT INTO meta VALUES('contract',?)",(canonical(config),))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK");db.close();raise
    else:
        config=json.loads(old[0])
        if {k:config[k] for k in ("goal_id","max_cycles","max_calls","package_sha256")} != {
            "goal_id":goal_id,"max_cycles":max_cycles,"max_calls":MAX_CALLS,"package_sha256":PACKAGE_SHA}:
            db.close();raise ValueError("stored goal differs; no reset")
    return db,config


def make_output(engine,UnifiedBody,db,record=None,upper="none",replay=0,*,goal_id,max_cycles):
    body=UnifiedBody.restore(engine.runtime("nasuraya-vps-body"))
    state=body.owner.body()["minimum_state"]
    checkpoint=body.checkpoint()
    count=db.execute("SELECT count(*) FROM calls WHERE name='request_body_action' AND phase='complete'").fetchone()[0]
    actual=(record or {}).get("actual_outcome") or {}
    result={"goal_id":goal_id,"complete":count==max_cycles,"completed_cycles":count,
            "max_cycles":max_cycles,"revision":body.revision,"checkpoint_sha256":checkpoint["sha256"],
            "energy":state["energy"],"fatigue":state["fatigue"],"pain":state["pain"],
            "sleep_pressure":state["sleep_pressure"],"requested_by_model":upper,
            "requested_by_native":(record or {}).get("selected_action","none"),
            "actual_action":actual.get("selected_action","none"),
            "recalled_feedback":len((record or {}).get("recalled_feedback_ids",[])),
            "replay_extra_cycles":replay,"physical_actuation":False}
    for name in ("energy","fatigue","pain","sleep_pressure"):
        if type(result[name]) not in (int,float) or not math.isfinite(result[name]):
            raise ValueError("invalid native observation")
    return result


def operate(call,root):
    validate(call)
    driver=verified_driver(root)
    with driver.host_lock(Path(root)/"state") as state,driver.native_runtime() as runtime:
        ReflectionCycle,ReflectiveBody,UnifiedBody,canonical_native,prepare_defaults,sleep_fixture=runtime
        driver.checked_ledger(state/"session.sqlite")
        prepare_defaults()
        with ReflectionCycle(state/"session.sqlite") as engine:
            native_records=engine.export()["decisions"]
            if any(r["status"]=="running" for r in native_records):
                raise ValueError("unresolved native operation")
            baseline=sum((r.get("actual_outcome") or {}).get("body_checkpoint") is not None for r in native_records)
            goal_directory=state/"worker-goals"
            goal_directory.mkdir(exist_ok=True)
            db,config=goal_ledger(goal_directory/(sha(call["goal_id"].encode())+".sqlite"),baseline,call["goal_id"],call["max_cycles"])
            try:
                key=call["call_key"];fingerprint=sha(canonical(call).encode())
                old=db.execute("SELECT * FROM calls WHERE call_key=?",(key,)).fetchone()
                if old is not None:
                    if old["fingerprint"]!=fingerprint:
                        raise ValueError("conflicting call replay")
                    if old["phase"]=="complete":
                        return json.loads(old["output"])
                elif db.execute("SELECT count(*) FROM calls").fetchone()[0]>=MAX_CALLS:
                    raise ValueError("persistent tool budget exhausted")
                record=None;upper="none";extra=0
                if call["name"]=="request_body_action":
                    upper=call["arguments"]["action"]
                    body=UnifiedBody.restore(engine.runtime("nasuraya-vps-body"))
                    before=body.revision
                    if old is None:
                        used=db.execute("SELECT count(*) FROM calls WHERE name='request_body_action'").fetchone()[0]
                        if used>=call["max_cycles"]:
                            raise ValueError("persistent goal cycle budget exhausted")
                        if sum(r["selected_action"] is not None for r in native_records)>=20:
                            raise ValueError("native action budget exhausted")
                        observed=db.execute("SELECT value FROM meta WHERE key='observed'").fetchone()
                        if observed is None or observed[0]!=body.checkpoint()["sha256"]:
                            raise ValueError("fresh body observation required")
                        completed=db.execute("SELECT count(*) FROM calls WHERE name='request_body_action' AND phase='complete'").fetchone()[0]
                        if baseline!=config["baseline_cycles"]+completed:
                            raise ValueError("out-of-band native cycles")
                        decision_id="vps-cycle-"+str(len(native_records)+1)
                        req=driver.request(decision_id,body)
                        for candidate in req["actions"]:
                            preference=.9 if candidate["id"]==upper else .6
                            for field in ("respect","honesty","balance","dignity","compassion"):
                                candidate["score"][field]=preference
                        db.execute("INSERT INTO calls VALUES(?,?,?,'started',?,?,NULL)",
                                   (key,fingerprint,call["name"],decision_id,canonical(req)))
                    else:
                        decision_id=old["decision_id"];req=json.loads(old["request"])
                    previous=engine.get(decision_id)
                    if previous is not None and previous["status"]=="running":
                        raise ValueError("unresolved native effect; do not repeat")
                    record=ReflectiveBody(engine,key="nasuraya-vps-body").cycle(
                        req,at_utc=req["at_utc"],duration_s=.1)
                    if record["status"]!="complete" or "body_checkpoint" not in (record.get("actual_outcome") or {}):
                        raise ValueError("native outcome not complete")
                    after=UnifiedBody.restore(engine.runtime("nasuraya-vps-body")).revision
                    if previous is not None:
                        extra=after-before
                        if extra!=0:
                            raise AssertionError("native replay caused another cycle")
                    # Goal record follows native commit; a crash here reconciles
                    # the same source-linked native receipt without reexecution.
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        db.execute("UPDATE calls SET phase='complete' WHERE call_key=?",(key,))
                        result=make_output(engine,UnifiedBody,db,record,upper,extra,goal_id=call["goal_id"],max_cycles=call["max_cycles"])
                        db.execute("UPDATE calls SET output=? WHERE call_key=?",(canonical(result),key))
                        db.execute("INSERT OR REPLACE INTO meta VALUES('observed',?)",(result["checkpoint_sha256"],))
                        db.execute("COMMIT")
                    except BaseException:
                        db.execute("ROLLBACK");raise
                else:
                    result=make_output(engine,UnifiedBody,db,goal_id=call["goal_id"],max_cycles=call["max_cycles"])
                    if call["name"]=="observe_body":
                        db.execute("INSERT OR REPLACE INTO meta VALUES('observed',?)",(result["checkpoint_sha256"],))
                    if old is None:
                        db.execute("INSERT INTO calls VALUES(?,?,?,'complete',NULL,NULL,?)",
                                   (key,fingerprint,call["name"],canonical(result)))
                return result
            finally:
                db.close()


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",required=True,type=Path)
    args=parser.parse_args()
    try:
        raw=sys.stdin.read(8193)
        if len(raw)>8192:raise ValueError("bounded tool request")
        print(canonical(operate(json.loads(raw),args.root)))
    except Exception:
        raise SystemExit(1)

