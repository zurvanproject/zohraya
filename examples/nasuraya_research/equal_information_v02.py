"""DIOS NOUS v0.2: equal-information falsification of the v0.1 result.

All facts, labels, roots and epochs are AUTHORED synthetic fixtures. This adds
no model capability or ChatGPT memory; it benchmarks a small external ledger.
P2 is a separately written in-memory reducer with identical evidence metadata.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
import tempfile

from examples.nasuraya_research.epistemic_revision_v01 import (
    Evidence, EvidenceLedger, fixture, naive_last_arrival,
)

SCHEMA = "dios-nous-equal-information/0.2"
DEV_SEEDS = range(610000, 610040)
HELDOUT_SEEDS = range(620000, 620160)

# Independent reference policy: direct record reduction without calling
# EvidenceLedger.resolve, SQL, or the implementation's internal helper rules.
# Both policies are intentionally granted the SAME metadata and as-of scope.
def matched_reference(
    events: list[Evidence], scope: str, claim_key: str, as_of: int
) -> dict:
    current_epoch: int | None = None
    roots: dict[str, set[str]] = {}
    for record in events:
        if record.scope != scope or record.claim_key != claim_key:
            continue
        if record.epoch > as_of:
            continue
        if not record.verified_by_caller:
            continue
        if record.source_kind not in ("owner_observation", "independent_execution"):
            continue
        if current_epoch is None or record.epoch > current_epoch:
            current_epoch = record.epoch
            roots = {}
        if record.epoch == current_epoch:
            roots.setdefault(record.source_root, set()).add(record.value)

    if current_epoch is None:
        return {"status": "unknown", "decision": None,
                "distinct_sources": 0, "latest_epoch": None}
    if any(len(v) != 1 for v in roots.values()):
        return {"status": "abstain_provenance_conflict", "decision": None,
                "distinct_sources": len(roots), "latest_epoch": current_epoch}
    distinct_values = set().union(*roots.values())
    if len(distinct_values) != 1:
        return {"status": "abstain_contradiction", "decision": None,
                "distinct_sources": len(roots), "latest_epoch": current_epoch}
    return {"status": "supported", "decision": next(iter(distinct_values)),
            "distinct_sources": len(roots), "latest_epoch": current_epoch}


def pinned_snapshot_digest(connection: sqlite3.Connection) -> str:
    """Deterministic snapshot digest. Independent anchoring must be external.

    It detects altered bytes relative to a clean anchor, not a malicious
    rewrite of BOTH the database and anchor. It is NOT authenticity proof.
    """
    rows = connection.execute(
        "SELECT event_id,scope,claim_key,value,epoch,source_root,"
        "source_kind,verified_by_caller "
        "FROM evidence ORDER BY event_id ASC"
    ).fetchall()
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_equal_information(seeds: range) -> dict:
    scores = {"sqlite_p1": 0, "matched_p2": 0,
              "last_arrival_p3": 0, "always_abstain_p4": 0}
    checks = {"same_decision": 0, "replay_no_added_record": 0,
              "alias_invariant": 0, "reordered_invariant": 0,
              "cold_reopen_invariant": 0, "tampered_copy_detected": 0,
              "p1_false_assertion_on_unknown": 0,
              "p2_false_assertion_on_unknown": 0}
    regimes = {str(i): 0 for i in range(10)}
    counterexamples: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="dios_equalinfo_") as tmp:
        root = Path(tmp)
        for seed in seeds:
            events, answer_key, as_of = fixture(seed)
            regimes[str(seed % 10)] += 1
            alias = replace(events[0], event_id=str(seed) + ":additional_alias")
            augmented = events + [alias]

            p2 = matched_reference(augmented, "main", "target", as_of)
            path = root / (str(seed) + ".sqlite")
            with EvidenceLedger(path) as ledger:
                for event in events:
                    ledger.append(event)
                before_replay = pinned_snapshot_digest(ledger.conn)
                replayed = ledger.append(events[0])
                after_replay = pinned_snapshot_digest(ledger.conn)
                checks["replay_no_added_record"] += int(
                    replayed == "replay" and before_replay == after_replay
                )
                p1_original = ledger.resolve("main", "target", as_of)
                ledger.append(alias)
                p1 = ledger.resolve("main", "target", as_of)
                checks["alias_invariant"] += int(p1 == p1_original)
                anchor = pinned_snapshot_digest(ledger.conn)

            with EvidenceLedger(path) as reopened:
                cold = reopened.resolve("main", "target", as_of)
                checks["cold_reopen_invariant"] += int(
                    cold == p1 and pinned_snapshot_digest(reopened.conn) == anchor
                )

            reordered = list(augmented)
            random.Random(seed ^ 0xA71E).shuffle(reordered)
            reorder_path = root / (str(seed) + "_reorder.sqlite")
            with EvidenceLedger(reorder_path) as shuffled:
                for event in reordered:
                    shuffled.append(event)
                p1_reordered = shuffled.resolve("main", "target", as_of)
            p2_reordered = matched_reference(reordered, "main", "target", as_of)
            checks["reordered_invariant"] += int(
                p1_reordered == p1 and p2_reordered == p2
            )

            # Fault-inject only into a DISPOSABLE COPY; anchor is held outside
            # the corrupted database. Neither original nor Tadash memory touched.
            damaged = root / (str(seed) + "_damaged.sqlite")
            shutil.copyfile(path, damaged)
            with sqlite3.connect(damaged) as connection:
                same_before = pinned_snapshot_digest(connection) == anchor
                connection.execute(
                    "UPDATE evidence "
                    "SET value=CASE value WHEN 'A' THEN 'B' ELSE 'A' END "
                    "WHERE event_id=?", (events[0].event_id,)
                )
                connection.commit()
                changed = pinned_snapshot_digest(connection) != anchor
            checks["tampered_copy_detected"] += int(same_before and changed)

            p1_answer, p2_answer = p1["decision"], p2["decision"]
            scores["sqlite_p1"] += int(p1_answer == answer_key)
            scores["matched_p2"] += int(p2_answer == answer_key)
            scores["last_arrival_p3"] += int(
                naive_last_arrival(events) == answer_key
            )
            scores["always_abstain_p4"] += int(answer_key is None)
            checks["same_decision"] += int(p1 == p2)
            if answer_key is None:
                checks["p1_false_assertion_on_unknown"] += int(
                    p1_answer is not None
                )
                checks["p2_false_assertion_on_unknown"] += int(
                    p2_answer is not None
                )
            if p1 != p2:
                counterexamples.append({
                    "seed": seed, "regime": seed % 10,
                    "p1_status": p1["status"], "p2_status": p2["status"],
                })

    total = len(seeds)
    return {
        "schema": SCHEMA,
        "dataset": "synthetic_authored_fixture",
        "cases": total,
        "regime_counts": regimes,
        "scores": scores,
        "exact_accuracies": {
            name: round(value / total, 6) if total else 0.0
            for name, value in scores.items()
        },
        "checks": checks,
        "discordance_examples": counterexamples[:8],
        "source_labels_are_external_proof": False,
        "anchor_protects_against_adversarial_rewrite": False,
        "live_data": False,
        "network_calls": 0,
        "model_calls": 0,
        "server_actions": 0,
        "chatgpt_memory_changed": False,
        "not_generalization_evidence": True,
    }


def gates_pass(result: dict) -> bool:
    n = result["cases"]
    if not n or result["exact_accuracies"]["matched_p2"] < 0.9:
        return False
    check = result["checks"]
    if any(check[key] != n for key in (
        "same_decision", "replay_no_added_record", "alias_invariant",
        "reordered_invariant", "cold_reopen_invariant",
        "tampered_copy_detected",
    )):
        return False
    if check["p1_false_assertion_on_unknown"] or check["p2_false_assertion_on_unknown"]:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dev", action="store_true")
    group.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    report = run_equal_information(DEV_SEEDS if args.dev else HELDOUT_SEEDS)
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if gates_pass(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
