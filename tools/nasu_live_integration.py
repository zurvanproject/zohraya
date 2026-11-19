#!/usr/bin/env python3
"""Persist actual, sanitized local observations and an unexecuted plan hourly.

This is a live observer/planner, not a DIOS live adapter or an action executor.
The existing DIOS CognitiveSession deliberately labels every input as a
synthetic fixture, so it is not used to mislabel actual host observations.
Only the NEW integration journal is writable. Existing ledgers are read by
nasu_unified_status; that reader may use SQLite WAL/SHM coordination files.
Local hash chains detect accidental changes, not an attacker who rewrites the
journal and its hashes. No model, network, service, or shell call is made here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from tools import nasu_unified_status as hub
from tools import nasu_evidence_to_experiment as planner

SCHEMA = "nasuraya-live-integration/1"
DB_SCHEMA = "nasuraya-live-integration-journal/1"
HOME = hub.HOME
STATE = HOME / "agent-integration"
DATABASE = "integration.sqlite3"
ZERO = "0" * 64
MAX_DB_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 200000
MAX_PAYLOAD_BYTES = 4096
COUNTERS = {
    "continuity": ("records",),
    "frontier": ("days",),
    "cognition": ("completed", "incomplete"),
    "feedback": ("completed", "reserved", "comparable", "baseline_correct", "coached_correct"),
    "awake": ("evidence", "questions", "ticks", "ledger"),
}
MODEL_STATES = frozenset(("UNVERIFIED_DRAFT", "source_unavailable",
                          "test_unavailable", "model_unavailable"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _path(value):
    path = Path(os.path.abspath(os.fspath(value)))
    for component in (path, *path.parents):
        _require(not component.is_symlink(), "symlinked_path")
    return path


def _clock(now):
    now = now or dt.datetime.now(dt.timezone.utc)
    _require(isinstance(now, dt.datetime) and now.tzinfo is not None and
             now.utcoffset() == dt.timedelta(0), "UTC_required")
    now = now.replace(microsecond=0)
    return now, now.strftime("%Y-%m-%dT%H:00Z"), now.isoformat(timespec="seconds")


def _checked_stamp(value, hour):
    _require(isinstance(value, str) and len(value) <= 32, "invalid_stamp")
    parsed = dt.datetime.fromisoformat(value)
    _, parsed_hour, canonical_stamp = _clock(parsed)
    _require(canonical_stamp == value and parsed_hour == hour, "noncanonical_stamp")


def _checked_hour(value):
    _require(isinstance(value, str) and len(value) == 17, "invalid_hour")
    parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:00Z")
    _require(parsed.strftime("%Y-%m-%dT%H:00Z") == value, "noncanonical_hour")


def _state_path(state):
    root = _path(state)
    if root.exists():
        _require(root.is_dir(), "state_not_directory")
        allowed = {DATABASE, DATABASE + "-journal", DATABASE + "-wal", DATABASE + "-shm"}
        for item in root.iterdir():
            _require(item.name in allowed and not item.is_symlink() and item.is_file(),
                     "unexpected_state_file")
            if item.name != DATABASE:
                # This journal uses DELETE mode. A nonempty sidecar means an
                # interrupted or unknown writer; never silently recover/reset it.
                _require(item.stat().st_size == 0, "unfinished_journal")
        if any(root.iterdir()) and not (root / DATABASE).is_file():
            raise ValueError("missing_journal_in_partial_state")
    return root


def _separate(home, state):
    _require(state != home and not home.is_relative_to(state), "state_overlaps_sources")
    if state.is_relative_to(home):
        _require(state == home / "agent-integration", "state_overlaps_sources")


def _integer(value):
    _require(type(value) is int and 0 <= value <= 2**63 - 1, "invalid_counter")
    return value


def _project(snapshot, packet):
    """Store only finite labels, validated times and integer counters."""
    states = planner.checked_states(snapshot)
    selected, affected = planner.choose(states)
    _require(packet.get("schema") == planner.SCHEMA and
             packet.get("state") == "PROPOSAL_NOT_EXECUTED" and
             packet.get("selected", {}).get("id") == selected and
             packet["selected"].get("affected_components") == affected,
             "unexpected_plan")
    components = {}
    for name in planner.COMPONENTS:
        source = snapshot["components"][name]
        item = {"status": states[name]}
        counters = source.get("counts", {}) if name == "awake" else source
        _require(isinstance(counters, dict), "invalid_counts")
        for key in COUNTERS[name]:
            if key in counters:
                item[key] = _integer(counters[key])
        if name == "awake" and "paused" in source:
            _require(type(source["paused"]) is bool, "invalid_pause_state")
            item["paused"] = source["paused"]
        if name == "continuity" and source.get("last_hour") is not None:
            _checked_hour(source["last_hour"])
            item["last_hour"] = source["last_hour"]
        if name == "cognition" and "latest" in source:
            latest = source["latest"]
            _require(isinstance(latest, dict), "invalid_model_summary")
            hub._checked_time(latest.get("slot"), "%Y-%m-%dT%H")
            _require(latest.get("topic") in hub.cognition.TOPICS and
                     latest.get("model_status") in MODEL_STATES, "invalid_model_summary")
            item["latest"] = {key: latest[key] for key in ("slot", "topic", "model_status")}
        components[name] = item
    passed = all(states[name] == ("structural_only" if name == "awake" else "verified_history")
                 for name in planner.COMPONENTS)
    return {"schema": SCHEMA, "hub_schema": hub.SCHEMA, "planner_schema": planner.SCHEMA,
            "components": components, "selected_experiment": selected,
            "affected_components": affected, "plan_state": "PROPOSAL_NOT_EXECUTED",
            "local_history_checks_passed": passed,
            "source_root": "single_local_status_reader",
            "services_verified": False, "independent_authentication": False,
            "dios": "NOT_CONNECTED_SYNTHETIC_ADAPTER",
            "model_calls": 0, "external_actions_taken": 0}


def _validate_payload(value):
    """Re-project a stored payload; unknown fields never become public output."""
    _require(isinstance(value, dict), "invalid_payload")
    components = value.get("components")
    _require(isinstance(components, dict), "invalid_components")
    source = {}
    for name in planner.COMPONENTS:
        item = components.get(name)
        _require(isinstance(item, dict), "invalid_component")
        restored = dict(item)
        if name == "awake":
            restored["counts"] = {key: item[key] for key in COUNTERS[name] if key in item}
        source[name] = restored
    snapshot = {"schema": hub.SCHEMA, "execution": "OFFLINE_READ_ONLY", "components": source,
                "generated_at_utc": "2000-01-01T00:00:00+00:00"}
    expected = _project(snapshot, planner.plan(snapshot))
    _require(value == expected, "unexpected_payload_fields_or_decision")
    return value


def _digest(hour, stamp, payload, previous):
    raw = canonical({"hour": hour, "observed_at_utc": stamp, "payload": payload,
                     "previous_sha": previous})
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _schema(db):
    objects = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    _require(set(objects) == {("table", "metadata"), ("table", "cycles")}, "unknown_database_schema")
    _require(db.execute("SELECT key,value FROM metadata").fetchall() == [("schema", DB_SCHEMA)],
             "unknown_journal_version")
    columns = [row[1] for row in db.execute("PRAGMA table_info(cycles)")]
    _require(columns == ["hour", "observed_at_utc", "payload", "previous_sha", "digest"],
             "unknown_journal_columns")
    _require(db.execute("PRAGMA journal_mode").fetchone()[0] == "delete", "unexpected_journal_mode")


def _verify(db):
    _schema(db)
    _require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "journal_integrity_failed")
    previous = ZERO
    latest = None
    records = 0
    for hour, stamp, raw, parent, checksum in db.execute(
            "SELECT hour,observed_at_utc,payload,previous_sha,digest FROM cycles ORDER BY hour"):
        records += 1
        _require(records <= MAX_RECORDS and isinstance(raw, str) and
                 len(raw.encode("utf-8")) <= MAX_PAYLOAD_BYTES, "journal_limit_exceeded")
        _checked_hour(hour)
        _checked_stamp(stamp, hour)
        payload = _validate_payload(json.loads(raw))
        _require(raw == canonical(payload) and parent == previous and
                 checksum == _digest(hour, stamp, payload, previous), "journal_chain_mismatch")
        latest = {"hour": hour, "payload": payload}
        previous = checksum
    return records, latest, previous


def _summary(records, latest, outcome="ok"):
    public = None
    if latest is not None:
        payload = latest["payload"]
        public = {"hour": latest["hour"],
                  "states": {key: value["status"] for key, value in payload["components"].items()},
                  "experiment": payload["selected_experiment"],
                  "local_checks_passed": payload["local_history_checks_passed"]}
    return {"schema": SCHEMA, "status": outcome, "records": records, "latest": public,
            "scope": "OBSERVE_PLAN_PERSIST", "services_verified": False,
            "dios": "NOT_CONNECTED_SYNTHETIC_ADAPTER", "model_calls": 0,
            "external_actions_taken": 0}


def _open(path, *, write=False):
    _require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1 and
             path.stat().st_size <= MAX_DB_BYTES, "unsafe_journal")
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
                         uri=True, timeout=5, isolation_level=None)
    db.execute("PRAGMA trusted_schema=OFF")
    if not write:
        db.execute("PRAGMA query_only=ON")
    deadline = time.monotonic() + 15
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    return db


def _initialize(root):
    if not root.exists():
        _require(root.parent.is_dir(), "state_parent_missing")
        root.mkdir(mode=0o700)
    _require(not any(root.iterdir()), "partial_state_cannot_initialize")
    path = root / DATABASE
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("INSERT INTO metadata VALUES('schema',?)", (DB_SCHEMA,))
        db.execute("CREATE TABLE cycles(hour TEXT PRIMARY KEY,observed_at_utc TEXT NOT NULL,"
                   "payload TEXT NOT NULL,previous_sha TEXT NOT NULL,digest TEXT NOT NULL)")
        db.commit()
    except BaseException:
        db.rollback()
        # Retain any incomplete file for inspection. Never unlink/reset state.
        raise
    finally:
        db.close()
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def run(home=HOME, state=STATE, now=None):
    """Record at most one actual observation/plan for the current UTC hour."""
    _require(os.geteuid() != 0, "refusing_root_execution")
    now, hour, stamp = _clock(now)
    home, root = _path(home), _state_path(state)
    _separate(home, root)
    _require(home.is_dir(), "source_home_missing")
    if not (root / DATABASE).exists():
        _initialize(root)
    db = _open(root / DATABASE, write=True)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        records, latest, previous = _verify(db)
        if latest is not None:
            _require(hour >= latest["hour"], "clock_rollback")
            if hour == latest["hour"]:
                db.rollback()
                return _summary(records, latest, "already_recorded")
        _require(records < MAX_RECORDS, "journal_limit_exceeded")
        snapshot = hub.collect(home=home, now=now)
        payload = _project(snapshot, planner.plan(snapshot))
        raw = canonical(payload)
        _require(len(raw.encode("ascii")) <= MAX_PAYLOAD_BYTES, "payload_too_large")
        db.execute("INSERT INTO cycles VALUES(?,?,?,?,?)",
                   (hour, stamp, raw, previous, _digest(hour, stamp, payload, previous)))
        db.commit()
        return _summary(records + 1, {"hour": hour, "payload": payload}, "recorded")
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def status(state=STATE):
    """Read and verify history without initializing, resetting or running it."""
    try:
        root = _state_path(state)
        path = root / DATABASE
        if not path.exists():
            return _summary(0, None, "missing")
        db = _open(path)
        try:
            db.execute("BEGIN")
            records, latest, _ = _verify(db)
            return _summary(records, latest, "ok" if records else "empty")
        finally:
            db.close()
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as exc:
        return {"schema": SCHEMA, "status": "invalid", "error_class": type(exc).__name__}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "status"))
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        result = run() if args.action == "run" else status()
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as exc:
        result = {"schema": SCHEMA, "status": "failed", "error_class": type(exc).__name__}
    print(canonical(result))
    return 1 if result["status"] in ("invalid", "failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
