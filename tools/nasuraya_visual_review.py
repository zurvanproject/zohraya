"""Human-review ledger for Nasuraya visual continuity (no fake AI perception).

A review form contains null scores until an actual reviewer supplies pass/fail.
Reports are local and include sample count, per-criterion denominators and
exact image hashes. A passed automated build never substitutes for human review.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from nasuraya_visual_gallery import check_raster

CRITERIA = (
    "face_identity_consistent",
    "exactly_two_horns",
    "one_tail_connected",
    "hands_anatomically_consistent",
    "feet_anatomically_consistent",
    "paper_visible_open",
    "persian_letter_readable",
)
HEX_SHA = re.compile(r"^[0-9a-f]{64}$")


def form(image_path: Path) -> dict:
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise ValueError("an existing nonempty image is required")
    check_raster(image_path)
    return {
        "schema": "nasuraya-visual-review-v1",
        "image_sha256": sha256(image_path.read_bytes()).hexdigest(),
        "reviewer": None,
        "reviewed_at_utc": None,
        "scores": {key: None for key in CRITERIA},
        "notes": "",
    }


def validate(doc: dict) -> tuple[str, bool]:
    if not isinstance(doc, dict) or doc.get("schema") != "nasuraya-visual-review-v1":
        raise ValueError("unsupported review schema")
    digest = doc.get("image_sha256")
    if not isinstance(digest, str) or not HEX_SHA.fullmatch(digest):
        raise ValueError("invalid image digest")
    scores = doc.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(CRITERIA):
        raise ValueError("missing or extra score fields")
    if any(value is not None and type(value) is not bool and value != "not_visible"
           for value in scores.values()):
        raise ValueError("scores must be true, false, not_visible or null")
    all_set = all(type(value) is bool or value == "not_visible" for value in scores.values())
    all_unset = all(value is None for value in scores.values())
    if not (all_set or all_unset):
        raise ValueError("partially completed reviews are not counted")
    reviewer = doc.get("reviewer")
    timestamp = doc.get("reviewed_at_utc")
    if all_set:
        if not isinstance(reviewer, str) or not (2 <= len(reviewer.strip()) <= 80):
            raise ValueError("completed reviews require reviewer label")
        if not isinstance(timestamp, str):
            raise ValueError("completed reviews require UTC timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("invalid review timestamp") from None
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("review timestamp must be UTC")
    else:
        if reviewer is not None or timestamp is not None:
            raise ValueError("pending reviews cannot claim a reviewer or date")
    notes = doc.get("notes")
    if not isinstance(notes, str) or len(notes) > 1000:
        raise ValueError("notes must be text of at most 1000 characters")
    return (digest, all_set)


def report(files: list[Path]) -> dict:
    seen = set()
    counts = {key: {"pass": 0, "fail": 0, "not_visible": 0} for key in CRITERIA}
    reviewed = 0
    pending = 0
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        digest, complete = validate(doc)
        if digest in seen:
            raise ValueError("duplicate image hash in review set")
        seen.add(digest)
        if not complete:
            pending += 1
            continue
        reviewed += 1
        for key, value in doc["scores"].items():
            counts[key]["not_visible" if value == "not_visible" else
                        "pass" if value else "fail"] += 1
    return {
        "schema": "nasuraya-visual-review-summary-v1",
        "sample_count": len(seen),
        "reviewed_count": reviewed,
        "pending_count": pending,
        "minimum_sample_size": 10,
        "sufficient_samples_for_comparison": reviewed >= 10,
        "scores": {
            key: {**value, "denominator": value["pass"] + value["fail"],
                  "pass_fraction": value["pass"] / (value["pass"] + value["fail"])
                                   if value["pass"] + value["fail"] else None}
            for key, value in counts.items()
        },
        "visual_review_automated": False,
        "reviewer_identity_verified": False,
        "approval_for_publication": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    f = sub.add_parser("form", help="Create an unfilled review form for one image")
    f.add_argument("--image", type=Path, required=True)
    f.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report", help="Aggregate filled reviews without inferring visual scores")
    r.add_argument("--reviews-dir", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.action == "form":
        result = form(args.image)
    else:
        if not args.reviews_dir.is_dir():
            raise SystemExit("reviews-dir must exist")
        files = sorted(args.reviews_dir.glob("*.json"))
        result = report(files)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({"action": args.action, "output": str(args.out),
                      "reviewed": result.get("reviewed_count", False)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
