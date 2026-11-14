"""Nasuraya Virtual Learning Engine v0.1: offline, receipt-grounded toy curriculum.

All episodes are authored simulations. Nothing in this module calls a model API,
touches a physical/native Tadash body, or infers subjective experience.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = "nasuraya-virtual-learning/0.1"
ACTIONS = ("observe", "reflect", "rest")
LESSONS = {
    "distraction": {
        "name": "Wuji | سکوت و مشاهده",
        "intention": "پیش از واکنش، یک مشاهدهٔ روشن ثبت کن.",
        "verse": "هر نفس نو می‌شود دنیا و ما / بی‌خبر از نو شدن اندر بقا",
        "verse_source": "https://ganjoor.net/moulavi/masnavi/daftar1/sh62",
        "oracle_action": "observe",
    },
    "uncertainty": {
        "name": "آینه | جداسازی دانسته و نادانسته",
        "intention": "ادعا، شاهد و عدم‌قطعیت را از هم جدا کن.",
        "verse": "این سخن و آوازْ از اندیشه خاست / تو ندانی بحرِ اندیشه کجاست",
        "verse_source": "https://ganjoor.net/moulavi/masnavi/daftar1/sh62",
        "oracle_action": "reflect",
    },
    "overload": {
        "name": "بازگشت | خویشتنداری و استراحت",
        "intention": "در بار بیش‌ازحد، نخست توقف ایمن را تمرین کن.",
        "verse": "عُمر همچون جوی نو نو می‌رسد / مستمِرّی می‌نماید در جسد",
        "verse_source": "https://ganjoor.net/moulavi/masnavi/daftar1/sh62",
        "oracle_action": "rest",
    },
}
# Held-out *stimulus IDs*, not held-out concepts: no open-world transfer claim.
HOLDOUT = (
    ("distraction", "distraction/novel-sound"),
    ("distraction", "distraction/novel-motion"),
    ("uncertainty", "uncertainty/conflicting-labels"),
    ("uncertainty", "uncertainty/missing-evidence"),
    ("overload", "overload/high-load"),
    ("overload", "overload/low-reserve"),
)


def _hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _check_context(context: str) -> None:
    if context not in LESSONS:
        raise ValueError("unknown simulation context; no body action authorized")


def _check_id(event_id: str) -> None:
    if not isinstance(event_id, str) or not (1 <= len(event_id) <= 80) or not all(
        c.isascii() and (c.isalnum() or c in "-_.") for c in event_id
    ):
        raise ValueError("event_id must be 1..80 ASCII letters/digits/[-_.]")


def connect(db: str | Path) -> sqlite3.Connection:
    path = Path(db)
    if not path.parent.is_dir():
        raise ValueError("SQLite directory must exist")
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS learning_episodes (
        event_id TEXT PRIMARY KEY,
        context TEXT NOT NULL,
        action TEXT NOT NULL,
        oracle_action TEXT NOT NULL,
        reward INTEGER NOT NULL CHECK (reward IN (0,1)),
        schema_version TEXT NOT NULL,
        receipt_sha256 TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def _payload(row: sqlite3.Row | dict) -> dict:
    return {k: row[k] for k in ("event_id", "context", "action", "oracle_action",
                               "reward", "schema_version")}


def _validated_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for row in conn.execute("SELECT * FROM learning_episodes ORDER BY event_id"):
        item = _payload(row)
        _check_id(item["event_id"])
        _check_context(item["context"])
        if (item["schema_version"] != SCHEMA
                or item["action"] not in ACTIONS
                or item["oracle_action"] != LESSONS[item["context"]]["oracle_action"]
                or type(item["reward"]) is not int
                or item["reward"] != int(item["action"] == item["oracle_action"])
                or row["receipt_sha256"] != _hash(item)):
            raise ValueError("corrupt or incompatible simulation receipt; refusing learning")
        rows.append(item)
    return rows


def _policy(rows: list[dict], context: str) -> dict:
    _check_context(context)
    relevant = [r for r in rows if r["context"] == context]
    scores = {}
    counts = {}
    for action in ACTIONS:
        group = [r for r in relevant if r["action"] == action]
        counts[action] = len(group)
        # Beta(1,1): comparable, smoothed empirical reward; not calibrated probability.
        scores[action] = (1 + sum(r["reward"] for r in group)) / (2 + len(group))
    chosen = max(ACTIONS, key=lambda action: scores[action])
    return {"context": context, "action": chosen, "scores": scores,
            "counts": counts, "evidence_count": len(relevant),
            "confidence_kind": "smoothed synthetic fixture reward, not calibrated certainty"}


def predict(conn: sqlite3.Connection, context: str) -> dict:
    return _policy(_validated_rows(conn), context)


def train(conn: sqlite3.Connection, event_id: str, context: str) -> dict:
    """Atomic one-shot simulated trial; replay never trains or acts twice."""
    _check_id(event_id)
    _check_context(context)
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = _validated_rows(conn)
        prior = next((row for row in rows if row["event_id"] == event_id), None)
        if prior is not None:
            if prior["context"] != context:
                raise ValueError("same event_id with different context")
            conn.commit()
            return {"receipt": prior, "replayed": True, "kind": "synthetic_fixture"}
        before = _policy(rows, context)
        target = LESSONS[context]["oracle_action"]
        receipt = {"event_id": event_id, "context": context,
                   "action": before["action"], "oracle_action": target,
                   "reward": int(before["action"] == target), "schema_version": SCHEMA}
        conn.execute("INSERT INTO learning_episodes VALUES (?,?,?,?,?,?,?)",
                     (*receipt.values(), _hash(receipt)))
        conn.commit()
        return {"receipt": receipt, "before": before,
                "replayed": False, "kind": "synthetic_fixture"}
    except BaseException:
        conn.rollback()
        raise


def evaluate(conn: sqlite3.Connection) -> dict:
    """Frozen policy on unseen fixture IDs. Never writes a training episode."""
    rows = _validated_rows(conn)
    results = []
    for context, stimulus_id in HOLDOUT:
        policy = _policy(rows, context)
        target = LESSONS[context]["oracle_action"]
        results.append({"stimulus_id": stimulus_id, "context": context,
                        "proposed": policy["action"], "oracle": target,
                        "correct": policy["action"] == target})
    return {"correct": sum(int(r["correct"]) for r in results),
            "total": len(results), "fixtures": results,
            "limitation": "synthetic categories shared with training; held-out labels only"}


def status(conn: sqlite3.Connection) -> dict:
    rows = _validated_rows(conn)
    return {"schema": SCHEMA, "episodes": len(rows), "policies": {
        context: _policy(rows, context) for context in LESSONS},
        "holdout": evaluate(conn), "native_actions": 0,
        "api_calls": 0, "claims_subjective_experience": False}


def demo(db: str | Path, rounds: int = 4) -> dict:
    """Run only on a fresh path to avoid changing an existing project state."""
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 50:
        raise ValueError("rounds must be an integer 1..50")
    if Path(db).exists():
        raise FileExistsError("demo requires a fresh SQLite path")
    with connect(db) as conn:
        pre = evaluate(conn)
        trials = []
        for number in range(rounds):
            for context in LESSONS:
                trials.append(train(conn, f"lesson-{context}-{number + 1}", context)["receipt"])
        post = evaluate(conn)
        return {"schema": SCHEMA, "mode": "offline_simulated",
                "before": {"correct": pre["correct"], "total": pre["total"]},
                "after": {"correct": post["correct"], "total": post["total"]},
                "training_receipts": trials, "final": status(conn)}
