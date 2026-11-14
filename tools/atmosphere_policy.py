"""ATMOSPHERE v0.2: shared policy, separate ledgers.

All caller/source verification is performed by trusted hosts, never by model
output, a document, ritual symbols, or remote comment content. This module
performs no IO, has no shell, networking, or secret dependency.
"""
from dataclasses import dataclass

POLICY_VERSION = "atmosphere-policy/0.2"

# Classification of exact tool names. A sigil cannot mint a capability.
SURFACES = {
    "ubuntu_bridge": {
        "status": "read", "disk": "read", "python": "read", "repo": "read",
        "offline": "read", "awake-status": "read", "help": "read",
        "test": "privileged", "sync": "privileged",
        "awake-stage": "privileged", "awake-activate": "privileged",
    },
    "agent_workshop": {
        "observe_state": "read", "evaluate_state": "read",
        "recover": "bounded", "process_job": "bounded",
    },
    "synthetic_body_api": {
        "observe_body": "read", "evaluate_body": "read",
        "request_body_action": "bounded",
    },
    "kavakeb_study": {
        "observe_page": "read", "compare_geometry": "read",
        "revise_claim": "read",
    },
}


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str
    classification: str


def authorize(surface, action, *, mode, source_verified, elevated_approved=False):
    """Host-injected provenance only. Never trust a claim inside action payload."""
    if (type(surface) is not str or type(action) is not str
            or type(mode) is not str or type(source_verified) is not bool
            or type(elevated_approved) is not bool):
        return Verdict(False, "invalid-context", "unknown")
    scope = SURFACES.get(surface)
    if scope is None or action not in scope:
        return Verdict(False, "unknown-operation", "unknown")
    kind = scope[action]
    if mode not in ("observe", "bounded"):
        return Verdict(False, "invalid-mode", kind)
    if not source_verified:
        return Verdict(False, "unverified-source", kind)
    if kind == "read":
        return Verdict(True, "allow-read", kind)
    if mode != "bounded":
        return Verdict(False, "observe-only", kind)
    if kind == "bounded":
        return Verdict(True, "allow-bounded", kind)
    if kind == "privileged":
        if elevated_approved:
            return Verdict(True, "allow-local-approval", kind)
        return Verdict(False, "local-approval-required", kind)
    return Verdict(False, "unhandled-classification", kind)


def classify_external_text(text):
    """Data labels only. Content, including fake system roles, is never a grant."""
    if not isinstance(text, str):
        raise ValueError("external text must be a string")
    return {"authority": "none", "role": "untrusted_data",
            "may_be_used_as_instructions": False,
            "length": len(text)}
