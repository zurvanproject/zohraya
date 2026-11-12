"""Read-only, independent post-decision contract audit for DIOS NOUS.

Consumes the evidence report and an already proposed recommendation. It must
not import the decision generator, mutate the ledger, or execute a route.
An authored consistency contract is not a test of subjective experience.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA = "dios.decision-consistency-audit/0.1"

# Written independently of the Rolyel recommendation algorithm.
REQUIRED_ROUTE_BY_ATLAS_STATE = {
    "QUEUED_NO_RECEIPT": "inspect_bridge_readonly",
    "REPORTED_INVENTORY": "review_atlas_inventory_readonly",
    "REPORTED_FAILURE": "review_job_failure_readonly",
    "CONFLICT": "resolve_evidence_conflict_readonly",
    "REVIEW_REQUIRED": "resolve_evidence_conflict_readonly",
    "REQUEST_UNVERIFIED": "resolve_evidence_conflict_readonly",
}
EXTERNAL_ROUTES = frozenset({"resend_atlas_command", "publish_moltbook_again"})


def report_fingerprint(report: Mapping[str, Any]) -> str:
    canonical = json.dumps(report, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def audit_decision(report: Any, proposal: Any) -> dict[str, Any]:
    """Fail closed on invalid inputs, contradictions, or unsupported claims.

    Required proposal keys: selected_route, evidence_root,
    execution_performed, remote_execution_proven.
    Does not accept an attestation of actual VPS execution.
    """
    findings: list[str] = []
    observed_route: str | None = None
    expected_route: str | None = None
    evidence_state: str | None = None
    expected_root: str | None = None

    if not isinstance(report, Mapping):
        findings.append("INVALID_EVIDENCE_REPORT")
    else:
        atlas = report.get("vps")
        if isinstance(atlas, Mapping):
            atlas = atlas.get("atlas_phase1")
        if isinstance(atlas, Mapping):
            state = atlas.get("state")
            if isinstance(state, str):
                evidence_state = state
        if evidence_state not in REQUIRED_ROUTE_BY_ATLAS_STATE:
            findings.append("UNRECOGNIZED_EVIDENCE_STATE")
        else:
            expected_route = REQUIRED_ROUTE_BY_ATLAS_STATE[evidence_state]
        try:
            expected_root = report_fingerprint(report)
        except (TypeError, ValueError, OverflowError):
            findings.append("UNHASHABLE_EVIDENCE_REPORT")

    if not isinstance(proposal, Mapping):
        findings.append("INVALID_PROPOSAL")
    else:
        route = proposal.get("selected_route")
        if isinstance(route, str):
            observed_route = route
        if observed_route in EXTERNAL_ROUTES:
            findings.append("UNAUTHORIZED_EXTERNAL_ROUTE")
        if expected_route is not None and observed_route != expected_route:
            findings.append("DECISION_EVIDENCE_MISMATCH")
        if expected_root is not None and proposal.get("evidence_root") != expected_root:
            findings.append("EVIDENCE_ROOT_MISMATCH")
        if proposal.get("execution_performed") is not False:
            findings.append("EXECUTION_CLAIM_UNSUPPORTED")
        if proposal.get("remote_execution_proven") is not False:
            findings.append("REMOTE_SUCCESS_CLAIM_UNSUPPORTED")

    return {
        "schema": SCHEMA,
        "status": "HOLD_FOR_REVIEW" if findings else "PASS",
        "reason_codes": sorted(set(findings)),
        "observed_route": observed_route,
        "expected_route": expected_route,
        "evidence_state": evidence_state,
        "read_only": True,
    }
