"""Tadash Awake: bounded offline evidence -> question loop, not continuous ChatGPT thought."""
import hashlib
import json
import math
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "tadash-awake/1"
MIN_INTERVAL = 900
DAILY_LIMIT = 96
EVENT_LIMIT = 2000
TOPIC_LIMIT = 256


def clock(value=None):
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def iso(value):
    return clock(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def encode(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(obj):
    return hashlib.sha256(encode(obj).encode("utf-8")).hexdigest()


def connect(root):
    path = Path(root).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path / "awake.sqlite3"), timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS control(name TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,topic TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS questions(
          topic TEXT PRIMARY KEY,id TEXT NOT NULL,kind TEXT NOT NULL,
          question TEXT NOT NULL,evidence_hash TEXT NOT NULL,revision INTEGER NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ticks(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,status TEXT NOT NULL,topic TEXT);
        CREATE TABLE IF NOT EXISTS ledger(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL);
    """)
    db.execute("INSERT OR IGNORE INTO control VALUES('schema',?)", (SCHEMA,))
    db.execute("INSERT OR IGNORE INTO control VALUES('paused','1')")
    if db.execute("SELECT value FROM control WHERE name='schema'").fetchone()[0] != SCHEMA:
        db.close()
        raise ValueError("schema mismatch; explicit migration needed")
    return db


def checked(item, now):
    required = {"event_id", "topic", "source_ref", "observed_at", "value", "confidence"}
    if not isinstance(item, dict) or set(item) != required:
        raise ValueError("invalid evidence fields")
    e = dict(item)
    if not isinstance(e["event_id"], str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", e["event_id"]):
        raise ValueError("bad event id")
    if not isinstance(e["topic"], str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", e["topic"]):
        raise ValueError("bad topic")
    source = e["source_ref"]
    if not isinstance(source, str) or len(source) > 240 or not (
        source.startswith("https://github.com/zurvanproject/zohraya/")
        or re.fullmatch(r"tadash://[A-Za-z0-9._/-]{1,180}", source)
    ):
        raise ValueError("untrusted source pointer")
    if type(e["confidence"]) not in (int, float) or not math.isfinite(e["confidence"]) or not 0 <= e["confidence"] <= 1:
        raise ValueError("bad confidence")
    if type(e["value"]) not in (str, bool, int, float):
        raise ValueError("evidence values must be scalars")
    if isinstance(e["value"], str) and (not 1 <= len(e["value"]) <= 120 or any(ord(c) < 32 for c in e["value"])):
        raise ValueError("unsafe string evidence")
    if type(e["value"]) is float and not math.isfinite(e["value"]):
        raise ValueError("nonfinite value")
    observed = clock(e["observed_at"])
    if observed > now + timedelta(minutes=5):
        raise ValueError("future evidence")
    e["observed_at"] = iso(observed)
    e["confidence"] = float(e["confidence"])
    return e


def ingest(root, items, now=None):
    at = clock(now)
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("expected 1..50 evidence records")
    records = [checked(item, at) for item in items]
    db = connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        added = duplicate = 0
        for e in records:
            raw = encode(e)
            old = db.execute("SELECT payload FROM evidence WHERE id=?", (e["event_id"],)).fetchone()
            if old:
                if old[0] != raw:
                    raise ValueError("conflicting event id")
                duplicate += 1
            else:
                if count + added >= EVENT_LIMIT:
                    raise ValueError("evidence capacity reached")
                db.execute("INSERT INTO evidence VALUES(?,?,?)", (e["event_id"], e["topic"], raw))
                added += 1
        db.execute("INSERT INTO ledger(at,action,detail) VALUES(?,?,?)",
                   (iso(at), "ingest", encode({"added": added, "duplicate": duplicate})))
        db.execute("COMMIT")
        return {"status": "ingested", "added": added, "duplicate": duplicate}
    except BaseException:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def set_paused(root, paused, now=None):
    db = connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE control SET value=? WHERE name='paused'", ("1" if paused else "0",))
        db.execute("INSERT INTO ledger(at,action,detail) VALUES(?,?,?)",
                   (iso(clock(now)), "pause" if paused else "resume", "{}"))
        db.execute("COMMIT")
        return {"status": "paused" if paused else "resumed"}
    except BaseException:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def propose(topic, events):
    sources = {e["source_ref"] for e in events}
    values = {encode(e["value"]) for e in events}
    if len(sources) > 1 and len(values) > 1:
        kind, rank = "discrepancy", 4
        question = "چرا شواهد دربارهٔ «" + topic + "» متفاوت‌اند؟"
    elif len(sources) < 2:
        kind, rank = "independent_check", 3
        question = "چه شاهد مستقلی نتیجهٔ «" + topic + "» را می‌آزماید؟"
    elif min(e["confidence"] for e in events) < .70:
        kind, rank = "weak_evidence", 2
        question = "چطور اعتبار شواهد «" + topic + "» بیشتر می‌شود؟"
    else:
        kind, rank = "falsification", 1
        question = "چه آزمایشی برداشت فعلی از «" + topic + "» را رد می‌کند؟"
    return {"topic": topic, "kind": kind, "rank": rank, "question": question,
            "hash": fingerprint(sorted(e["event_id"] for e in events)),
            "latest": max(e["observed_at"] for e in events),
            "evidence_count": len(events)}


def tick(root, now=None):
    at = clock(now)
    db = connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT value FROM control WHERE name='paused'").fetchone()[0] == "1":
            db.execute("COMMIT")
            return {"status": "paused", "model_calls": 0}
        last = db.execute("SELECT at FROM ticks ORDER BY seq DESC LIMIT 1").fetchone()
        if last:
            delta = (at - clock(last["at"])).total_seconds()
            if delta < 0:
                raise ValueError("clock rollback")
            if delta < MIN_INTERVAL:
                db.execute("COMMIT")
                return {"status": "deferred_cooldown", "model_calls": 0}
        limit = iso(at - timedelta(days=1))
        if db.execute("SELECT COUNT(*) FROM ticks WHERE at>?", (limit,)).fetchone()[0] >= DAILY_LIMIT:
            db.execute("COMMIT")
            return {"status": "deferred_budget", "model_calls": 0}
        groups = defaultdict(list)
        for row in db.execute("SELECT payload FROM evidence"):
            e = json.loads(row[0])
            groups[e["topic"]].append(e)
        previous = {row["topic"]: row for row in db.execute("SELECT * FROM questions")}
        ready = []
        for topic, events in groups.items():
            p = propose(topic, events)
            if topic not in previous or previous[topic]["evidence_hash"] != p["hash"]:
                ready.append(p)
        selected = sorted(ready, key=lambda p: (-p["rank"], p["latest"], p["topic"]))
        if selected:
            rank = selected[0]["rank"]
            p = max((x for x in selected if x["rank"] == rank), key=lambda x: (x["latest"], x["topic"]))
            topic = p["topic"]
            old = previous.get(topic)
            if old is None and len(previous) >= TOPIC_LIMIT:
                raise ValueError("topic capacity reached")
            qid = fingerprint({"topic": topic})[:20]
            revision = 1 if old is None else old["revision"] + 1
            created = iso(at) if old is None else old["created_at"]
            db.execute("""INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(topic) DO UPDATE SET
                kind=excluded.kind,question=excluded.question,
                evidence_hash=excluded.evidence_hash,revision=excluded.revision,
                updated_at=excluded.updated_at""",
                (topic, qid, p["kind"], p["question"], p["hash"], revision, created, iso(at)))
            outcome = "question_created" if old is None else "question_revised"
            db.execute("INSERT INTO ledger(at,action,detail) VALUES(?,?,?)",
                       (iso(at), outcome, encode({"topic": topic, "kind": p["kind"],
                                                 "revision": revision, "evidence_count": p["evidence_count"],
                                                 "evidence_hash": p["hash"]})))
        else:
            topic = None
            outcome = "idle_no_evidence" if not groups else "idle_no_new_evidence"
        db.execute("INSERT INTO ticks(at,status,topic) VALUES(?,?,?)", (iso(at), outcome, topic))
        db.execute("COMMIT")
        result = {"status": outcome, "at": iso(at), "model_calls": 0}
        if selected:
            result.update({"topic": topic, "question_id": qid, "question": p["question"],
                           "kind": p["kind"], "revision": revision,
                           "evidence_count": p["evidence_count"]})
        return result
    except BaseException:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def status(root):
    db = connect(root)
    try:
        paused = db.execute("SELECT value FROM control WHERE name='paused'").fetchone()[0] == "1"
        counts = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in ("evidence", "questions", "ticks", "ledger")}
        recent = db.execute("""SELECT topic,id,kind,question,revision,updated_at
                               FROM questions ORDER BY updated_at DESC,topic LIMIT 10""").fetchall()
        last = db.execute("SELECT at,status,topic FROM ticks ORDER BY seq DESC LIMIT 1").fetchone()
        return {"schema": SCHEMA, "paused": paused, "counts": counts,
                "last_tick": dict(last) if last else None, "questions": [dict(row) for row in recent],
                "mode": "offline_evidence_only", "model_calls": 0}
    finally:
        db.close()
