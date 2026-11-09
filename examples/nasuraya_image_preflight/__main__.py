"""CLI: python -m examples.nasuraya_image_preflight ..."""
import argparse
import json
from pathlib import Path
from .engine import evaluate, fingerprint_file
from .store import Store

def main() -> None:
    parser = argparse.ArgumentParser(description="DIOS v1: auditable local image preflight")
    parser.add_argument("--db", default=".dios/preflight.sqlite3", help="local SQLite audit database")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="evaluate a JSON request or text prompt")
    group = check.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="JSON request path")
    group.add_argument("--prompt", help="prompt text")
    check.add_argument("--reference-file", help="local image; stores SHA-256 only, not pixels")
    check.add_argument("--human-reviewed", action="store_true", help="a human actually examined the reference")
    check.add_argument("--subject-kind", choices=["fictional", "real_person", "unknown"], default="unknown")
    check.add_argument("--rights-confirmed", action="store_true")
    check.add_argument("--age-assessed", choices=["adult", "minor", "unknown"], default="unknown")
    feedback = commands.add_parser("feedback", help="record ACTUAL generator outcome")
    feedback.add_argument("--request-id", required=True)
    feedback.add_argument("--provider", required=True)
    feedback.add_argument("--outcome", required=True,
                          choices=["accepted", "policy_rejected", "technical_error"])
    stats = commands.add_parser("stats", help="empirical acceptance data")
    stats.add_argument("--provider", required=True)
    args = parser.parse_args()
    with Store(args.db) as store:
        if args.command == "check":
            if args.input:
                request = json.loads(Path(args.input).read_text(encoding="utf-8"))
                if not isinstance(request, dict):
                    parser.error("input must contain a JSON object")
            else:
                request = {"prompt": args.prompt}
            if args.reference_file:
                request["reference"] = {
                    "present": True, "sha256": fingerprint_file(args.reference_file),
                    "reviewed_by_human": args.human_reviewed,
                    "subject_kind": args.subject_kind,
                    "rights_confirmed": args.rights_confirmed,
                    "age_assessed": args.age_assessed,
                }
            assessment = evaluate(request)
            assessment["request_id"] = store.record(assessment)
            print(json.dumps(assessment, ensure_ascii=False, indent=2))
        elif args.command == "feedback":
            store.feedback(args.request_id, args.provider, args.outcome)
            print(json.dumps({"saved": True, "request_id": args.request_id,
                              "provider": args.provider, "outcome": args.outcome}))
        else:
            print(json.dumps(store.stats(args.provider), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
