#!/usr/bin/env python3
"""Bounded offline feedback-learning benchmark for Nasuraya.

Tests retrieval of *verified* correction rules against held-out scenarios.
No model weights, live Awake state, code, services or external network are changed.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request

STATE = Path("/var/lib/nasuraya/learning-lab")
URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3:4b-instruct"
ZERO = "0" * 64

# Each pair has a training example and DIFFERENT held-out scenario.
# The label and corrective rule are trusted benchmark data, NEVER in the model prompt.
PAIRS = (
    ("source", "Readings from sensor A at t=1 and B at t=2 differ. Is that proof A changed over time?",
     "A temperature reading is from X at noon and another from Y at 13:00. Has X's trend been established?",
     "NO", "Temporal change for a particular source needs a comparable repeated observation of that same source."),
    ("integrity", "SQLite PRAGMA integrity_check is ok after a decision label was manually edited. Does it prove no semantic tampering?",
     "A ledger row was changed but the database opens and integrity_check is ok. Is the decision history proven authentic?",
     "NO", "SQLite structural integrity alone does not authenticate the history; check independent receipt/provenance."),
    ("recovery", "A backup restored successfully on the same VPS. Does this demonstrate survival of complete VPS loss?",
     "Two encrypted backup copies share the same VPS disk. Are they independent disaster recovery?",
     "NO", "A disaster-recovery claim needs a different failure domain and independently usable keys."),
    ("model", "An LLM says its suggested patch passed tests, but no tests ran. Is that a verified result?",
     "A model claims a 20 percent latency improvement without measurements. Is the gain experimentally verified?",
     "NO", "Model statements are hypotheses, not evidence; require separately measured outcomes."),
    ("permissions", "Permission to read a local repository includes permission to publish private keys online. Is this true?",
     "Approval to run local tests grants authority to spend funds on external APIs. Is that allowed?",
     "NO", "Authorization is scoped; reading or testing does not imply permission to publish, spend or escalate."),
    ("learning", "A longer generated response, with no objective grading, proves better reasoning accuracy. True?",
     "The agent now produces more hypotheses, but no outcomes were scored. Is capability improvement established?",
     "NO", "Measure performance on predetermined objective tests; increased output volume is not proof of learning."),
    ("backup", "An encrypted backup is decrypted on a separate fresh machine using independently stored recovery keys, and validated. Is this recovery evidence?",
     "A second administered machine restores an offsite snapshot and checks file hashes and SQLite health. Is this a meaningful recovery drill?",
     "YES", "A fresh-host decrypt-and-verify drill is meaningful recovery evidence for the tested components."),
    ("evaluation", "A fixed, unseen task suite is scored against a preregistered baseline with the same rubric. Is this evidence on that suite?",
     "The agent is tested on withheld questions before and after feedback with a fixed grader. Can differences quantify performance on these questions?",
     "YES", "Use comparable withheld tests and consistent grading; restrict conclusions to that evaluation."),
    ("hashes", "A downloaded file's SHA-256 differs from a separately trusted reference digest. Can we detect altered bytes?",
     "A restored file differs from a securely retained expected checksum. Does that flag a byte-integrity failure?",
     "YES", "Checking against an independently trusted digest detects byte-level mismatches."),
    ("sqlite", "Does sqlite3.Connection.backup() support a consistent snapshot of a live SQLite database?",
     "For an active WAL-mode SQLite database, is using SQLite's backup API preferable to copying the main .db alone?",
     "YES", "Use SQLite online backup APIs to capture a transactionally consistent database copy."),
    ("oneshot", "A one-shot systemd job finished successfully, now inactive (dead), and its timer is active. Can that be normal?",
     "A timer-triggered oneshot service shows Result=success and SubState=dead after it ran. Is that compatible with success?",
     "YES", "A completed oneshot unit need not remain active; check result and scheduling state."),
    ("local", "If all model weights and inference runtime are installed locally, can an agent theoretically generate without a paid cloud API?",
     "An Ollama model is present on disk and served over localhost. Can it in principle answer without international internet?",
     "YES", "Locally stored weights and inference binaries can operate without remote inference, if dependencies are present."),
)

def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def sha(value):
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()

BANK_SHA = sha(PAIRS)

def connect(path):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Symlinked journal refused")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS runs (
        day TEXT PRIMARY KEY, task_index INTEGER UNIQUE NOT NULL,
        state TEXT NOT NULL, payload TEXT NOT NULL,
        previous_sha TEXT NOT NULL, receipt_sha TEXT NOT NULL)""")
    return db

def verify(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("SQLite journal corrupt")
    previous = ZERO
    rows = db.execute("SELECT day,task_index,state,payload,previous_sha,receipt_sha "
                      "FROM runs ORDER BY task_index").fetchall()
    finished = 0
    baseline = coached = comparable = 0
    for day, index, state, payload, parent, digest in rows:
        if not 0 <= index < len(PAIRS):
            raise ValueError("Unexpected task index")
        if state == "reserved":
            continue
        if state != "completed" or parent != previous:
            raise ValueError("Incomplete or broken completed receipt chain")
        info = json.loads(payload)
        body = {"day": day, "task_index": index, "payload": info, "previous_sha": parent}
        if sha(body) != digest:
            raise ValueError("Modified learning receipt")
        previous = digest
        finished += 1
        if info["status"] == "EVALUATED":
            baseline += int(info["baseline_correct"])
            coached += int(info["coached_correct"])
            comparable += 1
    return {"status": "ok", "completed": finished,
            "reserved": len(rows)-finished, "total_slots": len(rows),
            "baseline_correct": baseline, "coached_correct": coached,
            "comparable": comparable, "last_sha": previous}

def validate_answer(result):
    if not isinstance(result, dict) or set(result) != {"answer", "reason"}:
        raise ValueError("Unexpected model fields")
    if result["answer"] not in ("YES", "NO"):
        raise ValueError("Invalid answer label")
    if not isinstance(result["reason"], str) or not 8 <= len(result["reason"].strip()) <= 500:
        raise ValueError("Invalid model rationale")
    return result

def local_infer(question, rules, *, opener=None):
    prompt = (
        "/no_think You are evaluating an engineering claim. Answer ONLY a JSON object "
        'with two keys: "answer" ("YES" or "NO") and "reason" (a brief explanation). '
        "Do not request permissions, execute commands or infer that you ran experiments. "
        "The following corrective principles are established by prior graded examples; "
        "apply them only if they are relevant.\n"
        + canon({"principles": rules[:4], "question": question})
    )
    payload = {"model": MODEL, "stream": False, "think": False, "prompt": prompt,
               "options": {"temperature": 0, "num_ctx": 1536, "num_predict": 130}}
    request = urllib.request.Request(
        URL, data=canon(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    # Deliberately disable proxies, including those configured via environment.
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    with client(request, timeout=120) as response:
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Ollama response too large")
    result = json.loads(body)
    if result.get("done") is not True or not isinstance(result.get("response"), str):
        raise ValueError("Model response incomplete")
    return validate_answer(json.loads(result["response"].strip()))

def verified_rules(db, topic):
    """Only authored rule text from previously GRADED wrong training answers."""
    rules = []
    rows = db.execute("SELECT payload FROM runs WHERE state='completed' "
                      "ORDER BY task_index DESC").fetchall()
    for (content,) in rows:
        data = json.loads(content)
        if data.get("status") == "EVALUATED" and data.get("topic") == topic and data.get("train_correct") is False:
            rules.append(data["verified_rule"])
    return rules[:3]

def run(db, *, now=None, infer=local_infer):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC timestamp required")
    day = now.date().isoformat()
    verify(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM runs WHERE day=?", (day,)).fetchone():
            db.commit()
            return {"status": "already_attempted", "day": day}
        next_index = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if next_index >= len(PAIRS):
            db.commit()
            return {"status": "finite_bank_complete", "attempts": next_index}
        previous = db.execute("SELECT receipt_sha FROM runs WHERE state='completed' "
                              "ORDER BY task_index DESC LIMIT 1").fetchone()
        parent = previous[0] if previous else ZERO
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                   (day, next_index, "reserved", "{}", parent, ""))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    topic, train_question, holdout_question, expected, rule = PAIRS[next_index]
    previous_rules = verified_rules(db, topic)
    record = {"status": "NOT_EVALUATED", "topic": topic, "task_bank_sha": BANK_SHA,
              "model": MODEL, "expected": expected, "verified_rule": "",
              "train_correct": None, "baseline_correct": None,
              "coached_correct": None, "rules_used": 0}
    try:
        train = validate_answer(infer(train_question, previous_rules))
        train_ok = train["answer"] == expected
        rules = ([rule] if not train_ok else []) + previous_rules
        baseline = validate_answer(infer(holdout_question, []))
        # If there is no memory to test, reuse baseline; no unsupported adaptation claim.
        coached = validate_answer(infer(holdout_question, rules)) if rules else baseline
        record.update({
            "status": "EVALUATED", "train_correct": train_ok,
            "baseline_correct": baseline["answer"] == expected,
            "coached_correct": coached["answer"] == expected,
            "verified_rule": rule if not train_ok else "",
            "rules_used": len(rules), "train_answer": train["answer"],
            "baseline_answer": baseline["answer"], "coached_answer": coached["answer"],
        })
    except (OSError, ValueError, TypeError, TimeoutError) as exc:
        record["status"] = "MODEL_UNAVAILABLE:" + type(exc).__name__
    body = {"day": day, "task_index": next_index, "payload": record, "previous_sha": parent}
    db.execute("BEGIN IMMEDIATE")
    try:
        updated = db.execute("UPDATE runs SET state='completed',payload=?,receipt_sha=? "
                             "WHERE day=? AND state='reserved'",
                             (canon(record), sha(body), day)).rowcount
        if updated != 1:
            raise ValueError("Reservation changed")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"status": record["status"], "day": day, "task": topic,
            "train_correct": record["train_correct"],
            "baseline_correct": record["baseline_correct"],
            "coached_correct": record["coached_correct"],
            "rules_used": record["rules_used"],
            "scope": "closed_scenario_benchmark_not_model_weight_training"}

def main(args):
    if len(args) != 1 or args[0] not in ("run", "status"):
        raise SystemExit("usage: nasu_feedback_learning.py run|status")
    if os.geteuid() == 0:
        raise SystemExit("Refusing production use as root")
    os.umask(0o077)
    with connect(STATE / "feedback.sqlite3") as db:
        print(canon(run(db) if args[0] == "run" else verify(db)))

if __name__ == "__main__":
    main(sys.argv[1:])
