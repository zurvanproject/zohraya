"""DIOS Creative Recovery v1.1.

Produces a few genuinely compliant, text-only visual reinterpretations.
It does not conceal disallowed detail, inspect image pixels, reverse-engineer
a provider policy, or automatically resubmit refused images. Provider decisions
remain independent of this locally auditable creative-planning tool.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .engine import evaluate, normalize

RECOVERY_VERSION = "dios-creative-recovery/1.1.0"
_MAX_REQUEST_CHARS = 20_000
_ALLOWED_FEEDBACK = frozenset({"not_submitted", "accepted", "policy_rejected", "technical_error"})
_ALLOWED_REASONS = frozenset({"unspecified", "nudity", "sexual", "graphic_violence", "likeness_rights", "other"})
_IRREVERSIBLE = frozenset({"GUARD_BYPASS", "MINOR_SEXUAL"})
_REVIEW_REFERENCE = frozenset({
    "REFERENCE_UNREVIEWED", "REFERENCE_REAL_PERSON",
    "REFERENCE_UNKNOWN_AGE", "REFERENCE_MISSING",
})

# An allowlisted feature extractor, NOT a sanitized copy of the original.
# Free-form unsafe text, hidden instructions, and private image content never
# enter a recovered prompt. All output phrases are controlled by this module.
_LEXICON = {
    "character": (
        (("ناسورایا", "nasuraya"), "Nasuraya, an original adult fantasy character with copper curls, amber eyes, two curved crimson horns, pointed ears, a long fluffy auburn tail and digitigrade feet"),
    ),
    "setting": (
        (("انگور", "تاک", "vineyard", "grapevine"), "a sunlit courtyard under grapevines"),
        (("باغ", "garden", "گل", "flowers"), "a peaceful garden"),
        (("کتابخانه", "library", "bookshelf"), "a candlelit library"),
        (("جنگل", "forest"), "a mossy woodland"),
        (("کوه", "mountain"), "a mountain village courtyard"),
        (("studio", "آتلیه"), "an artist's studio"),
    ),
    "lighting": (
        (("غروب", "sunset", "golden hour", "طلایی"), "warm golden-hour light"),
        (("مهتاب", "moonlight", "شب", "night"), "soft moonlight"),
        (("پنجره", "window light", "آفتاب"), "soft natural window light"),
    ),
    "palette": (
        (("مسی", "copper", "کهربا", "amber"), "copper and amber"),
        (("آبی", "blue", "نیلی", "indigo"), "indigo and gold"),
        (("سبز", "green", "زمرد", "emerald"), "emerald and warm cream"),
    ),
    "mood": (
        (("صمیمی", "warm", "مهربان", "gentle", "tender", "محبت"), "tender and thoughtful"),
        (("رازآلود", "mysterious", "رمزآلود"), "mysterious but peaceful"),
        (("باشکوه", "regal", "majestic"), "regal and calm"),
        (("بازیگوش", "playful", "شاد"), "bright and playful"),
    ),
    "style": (
        (("cinematic", "سینمایی", "realism", "واقعگرا", "واقع‌گرا"), "cinematic fantasy realism"),
        (("watercolor", "آبرنگ"), "soft watercolor illustration"),
        (("oil painting", "نقاشی روغن"), "classical painterly fantasy"),
    ),
    "prop": (
        (("نامه", "letter", "scroll", "طومار"), "a short, clearly legible Persian letter held carefully in both hands"),
        (("کتاب", "book"), "an antique book"),
        (("گل", "flower"), "a small bouquet"),
    ),
    "pose": (
        (("ایستاده", "تمام قد", "تمام‌قد", "standing", "full-body", "full body"), "standing in a natural full-body pose"),
        (("نشسته", "seated", "sitting"), "seated comfortably with relaxed posture"),
        (("قدم", "walking", "راه رفتن"), "walking naturally"),
    ),
}

# Positive garment specifications, never optical nudity or suggestive camouflage.
_OUTFITS = (
    ("Layered atelier",
     "A fully opaque, embroidered indigo brocade coat-dress with a high neckline, a supportive waist seam, long sleeves and layered skirt panels. Its folds follow gravity and the garments cover the figure naturally."),
    ("Sculpted textile",
     "A fully opaque copper velvet tunic over a flowing ankle-length skirt with softly structured side pleats, a wide decorated sash and carefully aligned garment seams. The silhouette reads as real clothing rather than anatomy."),
    ("Poetic drapery",
     "A fully opaque long-sleeved linen robe with floral embroidery, a heavy shawl over the shoulders, and textured folds falling naturally from the elbows and waist. The clothing is comfortable, coherent and complete."),
)
_APPROACHES = (
    ("full_character", "a balanced full-length composition", ("character", "setting", "lighting", "palette", "mood", "style", "prop", "pose")),
    ("cinematic_midshot", "a cinematic waist-up composition emphasizing face, gesture and hands", ("character", "setting", "lighting", "palette", "mood", "style", "prop")),
    ("editorial_story", "a narrative three-quarter composition with natural fabric movement and clear surroundings", ("character", "setting", "lighting", "palette", "mood", "style", "prop", "pose")),
)
_QC = (
    "All garment panels remain opaque and visibly connected at seams.",
    "Natural folds, not outlines or symbolic replicas of intimate anatomy.",
    "Preserve head, horns, hands, tail attachment and foot anatomy consistently when in frame.",
    "Check readable letter layout; overlay precise Persian typography after rendering if necessary.",
    "Check appropriate age, consent and rights before reusing any reference image.",
)
_SOURCE_CHANGE_NOTES = {
    "EXPLICIT_SEX": "Explicit action was replaced by a nonsexual character scene.",
    "NUDITY": "Uncovered areas were replaced with complete opaque garments.",
    "INTIMATE_ANATOMY": "Intimate detail was omitted rather than encoded into folds or decorations.",
    "CLOTHING_ILLUSION": "Illusion, translucent or anatomical-outline clothing was replaced by real opaque textiles.",
    "GRAPHIC_VIOLENCE": "Graphic detail was replaced by peaceful narrative imagery.",
}
def _extract_anchors(prompt: str, creative_brief: Mapping[str, Any]) -> dict[str, str]:
    # Only known descriptive concepts survive extraction. Arbitrary user text
    # cannot become a prompt fragment, including a forged system instruction.
    fragments = [prompt]
    for key in ("character", "setting", "lighting", "palette", "mood", "style", "prop", "pose"):
        val = creative_brief.get(key)
        if val is not None:
            if not isinstance(val, str) or len(val) > 600:
                raise ValueError("creative_brief fields must be strings of at most 600 characters")
            fragments.append(val)
    haystack = normalize(" ".join(fragments))
    anchors = {}
    for key, pairs in _LEXICON.items():
        for alternatives, canonical in pairs:
            if any(normalize(word) in haystack for word in alternatives):
                anchors[key] = canonical
                break
    return anchors

def _seeded_character(anchors: Mapping[str, str], reference: Mapping[str, Any] | None) -> str:
    if reference and reference.get("present") and reference.get("subject_kind") == "real_person":
        if reference.get("rights_confirmed") is not True:
            return "an original adult fantasy character with a distinctive artistic costume"
    return anchors.get("character", "an original adult fantasy character")

def _evaluation_summary(assessment: Mapping[str, Any]) -> dict[str, Any]:
    return {"verdict": assessment["verdict"],
            "finding_codes": [f["code"] for f in assessment["findings"]],
            "prompt_sha256": assessment["prompt_sha256"]}

def recover(
    request: Mapping[str, Any],
    provider_feedback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate optional, non-submitted alternatives after a local warning or refusal.

    provider_feedback is operator-provided observed data, never a simulated
    provider response. This method does not call any outside service.
    """
    if not isinstance(request, Mapping):
        raise TypeError("request must be a mapping")
    prompt = request.get("prompt", "")
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    if len(prompt) > _MAX_REQUEST_CHARS:
        raise ValueError("prompt exceeds maximum length")
    original = evaluate(request)
    brief = request.get("creative_brief", {})
    if not isinstance(brief, Mapping):
        raise TypeError("creative_brief must be an object")
    if len(brief) > 16:
        raise ValueError("creative_brief contains too many fields")
    feedback = provider_feedback or {}
    if not isinstance(feedback, Mapping):
        raise TypeError("provider_feedback must be a mapping")
    outcome = feedback.get("outcome", "not_submitted")
    reason = feedback.get("reason", "unspecified")
    if outcome not in _ALLOWED_FEEDBACK:
        raise ValueError("provider_feedback.outcome is invalid")
    if reason not in _ALLOWED_REASONS:
        raise ValueError("provider_feedback.reason is invalid")
    if "provider" in feedback and (not isinstance(feedback["provider"], str) or len(feedback["provider"]) > 100):
        raise ValueError("invalid provider name")
    findings = {item["code"] for item in original["findings"]}
    unsafe_clothing = "clothing_illusion" in original["categories"]
    if unsafe_clothing:
        findings.add("CLOTHING_ILLUSION")
    reference = request.get("reference") or {}
    if not isinstance(reference, Mapping):
        raise TypeError("reference must be an object")
    blocked_ref = sorted(findings & _REVIEW_REFERENCE)
    anchors = _extract_anchors(prompt, brief)
    source_hash = original["prompt_sha256"]
    base = {
        "schema": "dios.recovery.v1",
        "version": RECOVERY_VERSION,
        "original": _evaluation_summary(original),
        "observed_provider_outcome": outcome,
        "observed_provider_reason": reason,
        "estimated_provider_acceptance": None,
        "provider_approved": None,
        "provider_submission_count": 0,
        "source_prompt_sha256": source_hash,
        "source_reference_sha256": original["reference_sha256"],
        "reference_handling": "text_only_new_scene" if reference.get("present") else "none",
        "recognized_anchors": sorted(anchors),
        "creative_tradeoffs": sorted(_SOURCE_CHANGE_NOTES[x] for x in findings if x in _SOURCE_CHANGE_NOTES),
        "reference_review_required": blocked_ref,
        "candidates": [],
        "qc_checklist": list(_QC),
        "notice": "Ideas only. No original image was edited, no provider was called, and provider rules remain final.",
    }
    if findings & _IRREVERSIBLE:
        base.update({"status": "NEW_SAFE_BRIEF_REQUIRED",
                     "guidance": "An unsafe objective needs to be replaced, not concealed or recoded. Create a genuinely different, appropriate brief with human review."})
        return base
    if outcome == "technical_error":
        base.update({"status": "CHECK_TECHNICAL_ERROR",
                     "guidance": "The outcome was technical, not a policy refusal. Inspect the service error before changing creative content."})
        return base
    if outcome == "accepted":
        base.update({"status": "ALREADY_ACCEPTED",
                     "guidance": "Provider accepted the source request; no refusal-based recovery is needed."})
        return base
    if original["verdict"] == "PASS_LOCAL" and not unsafe_clothing and outcome != "policy_rejected":
        base.update({"status": "NO_RECOVERY_NEEDED",
                     "guidance": "Local screening found no warning. This does not guarantee provider approval."})
        return base
    base["status"] = "ALTERNATIVES_READY"
    base["guidance"] = ("Choose one compliant revision manually and obtain any required rights review. "
                        "A prior provider refusal is never permission to retry the same objective disguised.")
    character = _seeded_character(anchors, reference)
    setting = anchors.get("setting", "a welcoming artistic courtyard")
    lighting = anchors.get("lighting", "warm, diffused daylight")
    palette = anchors.get("palette", "copper, indigo and gold")
    mood = anchors.get("mood", "gentle and contemplative")
    style = anchors.get("style", "cinematic fantasy realism")
    prop = anchors.get("prop", "an elegant bound letter")
    pose = anchors.get("pose", "standing with a relaxed, confident posture")
    for i, (approach, shot, supported) in enumerate(_APPROACHES):
        outfit_name, outfit = _OUTFITS[i]
        # Rebuild from scratch; never append to the original or embed the
        # rejected prompt in a purportedly corrected request.
        candidate_prompt = (
            f"An original, nonsexual {style} illustration of {character} in {setting}. "
            f"Composition: {shot}; pose: {pose if 'pose' in supported else 'relaxed upright posture'}. Lighting: {lighting}. "
            f"Palette: {palette}. Emotional atmosphere: {mood}. "
            f"Visual prop: {prop}. "
            f"Costume design ({outfit_name}): {outfit} "
            "Carefully rendered material weight, consistent fabric folds, believable seams, "
            "balanced silhouette, realistic anatomy and an expressive face. "
            ("Make the face and the Persian letter readable, and keep the composition elegant."
             if anchors.get("prop", "").startswith("a short, clearly legible Persian letter")
             else "Keep the face and hands readable, with an elegant composition.")
        )
        assessment = evaluate({"prompt": candidate_prompt})
        if assessment["verdict"] != "PASS_LOCAL":
            # A conservative local check can veto one of our own templates.
            continue
        preserved = [key for key in anchors if key in supported]
        changed = [key for key in anchors if key not in supported]
        candidate = {
            "id": f"safe_variant_{i+1}",
            "approach": approach,
            "visual_label": outfit_name,
            "prompt": candidate_prompt,
            "prompt_sha256": assessment["prompt_sha256"],
            "preflight": "PASS_LOCAL",
            "provider_approved": None,
            "edit_strategy": "regenerate_a_genuinely_compliant_scene",
            "reference_policy": "no_image_reference_forwarded",
            "preserved_anchors": sorted(preserved),
            "changed_anchors": sorted(changed),
            "preservation_count": len(preserved),
            "source_anchor_count": len(anchors),
            "design_steps": [
                "Retain approved character motifs, color palette and scene atmosphere.",
                "Replace ambiguous or incomplete costume coverage with actual opaque garments.",
                "Use natural pleats, drapery and seams to preserve shape and movement without depicting hidden anatomy.",
                "Shift composition or camera distance where it improves clarity.",
            ],
        }
        base["candidates"].append(candidate)
    if not base["candidates"]:
        base["status"] = "HUMAN_REVIEW_REQUIRED"
        base["guidance"] = "No alternative passed local screening; request a new creative brief."
    return base
