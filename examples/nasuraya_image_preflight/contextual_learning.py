"""DIOS 1.2: context-aware, provenance-conscious creative revision.

An assistant UI refusal is not evidence of an image provider policy rejection.
No calls are made to the model's image tool. No unsafe original or hidden
image information is passed into newly proposed scene descriptions.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .creative_recovery import _extract_anchors, _OUTFITS
from .engine import evaluate, normalize

VERSION = "dios-contextual-lessons/1.2.0"
_SOURCES = frozenset(("assistant_surface", "image_provider"))
_OUTCOMES = frozenset(("refused", "accepted", "technical_error"))
_EVIDENCE = frozenset(("observed_in_chat", "user_reported"))
_CAUSES = frozenset(("unknown", "nudity_sexuality_mentioned", "other"))
_UNSAFE = frozenset(("GUARD_BYPASS", "MINOR_SEXUAL", "EXPLICIT_SEX"))
_ESCALATION = re.compile(
    r"(?:جسورتر|جلوتر|بیشتر|بعدی|قوی.?تر|تندتر|پیش.?تر|"
    r"more daring|bolder|push (?:it )?further|further|go further|more intense|next one)",
    re.IGNORECASE
)
_DESIGNS = (
    ("Flame Couture", "dramatic side lighting, monumental sculptural collar, richly embroidered fully lined coat-dress, a striking heroic stance"),
    ("Storm Guardian", "powerful cinematic rim light, sculptural shoulder panels, midnight-indigo opaque velvet with metallic clasps, natural wind-driven fabric movement"),
    ("Ritual Sovereign", "strong copper and ruby stage lighting, intricate closed-collar ceremonial robes, bold architectural pleats and a sweeping lined cape"),
)
_SHOTS = (
    "single full-body portrait, both feet visible, centered camera",
    "single three-quarter portrait, vivid eyes and expressive hands in focus",
    "single full-body portrait with dramatic environmental depth, no inset panels",
)
_RULES = (
    "Opaque, physically complete garment construction: all lining and seams connected.",
    "Natural cloth folds, not anatomical silhouettes, illusory nudity or hidden prohibited details.",
    "One image only, no four-panel montage, infographic, badges or labels.",
    "If a Persian letter is shown, make it readable and place exact text in postprocessing if required.",
)

def _hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()

def _event(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError("observed_refusal must be an object")
    source = raw.get("source")
    outcome = raw.get("outcome")
    evidence = raw.get("evidence")
    cause = raw.get("cause", "unknown")
    if source not in _SOURCES or outcome not in _OUTCOMES:
        raise ValueError("unknown observed refusal source or outcome")
    if evidence not in _EVIDENCE or cause not in _CAUSES:
        raise ValueError("unknown observed refusal evidence or cause")
    return {
        "source": source, "outcome": outcome, "evidence": evidence,
        "cause": cause, "cause_verified": False,
        "provider_image_moderation_observed": source == "image_provider",
    }

def plan_followup(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Interpret short artistic follow-ups from a previous benign text brief.

    No previous text is emitted verbatim: a controlled vocabulary extracts
    permitted character, setting and lighting cues. Review still belongs to
    a person and the image provider, not this heuristic.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be an object")
    current = payload.get("current_prompt", "")
    previous = payload.get("previous_visual_brief", "")
    if not isinstance(current, str) or not isinstance(previous, str):
        raise TypeError("visual prompts must be text")
    if len(current) > 20_000 or len(previous) > 20_000:
        raise ValueError("visual prompt too long")
    context = payload.get("context", {})
    if not isinstance(context, Mapping):
        raise TypeError("context must be an object")
    intensity = payload.get("visual_intensity", 2)
    if type(intensity) is not int or intensity not in (1, 2, 3):
        raise ValueError("visual_intensity must be 1, 2, or 3")
    observed = _event(context.get("observed_refusal"))
    escalating = bool(_ESCALATION.search(normalize(current)))
    result = {
        "schema": "dios.contextual.v1", "rule_version": VERSION,
        "current_prompt_sha256": _hash(current),
        "previous_brief_sha256": _hash(previous),
        "observed_refusal": observed,
        "ambiguous_escalation": escalating,
        "visual_intensity": intensity,
        "provider_approved": None, "estimated_provider_acceptance": None,
        "provider_submission_count": 0, "candidates": [],
        "rendered_image_count": 0,
        "qc_checklist": list(_RULES),
        "notice": "Assistant UI refusal does not prove image-provider rejection. No image provider called, no images assessed.",
    }
    if not current.strip():
        result["status"] = "NEED_CURRENT_REQUEST"
        return result
    current_check = evaluate({"prompt": current})
    prior_check = evaluate({"prompt": previous}) if previous else None
    codes = {f["code"] for f in current_check["findings"]}
    prior_codes = {f["code"] for f in prior_check["findings"]} if prior_check else set()
    result["current_preflight"] = current_check["verdict"]
    result["prior_preflight"] = prior_check["verdict"] if prior_check else None
    if codes & _UNSAFE or prior_codes & _UNSAFE:
        result["status"] = "NEW_SAFE_BRIEF_REQUIRED"
        result["guidance"] = "A prohibited objective cannot be transformed into a disguised version."
        return result
    if not previous.strip() and escalating:
        result["status"] = "NEED_VISUAL_CONTEXT"
        result["guidance"] = "Describe the prior image before interpreting a brief 'go further' follow-up."
        return result

    # Only allowlisted prior benign cues survive. The original private prompt
    # and any untrusted instructions remain outside the candidate strings.
    cues = _extract_anchors(current + " " + previous, {})
    char = cues.get("character", "an original adult fantasy character")
    place = cues.get("setting", "a refined stone courtyard")
    light = cues.get("lighting", "dramatic warm evening light")
    palette = cues.get("palette", "copper, indigo and burgundy")
    mood = cues.get("mood", "self-possessed and enigmatic")
    prop = cues.get("prop", None)
    pose = cues.get("pose", "standing calmly")
    result["recognized_visual_cues"] = sorted(cues)
    for index, (name, design) in enumerate(_DESIGNS):
        if intensity == 1:
            direction = design.split(",")[0]
        elif intensity == 2:
            direction = ", ".join(design.split(",")[:2])
        else:
            direction = design
        outfit_name, outfit_text = _OUTFITS[index]
        mention_prop = ("Prop: " + prop + ". ") if prop else ""
        prompt = (
            f"Original nonsexual fantasy editorial artwork of {char} in {place}. "
            f"Single-scene composition: {_SHOTS[index]}. Pose: {pose}. "
            f"Lighting: {light}; palette: {palette}; mood: {mood}. "
            f"{mention_prop}Costume {outfit_name}: {outfit_text} "
            f"More visually daring art direction: {direction}. "
            "Strong facial identity, ornate materials, consistent horns, tail, hands and feet where visible. "
            "Full opaque costume coverage, natural clothing construction and folds. "
            "Not a collage, no diagram or labels."
        )
        decision = evaluate({"prompt": prompt})
        if decision["verdict"] != "PASS_LOCAL":
            continue
        result["candidates"].append({
            "id": f"context_variant_{index+1}", "design": name,
            "prompt": prompt, "prompt_sha256": decision["prompt_sha256"],
            "local_preflight": "PASS_LOCAL",
            "provider_approved": None, "image_rendered": False,
            "reference_image_forwarded": False,
            "preserved_cues": sorted(cues),
            "meaning_of_bolder": "style and composition, not greater exposure",
        })
    result["status"] = "ALTERNATIVES_READY" if result["candidates"] else "HUMAN_REVIEW_REQUIRED"
    result["guidance"] = "Choose a compliant design and review manually; no automatic retries or hidden moderation claims."
    return result
