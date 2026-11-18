#!/usr/bin/env python3
"""Nasuraya unified OFFLINE read-only status. No commands, LLM, or state writes.

This is an observability adapter, NOT a merger of independent SQLite ledgers,
a security attestation, a deployer, or evidence of autonomous cognition.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3

from tools import nasuraya_offline_continuity as continuity
from tools import nasu_frontier_lab as frontier
from tools import nasu_autonomous_cognition as cognition
from tools import nasu_feedback_learning as feedback

HOME = Path("/var/lib/nasuraya")
SCHEMA = "nasuraya-unified-status/1"
COMPONENTS = (
    ("continuity", "continuity/continuity.sqlite3"),
    ("frontier", "frontier-lab/frontier.sqlite3"),
    ("cognition", "cognitive-growth/cycles.sqlite3"),
    ("feedback", "learning-lab/feedback.sqlite3"),
)
# These are intentionally NOT inferred from a local file or an LLM answer.
# No snapshot can assert remote recovery, model training, live trust, or actuation.
UNVERIFIED_GATES = (
    "independent_offsite_restore_with_separate_keys",
    "full_offline_model_and_runtime_recovery",
    "live_atmosphere_signed_evidence_pipeline",
    "live_dios_body_ritual_visual_integration",
    "physical_morphology_and_motion_validation",
)


def _normal(path):
    """Normalize dot segments without trusting symlinks."""
    return Path(os.path.abspath(os.fspath(path)))


def _guard(home, path):
    home, path = _normal(home), _normal(path)
    if not path.is_relative_to(home):
        raise ValueError("path_outside_home")
    # Unlike resolve(), this refuses *every* symlink, even a broken one.
    current = path
    while True:
        if current.is_symlink():
            raise ValueError("symlinked_source")
        if current == home:
            break
        current = current.parent
    return path


def _read(home, path, inspector):
    """Never open an unknown DB, initialize a schema, or print source rows."""
    try:
        target = _guard(home, path)
        if not target.exists():
            return {"status": "missing"}
        if not target.is_file():
            raise ValueError("not_regular_file")
        # URI read-only mode plus query_only is intentional; do not use
        # existing modules' connect() helpers, which initialize WAL/tables.
        db = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("sqlite_integrity_failed")
            return inspector(db)
        finally:
            db.close()
    except (OSError, sqlite3.Error, ValueError, RuntimeError, KeyError,
            TypeError, IndexError, json.JSONDecodeError) as exc:
        # Safe error classification only. Never expose a DB path, secret,
        # question, observation, model response, or exception message.
        return {"status": "invalid", "error_class": type(exc).__name__}


def _continuity(db):
    r = continuity.verify(db)
    return {"status": "verified_history" if r["records"] else "empty",
            "records": r["records"], "last_hour": r["last_hour"],
            "evidence": "local_sqlite_integrity_and_hash_chain"}


def _frontier(db):
    r = frontier.verify(db)
    return {"status": "verified_history" if r["days"] else "empty",
            "days": r["days"], "evidence": "local_sqlite_integrity_and_hash_chain"}


def _cognition(db):
    r = cognition.verify(db)
    status = ("incomplete" if r["incomplete"] else
              "verified_history" if r["completed"] else "empty")
    last = db.execute("SELECT slot,topic,model_status FROM cycles "
                      "WHERE state='completed' ORDER BY slot DESC LIMIT 1").fetchone()
    result = {"status": status, "completed": r["completed"],
              "incomplete": r["incomplete"],
              "evidence": "local_sqlite_integrity_and_hash_chain"}
    if last:
        result["latest"] = {"slot": last[0], "topic": last[1],
                            "model_status": last[2]}
    return result


def _feedback(db):
    r = feedback.verify(db)
    return {"status": ("incomplete" if r["reserved"] else
                       "verified_history" if r["completed"] else "empty"),
            "completed": r["completed"], "reserved": r["reserved"],
            "comparable": r["comparable"],
            "baseline_correct": r["baseline_correct"],
            "coached_correct": r["coached_correct"],
            "evidence": "finite_synthetic_benchmark_hash_chain_not_weight_training"}


def _awake(db):
    # Original pinned Awake core has no independently authenticated ledger.
    # SQLite integrity + schema + counters is STRUCTURAL evidence only.
    schema = db.execute("SELECT value FROM control WHERE name='schema'").fetchone()
    paused = db.execute("SELECT value FROM control WHERE name='paused'").fetchone()
    if schema != ("tadash-awake/1",) or not paused or paused[0] not in ("0", "1"):
        raise ValueError("awake_schema_or_gate_mismatch")
    counts = {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
              for name in ("evidence", "questions", "ticks", "ledger")}
    return {"status": "structural_only", "counts": counts,
            "paused": paused[0] == "1",
            "evidence": "sqlite_structure_only_no_independent_authentication"}


def _awake_path(home):
    manifest = _guard(home, _normal(home) / "migration/latest-import.json")
    if not manifest.exists() and not manifest.is_symlink():
        return _normal(home) / "awake-stage/awake.sqlite3"
    if not manifest.is_file() or manifest.stat().st_size > 65536:
        raise ValueError("unsafe_migration_manifest")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    working = data.get("working_db")
    if not isinstance(working, str):
        raise ValueError("missing_working_db")
    target = _normal(working)
    allowed = _normal(home) / "migration/working"
    if target.name != "awake.sqlite3" or not target.is_relative_to(allowed):
        raise ValueError("untrusted_working_db")
    return target


def collect(home=HOME, now=None):
    """Return a sanitized snapshot without touching services or private data."""
    home = _normal(home)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC time required")
    inspectors = {"continuity": _continuity, "frontier": _frontier,
                  "cognition": _cognition, "feedback": _feedback}
    out = {}
    for key, rel in COMPONENTS:
        out[key] = _read(home, home / rel, inspectors[key])
    try:
        awake_path = _awake_path(home)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        out["awake"] = {"status": "invalid",
                        "error_class": type(exc).__name__}
    else:
        out["awake"] = _read(home, awake_path, _awake)
    compromised = [k for k, v in out.items() if v["status"] in ("invalid", "incomplete")]
    missing = [k for k, v in out.items() if v["status"] == "missing"]
    if compromised:
        priority = "review_invalid_or_incomplete_local_receipts"
    elif missing:
        priority = "locate_missing_local_component_without_reinitializing"
    else:
        priority = "prove_independent_offsite_restore_and_live_trust"
    return {
        "schema": SCHEMA, "generated_at_utc": now.isoformat(),
        "execution": "OFFLINE_READ_ONLY", "overall": "PARTIAL_NOT_LIVE_INTEGRATED",
        "components": out,
        "unverified_gates": list(UNVERIFIED_GATES),
        "priority": priority,
        "note": "Local hash chains are not independent tamper authentication; "
                "an available SQLite file does not prove its service is running.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=HOME)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = collect(home=args.home)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False,
                     indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
