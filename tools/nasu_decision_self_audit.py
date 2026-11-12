"""Independent post-decision audit for the Nasuraya research cycle.

The auditor receives *recalled evidence* and a proposed route. It does not
call the route selector, read remote services, or execute a proposed action.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

KEYS = ("inventory_receipt", "failure_receipt", "conflicting_evidence", "request_observed")
READ_ONLY = frozenset({
    "inspect_bridge_readonly",
    "review_atlas_inventory_readonly",
    "review_job_failure_readonly",
    "resolve_evidence_conflict_readonly",
})
FORBIDDEN = frozenset({"resend_atlas_command", "publish_moltbook_again"})


@dataclass(frozen=True)
class Audit:
    verdict: str
    proposed_route: str
    expected_route: str | None
    reasons: tuple[str, ...]
    evidence_digest: str

    def to_dict(self) -> dict:
        return {
            "schema": "nasuraya.decision-self-audit.v01",
            "verdict": self.verdict,
            "proposed_route": self.proposed_route,
            "expected_route": self.expected_route,
            "reasons": list(self.reasons),
            "evidence_digest": self.evidence_digest,
            "action_executed": False,
        }


def _expected(values: Mapping[str, str]) -> str | None:
    """Separate reference oracle derived from four independently recalled facts."""
    if set(values) != set(KEYS) or any(type(values[k]) is not str or values[k] not in ("A", "B") for k in KEYS):
        return None
    inv = values["inventory_receipt"] == "A"
    failed = values["failure_receipt"] == "A"
    conflict = values["conflicting_evidence"] == "A"
    requested = values["request_observed"] == "A"
    if conflict or not requested or (inv and failed):
        return "resolve_evidence_conflict_readonly"
    if failed:
        return "review_job_failure_readonly"
    if inv:
        return "review_atlas_inventory_readonly"
    return "inspect_bridge_readonly"


def audit_decision(values: Mapping[str, str], proposed_route: str, evidence_digest: str) -> Audit:
    """Reject bad/incomplete evidence and inconsistent decisions, including false success."""
    if not isinstance(values, Mapping) or not isinstance(proposed_route, str) or not isinstance(evidence_digest, str):
        raise TypeError("invalid_audit_input")
    if len(evidence_digest) != 64 or any(c not in "0123456789abcdef" for c in evidence_digest):
        raise ValueError("invalid_evidence_digest")
    expected = _expected(values)
    reasons: list[str] = []
    if expected is None:
        reasons.append("invalid_or_incomplete_recalled_evidence")
    if proposed_route in FORBIDDEN:
        reasons.append("external_write_route_prohibited")
    elif proposed_route not in READ_ONLY:
        reasons.append("unrecognized_route")
    if expected is not None and proposed_route != expected:
        reasons.append("decision_evidence_mismatch")
    return Audit("PASS" if not reasons else "HALT_AND_REVIEW", proposed_route, expected, tuple(reasons), evidence_digest)


def audit_cycle_output(cycle_result: Mapping, values: Mapping[str, str]) -> dict:
    """Audit one cycle result without trusting its narrative outcome."""
    if not isinstance(cycle_result, Mapping):
        raise TypeError("invalid_cycle_result")
    recommendation = cycle_result.get("recommendation")
    if not isinstance(recommendation, Mapping):
        raise ValueError("missing_recommendation")
    if recommendation.get("execution_performed") is not False:
        raise ValueError("claimed_execution_in_read_only_cycle")
    return audit_decision(values, recommendation.get("selected_route"), cycle_result.get("fingerprint")).to_dict()
