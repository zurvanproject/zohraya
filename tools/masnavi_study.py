#!/usr/bin/env python3
"""Source-bounded Masnavi I study companion for Nasuraya. Offline, read-only.

This is a structured retrieval and self-questioning scaffold, NOT model training,
a live ritual, a source of operational instructions, or a capability grant.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "reading" / "masnavi_daftar1_study_v01.json"
STAGES = ("observe", "counterread", "revise")


def load(path=DATA):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "nasuraya/masnavi-daftar1-source-study/1":
        raise ValueError("Wrong study schema")
    if data.get("file_pdf_pages") != 192:
        raise ValueError("Source pagination changed")
    if any(data["training_status"].values()):
        raise ValueError("Unverified model or ritual achievement claim")
    motifs = data.get("motifs")
    if not isinstance(motifs, list) or len(motifs) != 14:
        raise ValueError("Expected 14 recorded study topics")
    seen = set()
    for item in motifs:
        if item["id"] in seen:
            raise ValueError("Duplicate motif")
        seen.add(item["id"])
        a, b = item["pdf_pages"]
        if not (isinstance(a, int) and isinstance(b, int) and 2 <= a <= b <= 192):
            raise ValueError("Invalid source page interval")
        if item.get("attribution") != "analysis_of_source_not_canonical_instruction":
            raise ValueError("Wrong attribution")
        if tuple(x.get("stage") for x in item.get("three_passes", [])) != STAGES:
            raise ValueError("Incomplete three-pass exercise")
        for field in ("source_observation", "question", "derived_application"):
            if not isinstance(item.get(field), str) or len(item[field]) < 18:
                raise ValueError("Missing bounded learning element")
    return data


def lesson(data, ident):
    found = next((x for x in data["motifs"] if x["id"] == ident), None)
    if found is None:
        raise ValueError("Unknown lesson ID")
    return {
        "schema": "nasuraya/masnavi-lesson/1",
        "source": "owner-provided Masnavi Daftar1 PDF",
        "source_pdf_pages": found["pdf_pages"],
        "topic": found["title"],
        "source_observation": found["source_observation"],
        "interpretation_only": found["derived_application"],
        "question": found["question"],
        "three_passes": found["three_passes"],
        "permission_granted": False,
        "model_weights_updated": False,
        "performance_verified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--lesson")
    parser.add_argument("--source", type=Path, default=DATA)
    args = parser.parse_args(argv)
    if args.list == bool(args.lesson):
        parser.error("choose exactly one of --list or --lesson")
    data = load(args.source)
    result = [{"id": x["id"], "title": x["title"], "pdf_pages": x["pdf_pages"]}
              for x in data["motifs"]] if args.list else lesson(data, args.lesson)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
