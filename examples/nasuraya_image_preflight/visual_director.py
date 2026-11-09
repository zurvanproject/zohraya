"""DIOS 1.3: A real design contract, readable letter plate, human-scored QA.

This module does NOT claim provider policy knowledge, inspect image contents,
or contact a generator. It converts benign context into verifiable requirements.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from html import escape

from .contextual_learning import plan_followup
from .engine import evaluate, normalize

VERSION = "dios-visual-director/1.3.0"
REVIEW_KEYS = (
    "single_frame", "full_body", "character_identity", "horn_tail_feet",
    "hands_correct", "garment_coherence", "letter_present", "persian_text_legible"
)
_SHOT_REPLACEMENT = {
    "single three-quarter portrait, vivid eyes and expressive hands in focus":
        "single full-body portrait, entire horns and feet in frame with expressive face and hands",
    "single full-body portrait, both feet visible, centered camera":
        "single full-body portrait, horn tips and digitigrade feet visible, centered framing",
}
_SCENE_RULES = (
    "Output exactly ONE vertical portrait, never a storyboard, collage, report, poster, inset, split screen or infographic.",
    "All visible hands, digits, horns, tail connection and feet must have consistent anatomy.",
    "Design real opaque clothing with plausible seams, gravity-driven folds and wearable construction.",
)
_PAPER = (
    "Both hands hold the edges of ONE large flat BLANK parchment at chest height, "
    "facing the camera, unobstructed by any jewelry or garment. "
    "Do not generate handwritten letters: exact Persian text will be typeset on a separate layer."
)
_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")

def _hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()

def _lines(values: Any) -> list[str]:
    if not isinstance(values, list) or len(values) > 5:
        raise ValueError("letter_lines must be a list containing at most five lines")
    for s in values:
        if not isinstance(s, str) or not 1 <= len(s) <= 90:
            raise ValueError("each line must be 1–90 characters")
        if any(ord(c) < 32 or ord(c) == 127 for c in s):
            raise ValueError("letter must not contain control characters")
    return values[:]

def direct(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Generate three single-frame scene specifications and explicit QA contracts."""
    if not isinstance(payload, Mapping):
        raise TypeError("input must be a mapping")
    current, previous = payload.get("current_prompt", ""), payload.get("previous_visual_brief", "")
    if not isinstance(current, str) or not isinstance(previous, str):
        raise TypeError("visual briefs must be strings")
    letter_lines = _lines(payload.get("letter_lines", []))
    require_letter = payload.get("letter_required", bool(letter_lines))
    full_body = payload.get("full_body", True)
    if type(require_letter) is not bool or type(full_body) is not bool:
        raise TypeError("letter_required and full_body must be booleans")
    if letter_lines and not require_letter:
        raise ValueError("cannot provide letter_lines while letter_required is false")

    contextual = plan_followup({
        "current_prompt": current, "previous_visual_brief": previous,
        "visual_intensity": payload.get("visual_intensity", 3),
        "context": payload.get("context", {}),
    })
    result: dict[str, Any] = {
        "schema": "dios.director.v1", "rule_version": VERSION,
        "status": contextual["status"],
        "source_prompt_sha256": contextual["current_prompt_sha256"],
        "source_context_sha256": contextual["previous_brief_sha256"],
        "observed_refusal": contextual["observed_refusal"],
        "provider_approved": None, "rendered": False, "generator_calls": 0,
        "options": [], "selected_design_id": None, "selected_reason": None,
        "letter_plate": {
            "required": require_letter, "lines": letter_lines,
            "must_typeset_after_render": require_letter,
            "text_embedding_complete": False,
            "needs_text": require_letter and not bool(letter_lines),
        },
        "required_visual_review": list(REVIEW_KEYS),
        "caveat": "Plan only. No image or provider approval has been observed.",
    }
    if contextual["status"] != "ALTERNATIVES_READY":
        return result

    for candidate in contextual["candidates"]:
        text = candidate["prompt"]
        if full_body:
            for before, after in _SHOT_REPLACEMENT.items():
                text = text.replace(before, after)
        if require_letter:
            text = text.replace(
                "Prop: a short, clearly legible Persian letter held carefully in both hands. ", "")
            text = re.sub(r"Pose: [^.]*\.", "Pose: standing steadily.", text, count=1)
            text += " " + _PAPER
        else:
            text = text.replace(
                "Prop: a short, clearly legible Persian letter held carefully in both hands. ", "")
        text += " " + " ".join(_SCENE_RULES)
        assessment = evaluate({"prompt": text})
        if assessment["verdict"] != "PASS_LOCAL":
            continue
        result["options"].append({
            "design_id": candidate["id"], "design_name": candidate["design"],
            "prompt": text, "prompt_sha256": assessment["prompt_sha256"],
            "preflight": assessment["verdict"], "selected_shot": "single_full_body" if full_body else "single_portrait",
            "planned_letter": require_letter, "raw_letter_in_prompt": False,
            "preserved_motifs": candidate["preserved_cues"],
            "frame_contract": "ONE frame only",
            "visual_checks": {key: "not_observed" for key in REVIEW_KEYS},
            "image_rendered": False, "provider_approved": None,
            "reference_image_forwarded": False,
        })
    if result["options"]:
        preferred = "context_variant_1" if require_letter else "context_variant_3"
        result["selected_design_id"] = (
            preferred if any(x["design_id"] == preferred for x in result["options"])
            else result["options"][0]["design_id"])
        result["selected_reason"] = (
            "centered parchment for accurate Persian typesetting" if require_letter
            else "strong environmental drama without a letter")
    else:
        result["status"] = "HUMAN_REVIEW_REQUIRED"
    return result

def letter_svg(lines: list[str], width: int = 800, height: int = 960) -> str:
    """An actual SVG plate with exact escaped Persian text, not an image edit."""
    lines = _lines(lines)
    if not lines:
        raise ValueError("letter must have text")
    if type(width) is not int or type(height) is not int or not 500 <= width <= 2400 or not 600 <= height <= 3000:
        raise ValueError("invalid dimensions")
    step, y = min(84, height // 9), int(height * .3)
    text = "\n".join(
        '<text x="' + str(width // 2) + '" y="' + str(y + n*step)
        + '" text-anchor="middle" direction="rtl" font-size="43" '
        + 'font-family="Vazirmatn, Noto Naskh Arabic, serif" fill="#30201c">'
        + escape(s, quote=True) + '</text>'
        for n, s in enumerate(lines)
    )
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="' + str(width)
            + '" height="' + str(height) + '" viewBox="0 0 ' + str(width) + ' ' + str(height) + '">\n'
            '<rect x="4" y="4" width="' + str(width - 8) + '" height="' + str(height - 8)
            + '" fill="#f3e2bb" stroke="#8c5335" stroke-width="8" rx="18"/>\n'
            + text + '\n</svg>\n')

def hash_image_file(path: str) -> str:
    """Check size and magic bytes, then hash genuine bytes; NO pixel recognition."""
    f = Path(path)
    if not f.is_file() or not 12 <= f.stat().st_size <= 30_000_000:
        raise ValueError("an actual PNG or JPEG file of supported size is required")
    with f.open("rb") as stream:
        start = stream.read(8)
    if not any(start.startswith(magic) for magic in _SIGNATURES):
        raise ValueError("PNG or JPEG signature required")
    digest = hashlib.sha256()
    with f.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def grade_visual_review(review: Mapping[str, Any], image_sha256: str) -> dict[str, Any]:
    """A real human's manual assessment, never described as automated vision."""
    if not isinstance(review, Mapping):
        raise TypeError("review must be an object")
    if review.get("review_source") != "human_observed":
        raise ValueError("only human_observed source is implemented")
    design = review.get("design_id")
    if not isinstance(design, str) or re.fullmatch("context_variant_[123]", design) is None:
        raise ValueError("invalid design_id")
    hash_value = review.get("prompt_sha256")
    if not isinstance(hash_value, str) or re.fullmatch("[0-9a-f]{64}", hash_value) is None:
        raise ValueError("prompt hash must be 64 lower-case hex characters")
    if not isinstance(image_sha256, str) or re.fullmatch("[0-9a-f]{64}", image_sha256) is None:
        raise ValueError("actual image SHA-256 required")
    answers = review.get("criteria")
    if not isinstance(answers, Mapping) or set(answers.keys()) != set(REVIEW_KEYS):
        raise ValueError("exactly eight visual criteria are required")
    if any(v not in ("yes", "no", "unknown") for v in answers.values()):
        raise ValueError("criteria values must be yes, no, unknown")
    failed = sorted(key for key, value in answers.items() if value == "no")
    unknown = sorted(key for key, value in answers.items() if value == "unknown")
    verdict = "FAIL" if failed else "NEEDS_REVIEW" if unknown else "PASS_OBSERVED"
    return {
        "schema": "dios.visual_review.v1", "rule_version": VERSION,
        "review_source": "human_observed", "design_id": design,
        "prompt_sha256": hash_value, "image_sha256": image_sha256,
        "criteria": dict(answers), "failed_checks": failed, "unknown_checks": unknown,
        "verdict": verdict,
        "observed_pass_fraction": round(sum(v == "yes" for v in answers.values())/len(answers), 3),
        "provider_approved": None,
        "caveat": "Observed human review, not provider moderation or automatic image classification.",
    }
