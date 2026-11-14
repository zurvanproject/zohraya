#!/usr/bin/env python3
"""Offline, evidence-labelled three-pass manuscript study adjunct.

A 'pass' contains all three stages: observe, geometry, revise. Completing
three *stages once* is not three passes. Nothing here reads an image, infers
an esoteric meaning, runs the VPS, or claims ritual mastery.
"""
import argparse
import hashlib
import json
from pathlib import Path

DEFAULT_PROTOCOL = Path(__file__).resolve().parents[1] / "docs" / "rituals" / "kavakeb_three_looks_v01.json"
STAGES = ("observe", "geometry", "revise")
REQUIRED = {
    "observe": "observations",
    "geometry": "geometric_relations",
    "revise": "supported_findings",
}
ALLOWED_MODES = {"source_guided", "context_assisted_textual", "independent_delayed"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _nonempty_strings(value):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(x, str) and bool(x.strip()) for x in value))


def _valid_pass(item, expected_number):
    if not isinstance(item, dict) or item.get("number") != expected_number:
        return False
    if item.get("mode") not in ALLOWED_MODES:
        return False
    stages = item.get("stages")
    if not isinstance(stages, dict) or list(stages) != list(STAGES):
        return False
    for stage, required in REQUIRED.items():
        data = stages[stage]
        if not isinstance(data, dict) or not _nonempty_strings(data.get(required)):
            return False
    revision = stages["revise"]
    if not _nonempty_strings(revision.get("uncertainties")):
        return False
    if not isinstance(item.get("independent_assessor"), bool):
        return False
    if not isinstance(item.get("measured_duration_seconds"), (int, float, type(None))) or isinstance(item.get("measured_duration_seconds"), bool):
        return False
    if item.get("measured_duration_seconds") is not None and item["measured_duration_seconds"] < 0:
        return False
    return True


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(session, protocol, source_pdf=None, guide_pdf=None):
    if session.get("schema") != "nasuraya/kavakeb-three-looks-session/1":
        raise ValueError("wrong session schema")
    if session.get("protocol_id") != protocol.get("id"):
        raise ValueError("wrong protocol ID")
    if session.get("source_page") not in protocol["source"]["original_pdf_pages"]:
        raise ValueError("unsupported original PDF page")
    if not isinstance(session.get("session_id"), str) or not session["session_id"].strip():
        raise ValueError("missing session ID")
    # Never promote a study adjunct to a mastered rite or claim physical effects.
    if session.get("mastered") is not False or session.get("embodied_or_supernatural_verified") is not False:
        raise ValueError("unsupported mastery/effects claim")
    if session.get("independent_delayed_recall_proven") is not False:
        raise ValueError("unsupported delayed recall claim")
    records = session.get("passes")
    if not isinstance(records, list):
        raise ValueError("passes must be a list")
    complete = 0
    for n, record in enumerate(records, 1):
        if _valid_pass(record, n):
            complete += 1
        else:
            break
    # Source hashes must match if supplied; a declared reference alone is not verification.
    source_checks = {}
    for key, path in (("original_pdf", source_pdf), ("illustrated_guide", guide_pdf)):
        if path is None:
            source_checks[key] = "NOT_CHECKED"
            continue
        expected = protocol["source"][key]["sha256"]
        if sha256_file(path) != expected:
            raise ValueError(f"{key} SHA-256 mismatch")
        source_checks[key] = "SHA256_MATCH"
    complete_session = complete >= protocol["minimum_complete_passes_per_session"]
    return {
        "session_id": session["session_id"],
        "ritual_slot": "auxiliary_study_after_four_guardians",
        "source_page": session["source_page"],
        "full_passes_completed": complete,
        "required_full_passes": protocol["minimum_complete_passes_per_session"],
        "session_complete_under_three_pass_rule": complete_session,
        "status": "COMPLETED_TEXTUAL" if complete_session else "IN_PROGRESS",
        "source_checks": source_checks,
        "mastered": False,
        "independent_delayed_recall_proven": False,
        "vps_execution_verified": False,
        "note": "Validation checks authored records and optional file hashes; it cannot verify manuscript reading quality, a physical practice, or actual elapsed time."
    }


def new_session(protocol, date, page, session_id):
    if page not in protocol["source"]["original_pdf_pages"]:
        raise ValueError("unsupported source page")
    return {
        "schema": "nasuraya/kavakeb-three-looks-session/1",
        "protocol_id": protocol["id"],
        "session_id": session_id,
        "date": date,
        "source_page": page,
        "mastered": False,
        "embodied_or_supernatural_verified": False,
        "independent_delayed_recall_proven": False,
        "passes": [],
        "instructions": "For each full pass add observe, geometry AND revise, in this order. Record evidence. Do not mark an unperformed pass complete."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an empty, non-overwriting session JSON")
    new.add_argument("--date", required=True)
    new.add_argument("--page", type=int, required=True)
    new.add_argument("--session-id", required=True)
    new.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("check", help="Validate a documented session")
    check.add_argument("--session", type=Path, required=True)
    check.add_argument("--source-pdf", type=Path)
    check.add_argument("--guide-pdf", type=Path)
    args = parser.parse_args()
    protocol = read_json(args.protocol)
    if args.command == "new":
        session = new_session(protocol, args.date, args.page, args.session_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as f:  # never overwrite
            json.dump(session, f, ensure_ascii=False, indent=2)
            f.write("\n")
        result = {"status": "CREATED_EMPTY", "output": str(args.output), "passes": 0}
    else:
        result = audit(read_json(args.session), protocol, args.source_pdf, args.guide_pdf)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
