#!/usr/bin/env python3
"""Bounded offline research drafts. No network/API, remote commands or Awake writes.

Output is always UNVERIFIED_DRAFT, never evidence of a completed experiment.
At most one locally generated note every six days, 26 finite curated prompts.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

HOME = Path("/var/lib/nasuraya/local-research")
SEEDS = Path("/usr/local/lib/nasuraya/local_research_seeds.json")
BIN = Path("/opt/nasuraya-local-llm/llama.cpp/build/bin/llama-cli")
MODEL = Path("/var/lib/nasuraya/models/Qwen3-1.7B-Q8_0.gguf")
MODEL_SHA = "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"
ZERO = "0"*64
PROMPT_PREFIX = (
    "Prepare a concise research draft ONLY. No tool use, network, or actions. "
    "Do NOT claim any experiment was run or that new evidence exists. "
    "Give: 1) tentative hypothesis, 2) falsifiable test, 3) possible failure, "
    "4) what evidence would change the conclusion. Label every claim unverified.\n"
    "Research question: "
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing symlinked research database")
    db = sqlite3.connect(path, timeout=20, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL,
            question TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            claim_id TEXT, claimed_utc TEXT);
        CREATE TABLE IF NOT EXISTS notes(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            at_utc TEXT NOT NULL,
            seed_sha TEXT NOT NULL,
            model_sha TEXT NOT NULL,
            prompt_sha TEXT NOT NULL,
            output TEXT NOT NULL,
            output_sha TEXT NOT NULL,
            previous TEXT NOT NULL,
            digest TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT 'UNVERIFIED_DRAFT');
    """)
    return db


def seed(db, path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema") != "nasuraya-offline-questions/1":
        raise ValueError("Unrecognized curated question set")
    tasks = raw.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 26:
        raise ValueError("Expected exactly 26 finite weekly questions")
    ids = set()
    for i, obj in enumerate(tasks):
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not isinstance(obj.get("question"), str):
            raise ValueError("Malformed question")
        if obj["id"] in ids or len(obj["question"]) > 400 or len(obj["question"]) < 20:
            raise ValueError("Duplicate or invalid question")
        ids.add(obj["id"])
    fingerprint = digest(canonical(raw))
    db.execute("BEGIN IMMEDIATE")
    try:
        old = db.execute("SELECT value FROM metadata WHERE key='seed_sha'").fetchone()
        if old and old[0] != fingerprint:
            raise ValueError("Seed revision changed; human review required")
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('seed_sha',?)", (fingerprint,))
        for pos, item in enumerate(tasks):
            db.execute("INSERT OR IGNORE INTO tasks(id,ordinal,question) VALUES (?,?,?)",
                       (item["id"], pos, item["question"]))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return fingerprint


def local_infer(question):
    if not MODEL.is_file() or MODEL.is_symlink() or not BIN.is_file() or BIN.is_symlink():
        raise FileNotFoundError("Local GGUF model or llama-cli not installed")
    if file_sha(MODEL) != MODEL_SHA:
        raise ValueError("Qwen model SHA mismatch")
    prompt = PROMPT_PREFIX + question
    result = subprocess.run([
        str(BIN), "--model", str(MODEL),
        "--threads", "4", "--ctx-size", "2048",
        "--single-turn", "--no-display-prompt", "--n-predict", "320",
        "--prompt", "/no_think " + prompt
    ], capture_output=True, text=True, timeout=360, check=False, env={
        "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(HOME), "LC_ALL": "C.UTF-8"
    })
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Local inference failed")
    return result.stdout.strip()[:12000], MODEL_SHA


def run(db, source, now=None, infer=None):
    now = now or utcnow()
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC required")
    version = seed(db, source)
    at = now.isoformat(timespec="seconds")
    db.execute("BEGIN IMMEDIATE")
    try:
        last = db.execute("SELECT at_utc FROM notes ORDER BY seq DESC LIMIT 1").fetchone()
        if last and now - dt.datetime.fromisoformat(last[0]) < dt.timedelta(days=6):
            db.commit()
            return {"status": "not_due", "provenance": "no_new_evidence"}
        pending = db.execute(
            "SELECT id,question,attempts FROM tasks WHERE status='pending' ORDER BY ordinal LIMIT 1"
        ).fetchone()
        if not pending:
            # Crash recovery, without recreating notes or duplicating completed work.
            max_age = (now - dt.timedelta(hours=6)).isoformat(timespec="seconds")
            pending = db.execute(
                "SELECT id,question,attempts FROM tasks "
                "WHERE status='running' AND claimed_utc<? ORDER BY ordinal LIMIT 1",
                (max_age,)
            ).fetchone()
        if not pending:
            db.commit()
            return {"status": "queue_idle_or_in_progress"}
        task_id, question, attempts = pending
        if attempts >= 3:
            db.execute("UPDATE tasks SET status='blocked' WHERE id=?", (task_id,))
            db.commit()
            return {"status": "task_blocked_after_three_attempts", "task_id": task_id}
        claim = uuid.uuid4().hex
        db.execute("UPDATE tasks SET status='running',attempts=attempts+1,claim_id=?,claimed_utc=? "
                   "WHERE id=?", (claim, at, task_id))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    try:
        output, model_sha = (infer or local_infer)(question)
        if not isinstance(output, str) or not output.strip() or len(output) > 12000:
            raise ValueError("Invalid model draft")
        if not isinstance(model_sha, str) or len(model_sha) != 64:
            raise ValueError("Model fingerprint missing")
        prompt_sha = digest((PROMPT_PREFIX + question).encode("utf-8"))
        output_sha = digest(output.encode("utf-8"))
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT claim_id,status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if current != (claim, "running"):
            raise RuntimeError("Another research runner owns task")
        previous_row = db.execute("SELECT digest FROM notes ORDER BY seq DESC LIMIT 1").fetchone()
        previous = previous_row[0] if previous_row else ZERO
        values = [task_id, at, version, model_sha, prompt_sha, output_sha, previous, "UNVERIFIED_DRAFT"]
        row_hash = digest(canonical(values))
        db.execute("INSERT INTO notes(task_id,at_utc,seed_sha,model_sha,prompt_sha,output,output_sha,previous,digest,label) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (task_id, at, version, model_sha, prompt_sha, output, output_sha, previous,
                    row_hash, "UNVERIFIED_DRAFT"))
        db.execute("UPDATE tasks SET status='completed',claim_id=NULL WHERE id=?", (task_id,))
        db.commit()
        return {"status": "draft_recorded", "task_id": task_id, "digest": row_hash,
                "provenance": "UNVERIFIED_DRAFT", "network": False}
    except BaseException as exc:
        db.rollback()
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT claim_id,status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if current == (claim, "running"):
            db.execute("UPDATE tasks SET status='pending',claim_id=NULL WHERE id=?", (task_id,))
        db.commit()
        return {"status": "failed_no_new_note", "task_id": task_id, "error_class": type(exc).__name__}


def verify(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Corrupt research SQLite")
    prev = ZERO
    for rec in db.execute(
        "SELECT task_id,at_utc,seed_sha,model_sha,prompt_sha,output,output_sha,previous,digest,label "
        "FROM notes ORDER BY seq"
    ):
        task_id, at, seed_sha, model_sha, prompt_sha, output, output_sha, parent, checksum, label = rec
        if label != "UNVERIFIED_DRAFT" or digest(output.encode("utf-8")) != output_sha:
            raise ValueError("Research note tampered")
        values = [task_id, at, seed_sha, model_sha, prompt_sha, output_sha, prev, label]
        if parent != prev or checksum != digest(canonical(values)):
            raise ValueError("Research chain tampered")
        prev = checksum
    return {"status": "ok", "notes": db.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
            "pending": db.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0],
            "last_hash": prev}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "run", "status", "verify"])
    parser.add_argument("--db", type=Path, default=HOME/"research.sqlite3")
    parser.add_argument("--seeds", type=Path, default=SEEDS)
    args = parser.parse_args(argv)
    if os.geteuid() == 0 and args.db == HOME/"research.sqlite3":
        raise SystemExit("Refusing production research execution as root")
    os.umask(0o077)
    with connect(args.db) as db:
        if args.action == "init":
            result = {"status": "initialized", "seed_sha": seed(db, args.seeds)}
        elif args.action == "run":
            result = run(db, args.seeds)
        elif args.action == "verify":
            result = verify(db)
        else:
            result = verify(db)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
