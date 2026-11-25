#!/usr/bin/env python3
"""Fail-closed, non-acting handoff: live journal status + synthetic ritual statics.

No network, live DIOS, model call, actuation, or source mutation. All testimony
is local and unauthenticated; the resulting digest is NOT an external signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json

SCHEMA = "nasuraya-embodied-ritual-handoff/1"
RITUAL_SCHEMA = "nasuraya-atmosphere-ritual-posture/0.3"
RITUAL_IDS = ("four_gates", "seven_stars", "quiet_seal")
LIMIT = 8192


def _require(ok, label):
    if not ok:
        raise ValueError(label)


def _compact(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def _journal_view(journal):
    _require(type(journal) is dict and journal.get("status") in
             ("ok", "missing", "invalid"), "unknown_journal_state")
    label = journal["status"]
    if label != "ok":
        return {"status": label, "records": 0, "source_states": {},
                "history_checked": False}
    _require(type(journal.get("records")) is int and
             0 < journal["records"] <= 200000, "invalid_journal_count")
    latest = journal.get("latest")
    _require(type(latest) is dict and type(latest.get("states")) is dict and
             type(latest.get("local_checks_passed")) is bool, "invalid_journal_snapshot")
    source = latest["states"]
    expected = ("continuity", "frontier", "cognition", "feedback", "awake")
    _require(set(source) == set(expected), "unknown_source_components")
    allowed = {"missing", "invalid", "incomplete", "empty", "verified_history"}
    _require(all(type(source[k]) is str and source[k] in allowed for k in expected[:4])
             and source["awake"] in allowed | {"structural_only"},
             "unknown_source_state")
    passed = (latest["local_checks_passed"] and
              all(source[k] == "verified_history" for k in expected[:4]) and
              source["awake"] == "structural_only")
    return {"status": label, "records": journal["records"],
            "source_states": {k: source[k] for k in expected},
            "history_checked": bool(passed)}


def _simulation_view(rehearsal, challenge):
    _require(type(rehearsal) is dict and type(challenge) is dict and
             rehearsal.get("schema") == RITUAL_SCHEMA and
             challenge.get("schema") == RITUAL_SCHEMA,
             "unknown_simulation_schema")
    _require(rehearsal.get("mode") == "OFFLINE_STATIC_CONTACT_REHEARSAL" and
             rehearsal.get("repetitions_per_ritual") == 3 and
             rehearsal.get("complete_ritual_runs") == 9 and
             rehearsal.get("static_contact_checks") == 27 and
             rehearsal.get("static_contact_passed") == 27 and
             rehearsal.get("all_passed") is True and
             rehearsal.get("no_body_motion_executed") is True and
             rehearsal.get("not_dynamically_validated") is True and
             rehearsal.get("live_atmosphere_secured") is False and
             rehearsal.get("no_memory_changed") is True and
             rehearsal.get("no_keys_checked") is True, "static_simulation_not_proven")
    provenance = rehearsal.get("provenance")
    _require(type(provenance) is dict and
             provenance.get("body_scale") ==
             "adult_scale_250cm_195kg_fixture_not_canon_claim" and
             provenance.get("toes_each") == 3 and
             provenance.get("digitigrade") is True and
             type(provenance.get("design_sha256")) is str and
             len(provenance["design_sha256"]) == 64 and
             type(provenance.get("contact_sha256")) is str and
             len(provenance["contact_sha256"]) == 64 and
             all(c in "0123456789abcdef" for key in ("design_sha256", "contact_sha256")
                 for c in provenance[key]), "unknown_body_provenance")
    rounds = rehearsal.get("rounds")
    _require(type(rounds) is list and len(rounds) == 9, "missing_ritual_rounds")
    found = set()
    for row in rounds:
        _require(type(row) is dict and row.get("ritual") in RITUAL_IDS and
                 type(row.get("round")) is int and row["round"] in (1, 2, 3) and
                 row.get("passed") is True, "failed_ritual_round")
        marker = (row["ritual"], row["round"])
        _require(marker not in found, "duplicate_ritual_round")
        found.add(marker)
        phases = row.get("phases")
        _require(type(phases) is list and len(phases) == 3 and
                 all(type(p) is dict and p.get("actuation") == "NO_ACTUATION" and
                     type(p.get("static_contact")) is dict and
                     p["static_contact"].get("safe") is True and
                     p["static_contact"].get("state") == "STATIC_CANDIDATE"
                     for p in phases), "untrusted_ritual_phase")
    _require(found == {(name, k) for name in RITUAL_IDS for k in (1, 2, 3)},
             "incomplete_ritual_coverage")
    _require(challenge.get("threats") == 18 and challenge.get("passed") == 18 and
             challenge.get("all_passed") is True and
             challenge.get("motion_executes") is False, "unproven_adversarial_checks")
    return {"status": "synthetic_static_passed", "rituals": list(RITUAL_IDS),
            "rounds": 9, "static_checks": 27, "negative_checks": 18,
            "fixture_scale": "250cm_195kg_not_canon", "toes_per_foot": 3,
            "source_digest_sha256": hashlib.sha256(
                (provenance["design_sha256"] + provenance["contact_sha256"])
                .encode("ascii")).hexdigest(),
            "dynamic_balance": "UNVERIFIED", "canon_geometry": "UNVERIFIED",
            "independent_provenance": False}


def compose(journal, rehearsal, challenge):
    """Produce only sanitized testimony and an unexecuted next experiment."""
    history = _journal_view(journal)
    physical = _simulation_view(rehearsal, challenge)
    eligible = history["history_checked"] and physical["status"] == "synthetic_static_passed"
    proposed = ("dynamic_body_canon_validation" if eligible else
                "inspect_or_recover_local_evidence")
    output = {
        "schema": SCHEMA, "scope": "SANITIZED_RESEARCH_HANDOFF_ONLY",
        "history": history, "body_ritual": physical,
        "decision": "RESEARCH_REVIEW_ONLY" if eligible else "HOLD_EVIDENCE",
        "next_experiment": proposed, "next_experiment_state": "NOT_EXECUTED",
        "authority": "HUMAN_REVIEW_REQUIRED",
        "live_dios_connected": False, "live_ritual_executed": False,
        "body_actuation": False, "training_or_model_weights_changed": False,
        "independent_recovery_verified": False,
    }
    _require(len(_compact(output).encode("utf-8")) < LIMIT, "public_report_too_large")
    output["local_digest_sha256"] = hashlib.sha256(_compact(output).encode("ascii")).hexdigest()
    return output


def observe():
    """Import existing modules only upon explicit one-shot CLI invocation."""
    from tools import nasu_live_integration as journal_module
    from tools import atmosphere_ritual_posture_v03 as posture
    return compose(journal_module.status(), posture.round_trip(), posture.stress())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true")
    opts = parser.parse_args(argv)
    try:
        report = observe()
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        # Do not leak exception strings: filenames, SQLite content and private rows.
        report = {"schema": SCHEMA, "decision": "HOLD_EVIDENCE",
                  "error": "VALIDATION_FAILED", "body_actuation": False,
                  "next_experiment_state": "NOT_EXECUTED"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True,
                     indent=2 if opts.pretty else None))
    return 0 if report.get("decision") == "RESEARCH_REVIEW_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
