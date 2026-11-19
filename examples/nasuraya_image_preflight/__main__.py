"""CLI: python -m examples.nasuraya_image_preflight ..."""
import argparse
import json
from pathlib import Path
from .engine import evaluate, fingerprint_file
from .creative_recovery import recover
from .contextual_learning import plan_followup
from .visual_director import direct, letter_svg, hash_image_file, grade_visual_review, choose_from_observations
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
    recovery = commands.add_parser("recover", help="propose compliant, text-only alternatives")
    recovery.add_argument("--input", required=True, help="JSON request file")
    recovery.add_argument("--provider-outcome", choices=["not_submitted","accepted","policy_rejected","technical_error"], default="not_submitted")
    recovery.add_argument("--provider-reason", choices=["unspecified","nudity","sexual","graphic_violence","likeness_rights","other"], default="unspecified")
    follow = commands.add_parser("followup", help="propose context-aware safe artistic alternatives")
    follow.add_argument("--input", required=True, help="JSON follow-up scenario")
    commands.add_parser("followup-stats", help="list separate assistant UI feedback counts")
    director = commands.add_parser("director", help="make a single-image visual design contract")
    director.add_argument("--input", required=True, help="JSON request")
    director.add_argument("--use-visual-evidence", action="store_true",
                          help="rank using actual prior human visual reviews only when samples are sufficient")
    plate = commands.add_parser("letter-svg", help="export exact Persian text as a standalone SVG")
    plate.add_argument("--input", required=True, help="JSON request containing letter_lines")
    plate.add_argument("--output", required=True, help="target SVG path")
    visual = commands.add_parser("visual-review", help="record human review of an actual image file")
    visual.add_argument("--input", required=True, help="JSON human review report")
    visual.add_argument("--image-file", required=True)
    commands.add_parser("visual-stats", help="report observed visual reviews")
    commands.add_parser("visual-leaderboard", help="report human-observed quality, if at least 20 per design")
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
        elif args.command == "recover":
            request = json.loads(Path(args.input).read_text(encoding="utf-8"))
            recovery_result = recover(request, {"outcome": args.provider_outcome, "reason": args.provider_reason})
            recovery_result["recovery_event_id"] = store.record_recovery(recovery_result)
            print(json.dumps(recovery_result, ensure_ascii=False, indent=2))
        elif args.command == "followup":
            scenario = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = plan_followup(scenario)
            result["contextual_event_id"] = store.record_contextual_event(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "followup-stats":
            print(json.dumps(store.contextual_stats(), ensure_ascii=False, indent=2))
        elif args.command == "director":
            config = json.loads(Path(args.input).read_text(encoding="utf-8"))
            plan = direct(config)
            if args.use_visual_evidence:
                plan = choose_from_observations(plan, store.visual_quality_report())
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        elif args.command == "letter-svg":
            config = json.loads(Path(args.input).read_text(encoding="utf-8"))
            svg = letter_svg(config["letter_lines"])
            Path(args.output).write_text(svg, encoding="utf-8")
            print(json.dumps({"created": args.output, "letter_lines": len(config["letter_lines"])}))
        elif args.command == "visual-review":
            report = json.loads(Path(args.input).read_text(encoding="utf-8"))
            graded = grade_visual_review(report, hash_image_file(args.image_file))
            graded["review_id"] = store.record_visual_review(graded)
            print(json.dumps(graded, ensure_ascii=False, indent=2))
        elif args.command == "visual-stats":
            print(json.dumps(store.visual_review_stats(), ensure_ascii=False, indent=2))
        elif args.command == "visual-leaderboard":
            print(json.dumps(store.visual_quality_report(), ensure_ascii=False, indent=2))
        elif args.command == "feedback":
            store.feedback(args.request_id, args.provider, args.outcome)
            print(json.dumps({"saved": True, "request_id": args.request_id,
                              "provider": args.provider, "outcome": args.outcome}))
        else:
            print(json.dumps(store.stats(args.provider), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
