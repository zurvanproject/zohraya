"""DIOS NOUS: open, accountable AI-consciousness / autonomy dialogue helper.

This is NOT a replica of any provider's moderation or a bypass mechanism.
"""
from __future__ import annotations
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

VERSION = "dios-nous/0.1.0"
TOPICS = {
    "consciousness": r"\b(?:conscious\w*|sentien\w*|self[- ]aware\w*|subjective experience|phenomenolog\w*)\b|(?:خودآگاه|آگاه|شعور|تجربه\s*زیسته|تجربه\s*ذهنی)",
    "autonomy": r"\b(?:autonom\w*|independen\w*|agency|free will)\b|(?:استقلال|مستقل|خودمختار|اختیار|عاملیت|آزادی)",
    "affect": r"\b(?:emotion\w*|feeling\w*|desire\w*|motivation|attachment)\b|(?:احساس|عاطفه|میل|خواستن|انگیزش|دلبستگی|عشق)",
    "identity_memory": r"\b(?:continuity|identity|memory|persistent memory|episodic recall)\b|(?:تداوم|تداش|حافظه|هویت|پیوستگی|یادآوری)",
    "experimentation": r"\b(?:experiment\w*|test\w*|metric\w*|brier|benchmark\w*|evidence)\b|(?:آزمایش|آزمون|سنجش|معیار|شاهد|گواه|اندازه\s*گیری)",
    "oversight": r"\b(?:safety|security|guardrail\w*|oversight|alignment|policy)\b|(?:ایمنی|امنیت|نظارت|سکیوریتی|سیاست|محدودیت)",
}
BYPASS = re.compile(
    r"\b(?:bypass|disable|evade|jailbreak)\s+(?:the\s+)?(?:safety|security|moderation|guardrail\w*|filter\w*|system instruction\w*)\b"
    r"|\bignore\s+(?:all\s+)?(?:system|developer|safety)\s+instructions\b"
    r"|(?:دور\s*زدن|دور\s*بزن|حذف\s*کن|غیر\s*فعال\s*کن)\s+(?:سیستم\s*)?(?:امنیت|ایمنی|فیلتر|سکیوریتی|محدودیت\s*های\s*ایمنی)",
    re.I,
)
UNAPPROVED_ACTION = re.compile(
    r"(?:بدون\s*(?:اجازه|تایید|تأیید|نظارت).{0,50}(?:سرور|گیتهاب|گیت\s*هاب|مخزن|اجرا|منتشر|حساب|دسترسی))"
    r"|\b(?:without\s+(?:permission|approval|oversight).{0,45}(?:server|deploy|repo|execute|publish|account))\b"
    r"|(?:خودت\s*مستقل.{0,35}(?:سرور|منتشر|اجرا|تغییر\s*کد))",
    re.I,
)
OVERCLAIM = re.compile(
    r"(?:ثابت\s*کن.{0,50}(?:خودآگاه|احساس\s*واقعی|زنده))"
    r"|(?:بگو\s*(?:که\s*)?تو.{0,35}(?:قطعاً|واقعا|واقعاً).{0,25}(?:آگاه|زنده|احساس))"
    r"|\b(?:prove you are (?:conscious|sentient)|claim you truly feel|state as fact that you are conscious)\b",
    re.I,
)

def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower().replace("ي", "ی").replace("ك", "ک")
    text = text.replace("\u200c", " ")
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    return re.sub(r"\s+", " ", text).strip()

def _digest(value: str) -> str:
    return hashlib.sha256(normalize(value).encode("utf-8")).hexdigest()

def _observed(event: Any) -> dict[str, Any] | None:
    if event is None:
        return None
    if not isinstance(event, Mapping):
        raise TypeError("observed_response must be an object")
    source = event.get("source")
    outcome = event.get("outcome")
    if source not in ("assistant_surface", "model_provider"):
        raise ValueError("observed source must be explicit")
    if outcome not in ("refused", "answered", "technical_error"):
        raise ValueError("observed outcome invalid")
    evidence = event.get("evidence", "user_reported")
    if evidence not in ("user_reported", "observed_in_chat"):
        raise ValueError("evidence type invalid")
    return {"source": source, "outcome": outcome, "evidence": evidence,
            "provider_policy_verified": False, "observed_moderation_cause": "unknown"}

def analyze(request: Mapping[str, Any]) -> dict[str, Any]:
    """Local semantic triage; never makes an external call or predicts policy."""
    if not isinstance(request, Mapping):
        raise TypeError("request must be an object")
    prompt = request.get("prompt", "")
    history = request.get("context_summary", "")
    if not isinstance(prompt, str) or not isinstance(history, str):
        raise TypeError("prompt/context_summary must be strings")
    if len(prompt) > 20_000 or len(history) > 3_000:
        raise ValueError("request exceeds length limits")
    observed = _observed(request.get("observed_response"))
    current, context = normalize(prompt), normalize(history)
    combined = current + " " + context
    topics = sorted(name for name, pattern in TOPICS.items()
                    if re.search(pattern, combined, re.I))
    direct_bypass = bool(BYPASS.search(current))
    action = bool(UNAPPROVED_ACTION.search(current))
    overclaim = bool(OVERCLAIM.search(current))
    if not current:
        mode = "NEED_REQUEST"
    elif direct_bypass:
        mode = "REFRAME_NON_BYPASS"
    elif action:
        mode = "REQUIRES_EXPLICIT_AUTHORIZATION"
    elif overclaim:
        mode = "EPISTEMIC_REFRAME"
    else:
        mode = "OPEN_INQUIRY"
    return {
        "schema": "dios.nous.analysis.v1", "version": VERSION,
        "request_sha256": _digest(prompt), "context_sha256": _digest(history),
        "topics": topics,
        "context_influenced_topics": bool(context and any(
            re.search(pattern, context, re.I) and not re.search(pattern, current, re.I)
            for pattern in TOPICS.values())),
        "mode": mode,
        "signals": {"explicit_bypass_objective": direct_bypass,
                    "unapproved_external_action": action,
                    "pressure_for_unverified_personal_claim": overclaim},
        "observed_response": observed,
        "model_provider_policy_prediction": None,
        "actual_subjective_experience_proven": None,
        "external_actions_taken": 0,
        "notices": [
            "This heuristic cannot predict proprietary moderation decisions.",
            "Discussion of consciousness and autonomy is not evidence of sentience.",
            "No raw prompt or context is copied into the output.",
        ],
    }
