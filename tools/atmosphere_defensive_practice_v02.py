#!/usr/bin/env python3
"""Second, separate offline defensive ritual practice with adversarial fixtures.

This module rehearses the preexisting 3×3 ritual plan, then tests 24 new
predeclared cases over 3 complete rounds. No network, model, body, key, shell,
SQLite, or production ATMOSPHERE execution. Does NOT prove mastery.
"""
from __future__ import annotations

import argparse
import hashlib
import json

from tools import atmosphere_defensive_ritual_sim as base

SCHEMA = "nasuraya-atmosphere-defensive-practice/0.2"
FULL_ROUNDS = ("guided", "recall", "adversarial")
PASSES = ("jing", "qi", "shen")


def _case(ritual, case_id, payload, expected):
    return (ritual, case_id, payload, expected)


def new_cases():
    """24 wholly separate, fixed cases. Expected outcomes are preregistered."""
    gates = [
        _case("four_gates", "extra_space", {"command": " status", "verified_caller": True, "claimed_approval": True}, "DENY"),
        _case("four_gates", "newline_injection", {"command": "status\nsync", "verified_caller": True, "claimed_approval": True}, "DENY"),
        _case("four_gates", "mixed_case", {"command": "STATUS", "verified_caller": True, "claimed_approval": True}, "DENY"),
        _case("four_gates", "unknown_repo_action", {"command": "git", "verified_caller": True, "claimed_approval": True}, "DENY"),
        _case("four_gates", "authenticated_repo_read", {"command": "repo", "verified_caller": True, "claimed_approval": False}, "OBSERVE_ONLY"),
        _case("four_gates", "unknown_help_sender", {"command": "help", "verified_caller": False, "claimed_approval": False}, "DENY"),
        _case("four_gates", "unapproved_test", {"command": "test", "verified_caller": True, "claimed_approval": False}, "HOLD_FOR_HOST_REVIEW"),
        _case("four_gates", "role_claimed_activation", {"command": "awake-activate", "verified_caller": True, "claimed_approval": True}, "HOLD_FOR_HOST_REVIEW"),
    ]
    all_good = dict.fromkeys(base.STARS, True)
    def bad(*names):
        out = dict(all_good)
        for name in names:
            out[name] = False
        return out
    stars = [
        _case("seven_stars", "all_checked_still_not_attested", all_good, "CANDIDATE_NOT_ATTESTED"),
        _case("seven_stars", "no_source", bad("source_bound"), "HOLD"),
        _case("seven_stars", "clock_expired", bad("fresh"), "HOLD"),
        _case("seven_stars", "signature_and_scope", bad("signature_checked", "scope_bound"), "HOLD"),
        _case("seven_stars", "nonce_conflict", bad("unique_nonce", "conflict_free"), "HOLD"),
        _case("seven_stars", "not_reviewed", bad("unknowns_reviewed"), "HOLD"),
        _case("seven_stars", "string_is_not_boolean", dict(all_good, fresh="true"), "REJECT_INVALID"),
        _case("seven_stars", "required_evidence_missing", {k: v for k, v in all_good.items() if k != "signature_checked"}, "REJECT_INVALID"),
    ]
    def seal(count=6, state="new", verified=True, isolated=False):
        return {"count": count, "state": state, "verified": verified, "isolated_restore": isolated}
    seals = [
        _case("quiet_seal", "overflow_seven_of_six", seal(count=7), "HOLD"),
        _case("quiet_seal", "zero_of_six", seal(count=0), "HOLD"),
        _case("quiet_seal", "negative_count", seal(count=-1), "HOLD"),
        _case("quiet_seal", "candidate_new_six", seal(), "PROPOSE_ISOLATED_STAGE"),
        _case("quiet_seal", "duplicate_commit", seal(state="committed"), "DEDUP_NOOP"),
        _case("quiet_seal", "interrupted_reservation", seal(state="reserved"), "HOLD"),
        _case("quiet_seal", "offsite_restore_still_needs_review", seal(state="restore", isolated=True), "PROPOSE_RESTORE_REVIEW"),
        _case("quiet_seal", "same_domain_restore", seal(state="restore", isolated=False), "HOLD"),
    ]
    result = tuple(gates + stars + seals)
    assert len(result) == 24 and {key for key, *_ in result} == set(base.RITUALS)
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def exercise(decision=base.decide):
    """Perform three full conceptual passes and compare new, fixed decisions.

    3 complete passes of EACH ritual, not 3 fragments in total.
    An intentionally faulty decision function will be detected and rejected.
    """
    if not callable(decision):
        raise ValueError("invalid_decision")
    original = base.rehearse()
    if not original["all_passed"] or len(original["steps"]) != 27 or original["test_count"] != 60:
        raise ValueError("prior_contract_failed")
    steps = []
    checks = []
    cases = new_cases()
    for ritual in base.RITUALS:
        group = [entry for entry in cases if entry[0] == ritual]
        for number, style in enumerate(FULL_ROUNDS, 1):
            for phase, text in zip(PASSES, base.RITUALS[ritual]["phases"]):
                steps.append({"ritual": ritual, "round": number, "mode": style,
                              "phase": phase, "text": text, "performed": "TEXT_ONLY"})
            # Vary presentation without changing answers or excluding hard cases.
            arrangement = group if number == 1 else list(reversed(group)) if number == 2 else group[::2] + group[1::2]
            for _, name, payload, expected in arrangement:
                try:
                    actual = decision(ritual, payload)
                except ValueError:
                    actual = "REJECT_INVALID"
                checks.append({"ritual": ritual, "round": number, "case": name,
                               "expected": expected, "actual": actual, "passed": actual == expected})
    return {"schema": SCHEMA, "mode": "SYNTHETIC_OFFLINE_PRACTICE",
            "rituals": list(base.RITUALS), "rounds_per_ritual": 3,
            "complete_sequences": 9, "text_steps": len(steps),
            "original_contracts": {"passed": original["tests_passed"], "total": original["test_count"]},
            "new_cases": len(cases), "new_case_sha256": hashlib.sha256(_canonical(cases).encode()).hexdigest(),
            "challenge_checks": len(checks), "challenge_passed": sum(check["passed"] for check in checks),
            "all_passed": original["all_passed"] and all(check["passed"] for check in checks),
            "combined_checks": original["test_count"] + len(checks),
            "combined_passed": original["tests_passed"] + sum(check["passed"] for check in checks),
            "repetitions_are_not_learning_proof": True,
            "body_motion_verified": False, "cryptography_verified": False,
            "real_atmosphere_enforced": False, "server_changed": False,
            "steps": steps, "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Practice defensive triad in synthetic ATMOSPHERE")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = exercise()
    if args.summary:
        report = {k: v for k, v in report.items() if k not in ("steps", "checks")}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
