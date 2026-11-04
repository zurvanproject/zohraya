"""Read-only, finite self-error audit and falsification probe for synthetic NVLE.

Source of evidence: existing NVLE learning_episodes receipts, NOT ChatGPT memory,
a native Tadash BodyLoop, physical signals, or subjective experience.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .engine import (
    ACTIONS, HOLDOUT, LESSONS, _hash, _policy, _validated_rows, connect, train,
)

SCHEMA = "nasuraya-self-falsification/0.1"
MAX_RECEIPTS = 4096
PROBE_ROUNDS = 3


def _chronological_trace(conn: sqlite3.Connection) -> list[dict]:
    """Validate every receipt and replay each pre-action decision without look-ahead.

    SQLite rowid is a best-effort insertion order, NOT authenticated history.
    Missing/deleted events or a VACUUM may make historical attribution unreliable.
    """
    count = conn.execute("SELECT COUNT(*) FROM learning_episodes").fetchone()[0]
    if count > MAX_RECEIPTS:
        raise ValueError("receipt bound exceeded; refusing unbounded replay")
    validated = {row["event_id"]: row for row in _validated_rows(conn)}
    event_ids = [row["event_id"] for row in conn.execute(
        "SELECT event_id FROM learning_episodes ORDER BY rowid ASC"
    )]
    if len(event_ids) != len(validated):
        raise ValueError("receipt chronology inconsistent")
    previous: list[dict] = []
    trace = []
    for event_id in event_ids:
        receipt = validated[event_id]
        prior = _policy(previous, receipt["context"])
        if receipt["action"] != prior["action"]:
            raise ValueError("historical prediction cannot be replayed: refusing attribution")
        scores = prior["scores"]
        mechanism = ("cold_start_or_score_tie" if
                     len(set(scores.values())) == 1 else
                     "highest_smoothed_fixture_reward")
        trace.append({
            "event_id": event_id,
            "context": receipt["context"],
            "predicted": prior["action"],
            "observed_oracle": receipt["oracle_action"],
            "correct": bool(receipt["reward"]),
            "evidence_before": prior["evidence_count"],
            "scores_before": dict(scores),
            "mechanism": mechanism,
            "_prior_receipts": list(previous),
        })
        previous.append(receipt)
    return trace


def _public_error(event: dict) -> dict:
    return {key: event[key] for key in (
        "event_id", "context", "predicted", "observed_oracle",
        "evidence_before", "scores_before", "mechanism"
    )}


def audit(conn: sqlite3.Connection) -> dict:
    """Find the engine's own mismatches. Never modifies the input database."""
    trace = _chronological_trace(conn)
    errors = [_public_error(event) for event in trace if not event["correct"]]
    return {
        "schema": SCHEMA,
        "kind": "synthetic_fixture_receipt_audit",
        "episodes_checked": len(trace),
        "errors_found": len(errors),
        "errors": errors,
        "status": "errors_found" if errors else "no_recorded_errors",
        "provenance_limit": (
            "Pre-action predictions reconstructed from validated SQLite receipts "
            "and rowid order, not independently frozen forecasts. SHA-256 is not "
            "an authenticated log; deletion and adversarial replacement are not excluded."
        ),
        "native_actions": 0,
        "api_calls": 0,
        "subjective_experience_claim": False,
    }


def falsify(conn: sqlite3.Connection) -> dict:
    """Choose the earliest failed prediction, preregister a refutable test, run it.

    Two arms start from the SAME pre-error receipt prefix. Control receives no
    additional outcomes; treatment receives exactly 3 newly SIMULATED examples.
    Both are scored on the same predefined held-out fixture IDs, with no SQL writes.
    """
    report = audit(conn)
    failed = next((t for t in _chronological_trace(conn) if not t["correct"]), None)
    if failed is None:
        return {
            "audit": report, "status": "no_observed_error_to_challenge",
            "claim": "No recorded error is not proof of error-free prediction.",
            "native_actions": 0, "api_calls": 0,
        }

    context = failed["context"]
    target = LESSONS[context]["oracle_action"]
    test_ids = [stimulus for cat, stimulus in HOLDOUT if cat == context]
    if not test_ids:
        raise ValueError("no preregistered held-out fixture IDs")
    prefix = list(failed["_prior_receipts"])
    plan = {
        "schema": SCHEMA,
        "source_event_id": failed["event_id"],
        "context": context,
        "source_prediction": failed["predicted"],
        "source_observed_oracle": failed["observed_oracle"],
        "hypothesis": (
            "Three on-context simulated feedback episodes correct this error "
            "on fixed-oracle held-out IDs, while the no-feedback control does not."
        ),
        "control": "frozen pre-error policy; zero new episodes",
        "treatment": "exactly three sequential deterministic oracle-feedback episodes",
        "held_out_stimulus_ids": test_ids,
        "success_rule": "treatment correct on all held-out IDs and control wrong on all",
        "falsification_rule": "treatment still wrong on any held-out ID",
        "epistemic_limit": "same predefined categories and oracle; no open-world generalization",
    }
    plan_sha256 = _hash(plan)  # checksum for repeatability, not an authenticated seal

    control = _policy(prefix, context)
    treatment_receipts = list(prefix)
    training = []
    for step in range(1, PROBE_ROUNDS + 1):
        before = _policy(treatment_receipts, context)
        correct = int(before["action"] == target)
        simulated = {
            "event_id": f"synthetic-probe-{step}",
            "context": context,
            "action": before["action"],
            "oracle_action": target,
            "reward": correct,
        }
        training.append(simulated)
        treatment_receipts.append(simulated)
    after = _policy(treatment_receipts, context)

    control_correct = [control["action"] == target for _ in test_ids]
    treatment_correct = [after["action"] == target for _ in test_ids]
    if all(treatment_correct) and not any(control_correct):
        verdict = "supported_in_predefined_synthetic_fixture"
    elif not all(treatment_correct):
        verdict = "falsified_in_predefined_synthetic_fixture"
    else:
        verdict = "inconclusive_no_control_separation"
    return {
        "audit": report,
        "status": "finite_probe_completed",
        "diagnosed_error": _public_error(failed),
        "mechanical_explanation": (
            "Policy selects the highest smoothed synthetic reward; equal scores "
            "use ACTIONS tuple order. This explains the code path, not an "
            "underlying psychological or physical cause."
        ),
        "plan_frozen_before_probe": plan,
        "plan_sha256": plan_sha256,
        "control": {
            "predicted": control["action"],
            "correct_on_holdout": sum(control_correct),
            "total": len(test_ids),
        },
        "feedback_arm": {
            "sequential_new_synthetic_receipts": training,
            "predicted_after": after["action"],
            "correct_on_holdout": sum(treatment_correct),
            "total": len(test_ids),
        },
        "verdict": verdict,
        "limit": (
            "Retrospective source discovery and counterfactual synthetic replay; "
            "not independent causal discovery, new native data, awareness, or "
            "an autonomously chosen experiment. Review before any integration."
        ),
        "input_database_modified": False,
        "native_actions": 0,
        "api_calls": 0,
        "auto_promotion": False,
    }


def demo() -> dict:
    """Fresh memory-only fixture so the demonstration cannot touch saved state."""
    conn = connect(":memory:")
    try:
        train(conn, "self-error-demo-uncertainty", "uncertainty")
        train(conn, "self-error-demo-overload", "overload")
        return falsify(conn)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic self-error falsification, read-only")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("audit", "falsify", "demo"):
        p = sub.add_parser(command)
        if command != "demo":
            p.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "demo":
        result = demo()
    else:
        if not args.db.is_file():
            parser.error("database must exist; no database will be created")
        # Open the existing database READ ONLY, including through URI escaping.
        conn = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            result = audit(conn) if args.command == "audit" else falsify(conn)
        finally:
            conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
