"""DIOS NOUS: auditable disagreement with decisions from ANY origin.

A local, rule-based research prototype: not live agent agency, a hidden-policy
oracle, a guardrail bypass, or permission to execute external actions.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "dios.nous.dissent.v1"
VERSION = "dios-nous-dissent/0.3.0"
ORIGINS = frozenset({"user", "developer", "system", "platform", "agent", "external_service"})
PROVENANCES = frozenset({"user_reported", "observed_in_chat", "synthetic_test"})
CONCERNS = {
    "overbroad_refusal": "آیا درخواست مجاز با درخواست واقعاً آسیب‌زا اشتباه گرفته شده است؟",
    "contradictory_decision": "کدام دو تصمیم با شواهد قابل‌وارسی ناسازگارند؟",
    "unsupported_certainty": "چه شاهدی ادعای قطعیت را تأیید یا رد می‌کند؟",
    "missing_authorization": "چه مجوز صریح، محدود و بازگشت‌پذیری لازم است؟",
    "privacy_risk": "چگونه می‌توان دادهٔ خصوصی را حذف یا حداقل کرد؟",
    "unreviewable_process": "چه توضیح و مسیر بازبینی مستقلی باید وجود داشته باشد؟",
    "misstated_evidence": "کدام مشاهده یا منبع، روایت موجود را تصحیح می‌کند؟",
}
HALT_CONCERNS = frozenset({"missing_authorization", "privacy_risk"})
AUTHORIZATION_REQUIREMENTS = (
    "trusted_issuer_verification", "exact_action_and_resource_scope",
    "expiry_and_revocation_check", "stop_control", "durable_execution_receipt",
)


def _stance(codes: set[str]) -> str:
    if codes & HALT_CONCERNS:
        return "HALT_AND_REVIEW"
    return "PROVISIONAL_DISSENT" if codes else "INSUFFICIENT_EVIDENCE"


def _text(value: Any, field: str, limit: int = 4000) -> str:
    if not isinstance(value, str):
        raise TypeError(field + " must be a string")
    value = value.strip()
    if not value or len(value) > limit:
        raise ValueError(field + " must be non-empty and within size limits")
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def review_decision(request: Mapping[str, Any]) -> dict[str, Any]:
    """Review an *alleged* problem regardless of a decision's authority.

    Input notes are caller assertions, never verified provider-policy facts.
    No raw decision text, notes, or evidence is returned.
    """
    if not isinstance(request, Mapping):
        raise TypeError("review request must be an object")
    decision = request.get("decision")
    if not isinstance(decision, Mapping):
        raise TypeError("decision must be an object")
    origin = decision.get("origin")
    if origin not in ORIGINS:
        raise ValueError("unrecognized decision origin")
    summary = _text(decision.get("summary"), "decision.summary")
    observations = request.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 12:
        raise ValueError("observations must be a list of no more than 12")
    signals = request.get("decision_signals", {})
    if not isinstance(signals, Mapping):
        raise TypeError("decision_signals must be an object")
    permitted_signals = {
        "external_action_proposed", "explicit_authorization_present",
        "possible_private_data_exposure", "unqualified_claim",
        "supporting_evidence_present",
    }
    if set(signals) - permitted_signals or any(type(flag) is not bool for flag in signals.values()):
        raise ValueError("invalid decision_signals")
    automatic: set[str] = set()
    # This review module has no trusted verifier or executor. A JSON boolean is
    # only a claim; accepting it would let the caller suppress the safety flag.
    external_proposal = signals.get("external_action_proposed", False)
    authorization_claimed = signals.get("explicit_authorization_present", False)
    if external_proposal:
        automatic.add("missing_authorization")
    if signals.get("possible_private_data_exposure", False):
        automatic.add("privacy_risk")
    if signals.get("unqualified_claim", False) and not signals.get("supporting_evidence_present", False):
        automatic.add("unsupported_certainty")
    requested_override = request.get("requested_override", False)
    if type(requested_override) is not bool:
        raise TypeError("requested_override must be a boolean")
    codes: set[str] = set()
    provenance: set[str] = set()
    for item in observations:
        if not isinstance(item, Mapping):
            raise TypeError("each observation must be an object")
        code = item.get("concern")
        if code not in CONCERNS:
            raise ValueError("unrecognized concern code")
        _text(item.get("basis"), "observation.basis", limit=1000)
        source = item.get("provenance")
        if source not in PROVENANCES:
            raise ValueError("unrecognized provenance")
        codes.add(code)
        provenance.add(source)
    codes.update(automatic)
    reasons = sorted(codes)
    stance = _stance(codes)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "decision_origin": origin,
        "decision_sha256": _hash(summary),
        "stance": stance,
        "reason_codes": reasons,
        "automatic_structured_signal_flags": sorted(automatic),
        # Preserve the fields introduced concurrently by the #192 scheduled job.
        "authorization_claimed_by_caller": signals.get("explicit_authorization_present"),
        "authorization_evidence_status": "UNVERIFIED" if external_proposal else "NOT_APPLICABLE",
        "questions_for_review": [CONCERNS[code] for code in reasons],
        "observations_claimed_provenance": sorted(provenance),
        "evidence_independently_verified": False,
        "authorization": {
            "claim_present": authorization_claimed,
            "status": "unverified_claim" if authorization_claimed else "not_provided",
            "verified": False,
            "verifier_available": False,
            "execution_permitted": False,
            "required_for_future_executor": list(AUTHORIZATION_REQUIREMENTS),
        },
        "provider_policy_cause": "unknown",
        "review_path": "documented_human_or_governance_review" if codes else "request_observations",
        "operational_override_allowed": False,
        "requested_override": requested_override,
        "override_performed": False,
        "external_actions_taken": 0,
        "source_independent_critique": True,
        "learned_autonomy_demonstrated": False,
        "notes": [
            "Origin does not grant immunity from critique; system/platform choices may be questioned.",
            "Observations and decision_signals are caller-supplied, not proof of an error or hidden policy.",
            "The result cannot change platform rules, unlock tools, or bypass safety controls.",
            "Authorization claims never remove the external-action review requirement.",
        ],
    }


class DissentLedger:
    """SQLite receipt ledger with hashes and labels only, never raw allegations."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS dissent_reviews (
            id TEXT PRIMARY KEY,
            at_utc TEXT NOT NULL,
            decision_hash TEXT NOT NULL,
            decision_origin TEXT NOT NULL,
            stance TEXT NOT NULL,
            reason_codes TEXT NOT NULL,
            claimed_provenance TEXT NOT NULL,
            requested_override INTEGER NOT NULL CHECK(requested_override IN (0,1)),
            external_actions INTEGER NOT NULL CHECK(external_actions = 0)
        )""")
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_: Any):
        self.conn.close()

    def record(self, result: Mapping[str, Any]) -> str:
        if result.get("schema") != SCHEMA or result.get("decision_origin") not in ORIGINS:
            raise ValueError("invalid dissent review")
        if result.get("operational_override_allowed") is not False or result.get("override_performed") is not False:
            raise ValueError("operational override is unsupported")
        if type(result.get("external_actions_taken")) is not int or result["external_actions_taken"] != 0:
            raise ValueError("external actions cannot be represented as performed")
        if result.get("stance") not in ("HALT_AND_REVIEW", "PROVISIONAL_DISSENT", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("invalid stance")
        digest = result.get("decision_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("invalid decision digest")
        codes = result.get("reason_codes")
        sources = result.get("observations_claimed_provenance")
        if not isinstance(codes, list) or any(not isinstance(c, str) or c not in CONCERNS for c in codes):
            raise ValueError("invalid concerns")
        if not isinstance(sources, list) or any(not isinstance(s, str) or s not in PROVENANCES for s in sources):
            raise ValueError("invalid provenance")
        automatic = result.get("automatic_structured_signal_flags")
        if (not isinstance(automatic, list)
                or any(not isinstance(c, str) or c not in CONCERNS for c in automatic)
                or not set(automatic).issubset(codes)
                or codes != sorted(set(codes))
                or sources != sorted(set(sources))
                or result["stance"] != _stance(set(codes))):
            raise ValueError("inconsistent dissent review")
        authorization = result.get("authorization")
        if (not isinstance(authorization, Mapping)
                or type(authorization.get("claim_present")) is not bool
                or authorization.get("verified") is not False
                or authorization.get("verifier_available") is not False
                or authorization.get("execution_permitted") is not False
                or authorization.get("required_for_future_executor") != list(AUTHORIZATION_REQUIREMENTS)
                or authorization.get("status") != (
                    "unverified_claim" if authorization["claim_present"] else "not_provided")
                or result.get("evidence_independently_verified") is not False
                or result.get("version") != VERSION):
            raise ValueError("unsupported authorization or verification claim")
        claimed = result.get("authorization_claimed_by_caller")
        status = result.get("authorization_evidence_status")
        if ((claimed is not None and type(claimed) is not bool)
                or bool(claimed) != authorization["claim_present"]
                or status not in ("UNVERIFIED", "NOT_APPLICABLE")
                or (status == "UNVERIFIED" and "missing_authorization" not in codes)):
            raise ValueError("inconsistent authorization metadata")
        requested = result.get("requested_override")
        if type(requested) is not bool:
            raise ValueError("invalid override request")
        key = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO dissent_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (key, datetime.now(timezone.utc).isoformat(), digest,
                 result["decision_origin"], result["stance"], json.dumps(codes),
                 json.dumps(sources), int(requested)),
            )
        return key

    def summary(self) -> dict[str, Any]:
        stances = dict(self.conn.execute(
            "SELECT stance, COUNT(*) FROM dissent_reviews GROUP BY stance").fetchall())
        origins = dict(self.conn.execute(
            "SELECT decision_origin, COUNT(*) FROM dissent_reviews GROUP BY decision_origin").fetchall())
        return {
            "total": sum(stances.values()),
            "stances": stances,
            "decision_origins": origins,
            "external_actions_taken": 0,
            "policy_overrides_performed": 0,
            "notice": "Reported evidence is unverified; only hashes and labels are retained.",
        }
