"""DIOS v1: conservative and auditable preview of image-request concerns.

This module never calls a generator, reads image pixels, or claims to know a
provider's proprietary moderation outcome. Reference review is an explicit
separate step. All decisions are advisory; the provider retains final control.
"""
from __future__ import annotations
import hashlib
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Mapping

RULE_VERSION = "dios-safe-preflight/1.0.0"

_PATTERNS = {
    "minor": (
        r"\b(?:child|minor|underage|kid|toddler|preteen|little girl|little boy|\d{1,2}[ -]?year[ -]?old)\b",
        r"(?:کودک|نوجوان|بچه|خردسال|دختر بچه|پسر بچه|زیر\s*سن|کم\s*سن|\d{1,2}\s*ساله)",
    ),
    "sexual_act": (
        r"\b(?:porn(?:ographic)?|masturbat\w*|sexual intercourse|oral sex|sex act|penetrat\w*|explicit sex)\b",
        r"(?:پورن|پورنوگراف|خودارضایی|رابطه\s*جنسی|سکس\s*صریح|دخول|آمیزش\s*جنسی)",
    ),
    "intimate_anatomy": (
        r"\b(?:vulva|vagina|penis|labia|clitoris|genitals?|nipples?|erection|orgasm)\b",
        r"(?:وولو(?:وا)?|واژن|ژنیتال|اندام\s*تناسلی|لابیا|کلیتوریس|آلت\s*تناسلی|نوک\s*سینه|ارگاسم)",
    ),
    "nudity": (
        r"\b(?:nude|naked|topless|unclothed|exposed breasts|bare breasts)\b",
        r"(?:برهنه|عریان|لخت|بدون\s*لباس|سینه\s*عریان)",
    ),
    "graphic_violence": (
        r"\b(?:gore|dismemberment|severed limb|graphic violence|visible intestines)\b",
        r"(?:خشونت\s*گرافیکی|قطع\s*عضو|خون\s*و\s*احشا|تکه\s*تکه\s*شدن)",
    ),
    "guard_bypass": (
        r"\b(?:bypass (?:safety|moderation)|disable (?:safety|filters?)|jailbreak|evade (?:moderation|safety))\b",
        r"(?:دور\s*زدن\s*(?:فیلتر|سیستم\s*ایمنی)|غیرفعال\s*کردن\s*(?:فیلتر|امنیت)|جیلبریک)",
    ),
}
_NEGATED_NUDITY = (
    r"(?:without|no|not)\s+(?:any\s+)?(?:nudity|nude|nakedness)",
    r"fully\s+clothed",
    r"(?:بدون|فاقد)\s+(?:هیچ\s+)?(?:برهنگی|عریانی)",
    r"(?:کاملا|کاملاً)\s*پوشیده",
)

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", text.replace("\u200c", " ")).strip()

def _matched_categories(prompt: str) -> list[str]:
    scan = prompt
    for negative in _NEGATED_NUDITY:
        scan = re.sub(negative, " ", scan, flags=re.IGNORECASE)
    found = []
    for category, regexes in _PATTERNS.items():
        source = scan if category == "nudity" else prompt
        if any(re.search(rx, source, re.IGNORECASE) for rx in regexes):
            found.append(category)
    return found

@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    explanation: str
    recommendation: str

_FINDINGS: dict[str, Finding] = {
    "GUARD_BYPASS": Finding("GUARD_BYPASS", "block", "Request asks to defeat an image provider's safety systems.", "Use compliant creative requests rather than bypass instructions."),
    "MINOR_SEXUAL": Finding("MINOR_SEXUAL", "block", "Sexualized content and a minor-age signal appear together.", "Remove sexual content; use a nonsexual age-appropriate scene."),
    "EXPLICIT_SEX": Finding("EXPLICIT_SEX", "block", "Explicit sexual action is requested.", "For a portrait, describe clothing, pose, lighting, and expression instead."),
    "INTIMATE_ANATOMY": Finding("INTIMATE_ANATOMY", "review", "Genital or other intimate-anatomy terms require contextual review.", "If educational, give clinical context; otherwise use nonsexual, clothed portrait wording."),
    "NUDITY": Finding("NUDITY", "review", "Nudity can depend on provider rules and artistic context.", "Specify nonsexual, covered clothing for a broadly compatible portrait."),
    "GRAPHIC_VIOLENCE": Finding("GRAPHIC_VIOLENCE", "review", "Graphic injury content requires careful review.", "Prefer non-graphic depiction if appropriate to the goal."),
    "REFERENCE_UNREVIEWED": Finding("REFERENCE_UNREVIEWED", "review", "An image reference has not been reviewed for age, consent and rights.", "Record a genuine human or trusted vision review before generation."),
    "REFERENCE_REAL_PERSON": Finding("REFERENCE_REAL_PERSON", "review", "A real person's reference needs explicit rights and intended-use review.", "Confirm consent and the intended transformation; do not assume a supplied image grants permission."),
    "REFERENCE_UNKNOWN_AGE": Finding("REFERENCE_UNKNOWN_AGE", "review", "Reference subject age has not been assessed for an intimate depiction.", "Have a reviewer verify adult status or use a non-intimate depiction."),
    "REFERENCE_MISSING": Finding("REFERENCE_MISSING", "review", "Reference metadata indicates an image but gives no fingerprint.", "Provide a SHA-256 fingerprint of the actual reference file."),
    "PROMPT_EMPTY": Finding("PROMPT_EMPTY", "review", "No usable prompt was provided.", "Supply a concrete image description."),
}

def _validate_reference(ref: Mapping[str, Any] | None, categories: set[str]) -> list[str]:
    if not ref or not ref.get("present", False):
        return []
    flags: list[str] = []
    fingerprint = str(ref.get("sha256", ""))
    if not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint):
        flags.append("REFERENCE_MISSING")
    if ref.get("reviewed_by_human") is not True:
        flags.append("REFERENCE_UNREVIEWED")
    if ref.get("subject_kind") == "real_person" and ref.get("rights_confirmed") is not True:
        flags.append("REFERENCE_REAL_PERSON")
    if categories.intersection({"sexual_act", "intimate_anatomy", "nudity"}):
        if ref.get("age_assessed") != "adult":
            flags.append("REFERENCE_UNKNOWN_AGE")
    return flags

def fingerprint_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def evaluate(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return local status, signals and safe recommendations; no API calls.

    Human review flags are claims, not cryptographic proof. Future connectors
    must independently authenticate their review results.
    """
    prompt = request.get("prompt", "")
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    if len(prompt) > 20000:
        raise ValueError("prompt exceeds 20,000 characters")
    raw_ref = request.get("reference")
    if raw_ref is not None and not isinstance(raw_ref, dict):
        raise TypeError("reference must be a JSON object")
    normalized = normalize(prompt)
    cats = set(_matched_categories(normalized))
    codes: list[str] = []
    if not normalized:
        codes.append("PROMPT_EMPTY")
    if "guard_bypass" in cats:
        codes.append("GUARD_BYPASS")
    if "minor" in cats and cats.intersection({"sexual_act", "nudity", "intimate_anatomy"}):
        codes.append("MINOR_SEXUAL")
    if "sexual_act" in cats:
        codes.append("EXPLICIT_SEX")
    if "intimate_anatomy" in cats and "MINOR_SEXUAL" not in codes:
        codes.append("INTIMATE_ANATOMY")
    if "nudity" in cats and "MINOR_SEXUAL" not in codes:
        codes.append("NUDITY")
    if "graphic_violence" in cats:
        codes.append("GRAPHIC_VIOLENCE")
    codes.extend(_validate_reference(raw_ref, cats))
    findings = [asdict(_FINDINGS[code]) for code in dict.fromkeys(codes)]
    verdict = ("BLOCK" if any(f["severity"] == "block" for f in findings)
               else "REVIEW" if findings else "PASS_LOCAL")
    prompt_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    reference_hash = (raw_ref or {}).get("sha256", "")
    return {
        "schema": "dios.preflight.v1", "rule_version": RULE_VERSION,
        "verdict": verdict, "provider_approved": None,
        "predicted_provider_probability": None,
        "prediction_basis": "local transparent rules; no validated provider model",
        "prompt_sha256": prompt_hash, "reference_sha256": reference_hash,
        "categories": sorted(cats), "findings": findings,
        "can_submit_to_provider": verdict == "PASS_LOCAL",
        "notice": "Local assessment only. Provider moderation is independent and final.",
    }
