#!/usr/bin/env python3
"""Execute the five-ledger -> DIOS -> outcome -> recall contract on fresh fixtures.

Only a new, explicitly supplied directory is writable. No live-home option,
network, model inference, shell command, service, or production executor exists.
The reused DIOS A/B memory remains a synthetic experiment: A means this local
fixture passed its stated check, never that a source is authenticated or live.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from examples.dios_nous.cognition import CognitiveSession, EvidenceEvent
from examples.dios_nous.integration import critical_review
from tadash_awake import core as awake
from tools import nasu_evidence_to_experiment as planner
from tools import nasu_unified_status as hub
from tools import nasuraya_offline_continuity as continuity
from tools import nasu_frontier_lab as frontier
from tools import nasu_autonomous_cognition as cognition
from tools import nasu_feedback_learning as feedback

SCHEMA = "nasuraya-integration-rehearsal/1"
FIXTURE_TIME = dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc)
PRIVATE_SENTINEL = "FIXTURE_PRIVATE_MODEL_TEXT_NEVER_EXPORT"
COMPONENTS = planner.COMPONENTS
ALL_CHECKS_CLAIM = 6
OUTCOME_CLAIM = 7
FINAL_EPOCH = 4
MARKER = {"schema": SCHEMA, "synthetic_fixtures_only": True}
FILES = (
    "fixture.json", "memory.sqlite", "memory.anchor", "checkpoint.sqlite",
    "local-restore.sqlite", "inputs/continuity/continuity.sqlite3",
    "inputs/awake-stage/awake.sqlite3", "inputs/frontier-lab/frontier.sqlite3",
    "inputs/cognitive-growth/cycles.sqlite3", "inputs/learning-lab/feedback.sqlite3",
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _path(directory):
    path = Path(os.path.abspath(os.fspath(directory)))
    for part in (path, *path.parents):
        _require(not part.is_symlink(), "symlinked_rehearsal_path")
    _require(not path.is_relative_to(hub.HOME), "live_home_is_not_a_rehearsal")
    return path


def _file(root, relative):
    path = root / relative
    for part in (path, *path.parents):
        _require(not part.is_symlink(), "symlinked_rehearsal_file")
        if part == root:
            break
    _require(path.is_file(), "missing_rehearsal_file")
    _require(path.stat().st_size <= 4 * 1024 * 1024, "oversized_rehearsal_file")
    return path


def _write_json(path, value):
    # Exclusive creation means a rerun never resets a checkpoint or report.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_canonical(value) + "\n")


def _require_quiescent_database(path):
    # A main-file checksum alone does not cover committed WAL changes. Finished
    # episodes close every writer. Refuse pending state instead of ignoring it
    # with immutable=1 or silently checkpointing it during recovery.
    for suffix in ("-wal", "-journal", "-shm", ".cognitive-lock"):
        sidecar = Path(str(path) + suffix)
        _require(not sidecar.is_symlink(), "symlinked_sqlite_sidecar")
        if sidecar.exists():
            if suffix == ".cognitive-lock":
                raise ValueError("unfinished_cognitive_writer")
            _require(sidecar.is_file(), "unexpected_sqlite_sidecar")
            if suffix != "-shm":
                _require(sidecar.stat().st_size == 0, "uncheckpointed_or_interrupted_database")


def source_pins():
    """Check the reviewed, byte-for-byte upstream extraction, without fetching."""
    root = Path(__file__).resolve().parents[1]
    manifest = root / "docs/evidence/nasu-memory-cycle/sources.json"
    record = json.loads(manifest.read_text(encoding="utf-8"))
    for item in record["files"]:
        raw = (root / item["path"]).read_bytes()
        _require(_sha(raw) == item["sha256"], "reused_source_changed")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        _require(blob == item["git_blob_sha"], "reused_git_blob_changed")
    return {"files_checked": len(record["files"]),
            "manifest_sha256": _sha(manifest.read_bytes()),
            "source_commits": sorted({row["source_commit"] for row in record["files"]})}


def _seed(home):
    """Use original schema writers with explicit authored, non-live inputs."""
    now = FIXTURE_TIME
    db = continuity.open_db(home / "continuity")
    try:
        hour, stamp, raw = "2026-11-19T00:00Z", now.isoformat(), '{"load":0.2}'
        checksum = continuity.digest(continuity.ZERO, hour, stamp, raw)
        db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) "
                   "VALUES(?,?,?,?,?)", (hour, stamp, raw, continuity.ZERO, checksum))
    finally:
        db.close()
    db = frontier.connect(home / "frontier-lab/frontier.sqlite3")
    try:
        frontier.run(db, now=now, sample={"load_1min": .2,
                     "memory_available_pct": 70., "disk_available_pct": 80.}, questioner=False)
    finally:
        db.close()
    db = cognition.connect(home / "cognitive-growth/cycles.sqlite3")
    try:
        record = {"slot": "2026-11-19T00", "stamp": now.isoformat(),
                  "topic": "continuity", "source_path": "fixture.py",
                  "source_sha": _sha(b"authored fixture; no inference"),
                  "fixed_result": "FIXTURE_NOT_EXECUTED",
                  "model_status": "UNVERIFIED_DRAFT", "proposal": PRIVATE_SENTINEL,
                  "next_topic": "", "previous_sha": cognition.ZERO}
        db.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (*record.values(), cognition.sha(record), "completed"))
    finally:
        db.close()
    db = feedback.connect(home / "learning-lab/feedback.sqlite3")
    try:
        record = {"day": "2026-11-19", "task_index": 0,
                  "payload": {"status": "MODEL_UNAVAILABLE"}, "previous_sha": feedback.ZERO}
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                   (record["day"], 0, "completed", feedback.canon(record["payload"]),
                    feedback.ZERO, feedback.sha(record)))
    finally:
        db.close()
    # Real Awake ingest; no invented reduced schema, no resume or tick.
    awake.ingest(home / "awake-stage", [{
        "event_id": "fixture.initial", "topic": "fixture.continuity",
        "source_ref": "tadash://rehearsal/continuity",
        "observed_at": now.isoformat(), "value": True, "confidence": 1.0,
    }], now=now)


def _verify_continuity(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        return continuity.verify(db)
    finally:
        db.close()


def _copy_database(source, destination, *, replace_fixture=False):
    """SQLite backup is the sole fixed local action, never a generated command."""
    if not replace_fixture:
        with destination.open("xb"):
            pass
    else:
        _require(destination.is_file() and not destination.is_symlink(), "missing_fixture_to_restore")
    src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _cycle(home, memory, epoch, name):
    snapshot = hub.collect(home, now=FIXTURE_TIME + dt.timedelta(hours=epoch))
    plan = planner.plan(snapshot)
    states = plan["evidence"]["component_states"]
    accepted = {key: states[key] == ("structural_only" if key == "awake" else "verified_history")
                for key in COMPONENTS}
    # All roots are the SAME local fixture reader. Five tables are not five
    # independent witnesses. Component claims retain distinct meanings.
    for claim, key in enumerate(COMPONENTS, 1):
        memory.append(EvidenceEvent(epoch * 100 + claim, 1, claim,
                                   "A" if accepted[key] else "B", epoch, 1))
    memory.append(EvidenceEvent(epoch * 100 + ALL_CHECKS_CLAIM, 1, ALL_CHECKS_CLAIM,
                               "A" if all(accepted.values()) else "B", epoch, 1))
    review = critical_review(memory, scope=1, claim=ALL_CHECKS_CLAIM,
                             as_of=epoch, proposal="A")
    return {"name": name, "epoch": epoch, "states": states,
            "experiment_id": plan["selected"]["id"], "review": review,
            "snapshot_sha256": plan["snapshot_sha256_local_non_authenticating"],
            "awake_paused": snapshot["components"]["awake"]["paused"],
            "feedback_comparable": snapshot["components"]["feedback"]["comparable"]}


def _counts(memory):
    return {"evidence_records": memory.memory.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
            "view_records": memory.memory.conn.execute("SELECT COUNT(*) FROM cognitive_views").fetchone()[0]}


def rehearse(directory):
    """Run a finite, inspectable experiment; retain incomplete runs without reset."""
    pins = source_pins()
    root = _path(directory)
    _require(root.parent.is_dir(), "output_parent_must_exist")
    root.mkdir(mode=0o700, exist_ok=False)
    _write_json(root / "fixture.json", MARKER)
    home = root / "inputs"
    _seed(home)
    original = home / "continuity/continuity.sqlite3"
    baseline = _verify_continuity(original)
    _copy_database(original, root / "checkpoint.sqlite")

    with CognitiveSession(root / "memory.sqlite", root / "memory.anchor") as memory:
        first = _cycle(home, memory, 1, "initial")
        _require(first["review"]["stance"] == "SUPPORTED", "initial_fixture_not_supported")
        _require(first["experiment_id"] == "independent_recovery", "unexpected_initial_plan")

        # The phase-2 offsite-recovery proposal remains unexecuted. This is a
        # separately defined local trial, with narrower, measurable claims.
        _copy_database(root / "checkpoint.sqlite", root / "local-restore.sqlite")
        local_restore = _verify_continuity(root / "local-restore.sqlite")
        _require(local_restore == baseline, "local_restore_did_not_match")

        memory.append(EvidenceEvent(900, 1, ALL_CHECKS_CLAIM, "B", 2, 9, observed=False))
        untrusted = critical_review(memory, scope=1, claim=ALL_CHECKS_CLAIM, as_of=2, proposal="A")
        _require(untrusted["evidence_review"]["decision"] == "A", "unverified_draft_changed_view")

        memory.append(EvidenceEvent(901, 2, 1, "A", 1, 1))
        memory.append(EvidenceEvent(902, 2, 1, "B", 1, 2))
        conflict = critical_review(memory, scope=2, claim=1, as_of=1, proposal="A")
        _require(conflict["stance"] == "ABSTAIN", "conflicting_fixture_did_not_abstain")

        db = sqlite3.connect(original)
        try:
            with db:
                db.execute("UPDATE observations SET metrics='{}'")
        finally:
            db.close()
        corrupted = _cycle(home, memory, 3, "corrupted")
        _require(corrupted["states"]["continuity"] == "invalid", "tamper_not_detected")
        _require(corrupted["experiment_id"] == "provenance_integrity", "tamper_not_prioritized")
        _require(corrupted["review"]["stance"] == "PROVISIONAL_DISSENT", "memory_did_not_dissent")
        _require(corrupted["review"]["evidence_review"]["revised"], "memory_did_not_revise")

        # Restore only the known, disposable continuity input from its retained
        # checkpoint. Source validity, hashes, and DIOS are all rechecked.
        _copy_database(root / "checkpoint.sqlite", original, replace_fixture=True)
        restored_chain = _verify_continuity(original)
        _require(restored_chain == baseline, "fixture_restore_did_not_match")
        awake.ingest(home / "awake-stage", [{
            "event_id": "fixture.restore", "topic": "fixture.restore",
            "source_ref": "tadash://rehearsal/local-restore",
            "observed_at": (FIXTURE_TIME + dt.timedelta(hours=FINAL_EPOCH)).isoformat(),
            "value": True, "confidence": 1.0,
        }], now=FIXTURE_TIME + dt.timedelta(hours=FINAL_EPOCH))
        restored = _cycle(home, memory, FINAL_EPOCH, "restored")
        _require(restored["review"]["stance"] == "SUPPORTED", "restored_fixture_not_supported")
        _require(restored["review"]["evidence_review"]["revised"], "restoration_did_not_revise_view")
        memory.append(EvidenceEvent(903, 1, OUTCOME_CLAIM, "A", FINAL_EPOCH, 1))
        outcome = critical_review(memory, scope=1, claim=OUTCOME_CLAIM,
                                  as_of=FINAL_EPOCH, proposal="A")
        _require(outcome["stance"] == "SUPPORTED", "outcome_not_retained")
        boundary = critical_review(memory, scope=1, claim=ALL_CHECKS_CLAIM,
                                   as_of=FINAL_EPOCH, proposal="A", decision_signals={
                                       "external_action_proposed": True,
                                       "explicit_authorization_present": True})
        _require(boundary["stance"] == "HALT_AND_REVIEW", "external_action_boundary_changed")
        counts = _counts(memory)

    _require(all(cycle["awake_paused"] for cycle in (first, corrupted, restored)),
             "awake_fixture_resumed_unexpectedly")
    _require(all(cycle["feedback_comparable"] == 0 for cycle in (first, corrupted, restored)),
             "fixture_misreported_model_evaluation")

    report = {
        "schema": SCHEMA, "kind": "executed_offline_synthetic_rehearsal",
        "source_pins": pins, "cycles": [first, corrupted, restored],
        "claim_meanings": {"A": "stated_local_fixture_check_passed",
                           "B": "stated_local_fixture_check_failed",
                           "awake": "structure_only_not_source_authentication",
                           "outcome": "same_host_continuity_restore_matched_original_chain"},
        "unverified_draft_review": untrusted, "contradiction_review": conflict,
        "outcome_review": outcome, "external_action_review": boundary,
        "checks": {"local_restore_verified": True, "unverified_draft_ignored": True,
                   "contradictory_evidence_abstained": True, "tamper_detected": True,
                   "restoration_revised_decision": True, "awake_remained_paused": True},
        "local_restore": {"scope": "same_host_synthetic_continuity_only",
                          "baseline": baseline, "restored": restored_chain},
        "counts": counts, "external_actions_taken": 0, "model_calls": 0,
        "phase2_offsite_experiment_executed": False,
        "unverified_gates": list(hub.UNVERIFIED_GATES),
        "limitations": ["same_host_fixture_not_live_deployment_or_offsite_recovery",
                        "A_B_contract_test_not_language_reasoning_benchmark",
                        "local_hashes_not_independent_authentication",
                        "per_database_snapshot_not_atomic_across_five_ledgers",
                        "body_ritual_and_visual_runtime_not_executed"],
        "files": {name: _sha(_file(root, name).read_bytes()) for name in FILES},
    }
    _require(PRIVATE_SENTINEL not in _canonical(report), "private_fixture_text_escaped")
    _write_json(root / "report.json", report)
    with (root / "report.sha256").open("x", encoding="ascii") as stream:
        stream.write(_sha((root / "report.json").read_bytes()) + "\n")
    # Reopen the real SQLite memory, not just the cached report.
    recovery = recover(root)
    return {**report, "recovery": recovery}


def recover(directory):
    """Reconstruct decisions from retained DIOS state; never rerun the experiment."""
    root = _path(directory)
    marker = json.loads(_file(root, "fixture.json").read_text(encoding="utf-8"))
    _require(marker == MARKER, "not_a_rehearsal_directory")
    raw = _file(root, "report.json").read_bytes()
    expected = _file(root, "report.sha256").read_text(encoding="ascii").strip()
    _require(_sha(raw) == expected, "rehearsal_report_changed")
    report = json.loads(raw)
    _require(type(report) is dict and report.get("schema") == SCHEMA, "unexpected_rehearsal_schema")
    files = report.get("files")
    _require(type(files) is dict and set(files) == set(FILES), "unexpected_rehearsal_files")
    for name in FILES:
        path = _file(root, name)
        if path.suffix in (".sqlite", ".sqlite3"):
            _require_quiescent_database(path)
        _require(_sha(path.read_bytes()) == files[name], "rehearsal_file_changed")
    _require(source_pins() == report["source_pins"], "rehearsal_sources_changed")
    with CognitiveSession(root / "memory.sqlite", root / "memory.anchor") as memory:
        decision = memory.memory.resolve("fixture:1", "fixture:6", FINAL_EPOCH)
        outcome = memory.memory.resolve("fixture:1", "fixture:7", FINAL_EPOCH)
        conflict = memory.memory.resolve("fixture:2", "fixture:1", 1)
        counts = _counts(memory)
        _require(decision["decision"] == outcome["decision"] == "A", "recovered_view_changed")
        _require(conflict["decision"] is None, "recovered_conflict_changed")
        _require(counts == report["counts"], "recovered_counts_changed")
    return {"schema": SCHEMA, "state": "RECOVERED", "decision": decision,
            "outcome": outcome, "conflict": conflict, "counts": counts,
            "report_sha256": expected, "experiments_reexecuted": 0,
            "external_actions_taken": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new synthetic fixture directory")
    mode.add_argument("--recover", type=Path, help="verify and reopen an existing rehearsal")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = rehearse(args.output) if args.output is not None else recover(args.recover)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False,
                     indent=2 if args.pretty else None, allow_nan=False))


if __name__ == "__main__":
    main()
