"""Fail-closed reference and anatomy review gate for Nasuraya image files.

Only a genuine decoded candidate image and explicitly reviewed observations can
PASS. This does not detect fingers automatically or prove generator conditioning.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from PIL import Image, UnidentifiedImageError

EXPECTED = {"right_hand": 5, "left_hand": 5, "right_foot": 3, "left_foot": 3}
MAX_BYTES = 30_000_000
MAX_PIXELS = 32_000_000


def image_info(path: Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("IMAGE_MISSING")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("INVALID_IMAGE_SIZE")
    try:
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("INVALID_IMAGE_FORMAT")
            kind = image.format
            width, height = image.size
            if min(width, height) < 64 or width * height > MAX_PIXELS:
                raise ValueError("INVALID_IMAGE_DIMENSIONS")
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("INVALID_IMAGE_CONTENT") from exc
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"sha256": digest, "dimensions": [width, height], "format": kind}


def box_valid(b) -> bool:
    return (isinstance(b, (list, tuple)) and len(b) == 4
            and all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in b)
            and b[0] < b[2] and b[1] < b[3])


def inspect_candidate(reference: Path, expected_reference_sha: str,
                      candidate: Path, review: dict | None = None) -> dict:
    """PASS is manual appearance review ONLY. Generator provenance is unverified."""
    try:
        ref = image_info(reference)
        if ref["sha256"] != expected_reference_sha:
            return {"verdict": "FAIL", "reason": "REFERENCE_HASH_MISMATCH"}
        generated = image_info(candidate)
    except ValueError as error:
        return {"verdict": "FAIL", "reason": str(error)}
    if not isinstance(review, dict):
        review = {}
    header = review.get("review")
    valid_review = (
        isinstance(header, dict)
        and header.get("method") == "manual_image_review"
        and isinstance(header.get("reviewer_id"), str) and bool(header["reviewer_id"].strip())
        and header.get("reference_sha256") == ref["sha256"]
        and header.get("candidate_sha256") == generated["sha256"]
    )
    regions = review.get("anatomy", {}) if valid_review else {}
    face = review.get("face", {}) if valid_review else {}
    checks = []
    for region, count in EXPECTED.items():
        data = regions.get(region) if isinstance(regions, dict) else None
        bbox = data.get("bbox") if isinstance(data, dict) else None
        if (not valid_review or not isinstance(data, dict) or not box_valid(bbox)
                or data.get("visible") is not True or data.get("occluded") is not False
                or min(bbox[0], bbox[1], 1-bbox[2], 1-bbox[3]) < .012
                or type(data.get("detected_digits")) is not int
                or type(data.get("fused_digits")) is not bool):
            verdict = "UNVERIFIED"
        elif data["detected_digits"] != count or data["fused_digits"]:
            verdict = "FAIL"
        else:
            verdict = "PASS"
        checks.append({"region": region, "expected": count, "verdict": verdict,
                       "roi_bbox": bbox if box_valid(bbox) else None})
    if (not valid_review or not isinstance(face, dict) or not box_valid(face.get("bbox"))
            or face.get("visible") is not True):
        face_verdict = "UNVERIFIED"
    elif (face.get("scar_on_left") is True
          or face.get("matches_reference") is False
          or face.get("scar_on_right") is False):
        face_verdict = "FAIL"
    elif (face.get("matches_reference") is True
          and face.get("scar_on_right") is True
          and face.get("scar_on_left") is False):
        face_verdict = "PASS"
    else:
        face_verdict = "UNVERIFIED"
    outcomes = [x["verdict"] for x in checks] + [face_verdict]
    verdict = "FAIL" if "FAIL" in outcomes else ("UNVERIFIED" if "UNVERIFIED" in outcomes else "PASS")
    return {"verdict": verdict, "reference_file_sha256": ref["sha256"],
            "candidate_file_sha256": generated["sha256"],
            "checks": checks, "face_verdict": face_verdict,
            "review_method": "candidate_bound_manual_attestation" if valid_review else "UNVERIFIED",
            "reference_used_by_generator": "UNVERIFIED",
            "actual_image_edit_performed": False,
            "physical_reference_photo_stored_in_repo": False,
            "note": "Manual appearance gate only; not automated digit or face recognition."}
