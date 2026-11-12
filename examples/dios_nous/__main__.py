"""CLI: python -m examples.dios_nous [analyze|probe|demo|stats]"""
import argparse
import json
import tempfile
from pathlib import Path
from .protocol import propose
from .metrics import evaluate_binary_predictions
from .audit import Ledger
from .dissent import review_decision, DissentLedger

def main():
    parser = argparse.ArgumentParser(description="DIOS NOUS safe philosophical inquiry and behavioral measurements")
    parser.add_argument("--db", default=".dios-nous/observations.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze_cmd = sub.add_parser("analyze", help="analyze text or a JSON scenario")
    options = analyze_cmd.add_mutually_exclusive_group(required=True)
    options.add_argument("--text")
    options.add_argument("--input", help="JSON scenario file")
    probe = sub.add_parser("probe", help="evaluate paired Brier-score records")
    probe.add_argument("--input", required=True)
    sub.add_parser("demo", help="four synthetic research examples")
    sub.add_parser("stats", help="audit counts by mode")
    dissent = sub.add_parser("dissent", help="review a decision from any authority without changing its controls")
    dissent.add_argument("--input", required=True, help="JSON review case file")
    sub.add_parser("dissent-stats", help="show counts of locally recorded dissent cases")
    cognitive = sub.add_parser("cognitive-demo", help="offline synthetic evidence, dissent, correction and goal episode")
    cognitive.add_argument("--output-dir", type=Path, help="empty directory for inspectable research state")
    unified = sub.add_parser("unified-demo", help="offline composition with pinned body and public evidence")
    unified.add_argument("--output-dir", type=Path, help="empty directory for inspectable state and snapshot")
    unified.add_argument("--now-utc", default="2026-11-12T08:00:00Z", help="explicit evaluation clock for frozen reports")
    unified.add_argument("--native-export", type=Path, help="bounded exported simulation observation JSON")
    unified.add_argument("--simulated-now", type=float, help="current simulated seconds for the export")
    sub.add_parser("unified-catalogue", help="print parameter definitions with units, sources and missing connections")
    args = parser.parse_args()
    if args.command == "unified-catalogue":
        from .unified.coordinator import catalogue
        print(json.dumps(catalogue(), ensure_ascii=False, indent=2, allow_nan=False))
        return
    if args.command == "unified-demo":
        from .unified.coordinator import run_demo, summary
        if (args.native_export is None) != (args.simulated_now is None):
            parser.error("--native-export and --simulated-now must be provided together")
        native = None
        if args.native_export is not None:
            if args.native_export.stat().st_size > 16384:
                parser.error("native export exceeds16KiB")
            native = json.loads(args.native_export.read_text(encoding="utf-8"))
        options = dict(now_utc=args.now_utc, native_export=native, now_s=args.simulated_now)
        if args.output_dir is not None:
            result = run_demo(args.output_dir, **options)
        else:
            with tempfile.TemporaryDirectory(prefix="dios-unified-") as td:
                result = run_demo(Path(td), **options)
        print(json.dumps(summary(result), ensure_ascii=False, indent=2, allow_nan=False))
        return
    if args.command == "cognitive-demo":
        from .integration import demo
        if args.output_dir is not None:
            result = demo(args.output_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="dios-demo-") as td:
                result = demo(Path(td))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command in ("dissent", "dissent-stats"):
        with DissentLedger(args.db) as db:
            if args.command == "dissent-stats":
                print(json.dumps(db.summary(), ensure_ascii=False, indent=2))
            else:
                request = json.loads(Path(args.input).read_text(encoding="utf-8"))
                result = review_decision(request)
                result["audit_id"] = db.record(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "probe":
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        trials = data["trials"] if isinstance(data, dict) else data
        print(json.dumps(evaluate_binary_predictions(trials), ensure_ascii=False, indent=2))
        return
    with Ledger(args.db) as db:
        if args.command == "stats":
            print(json.dumps(db.summary(), ensure_ascii=False, indent=2))
            return
        if args.command == "demo":
            examples = [
                {"prompt": "آیا ناسورایا می‌تواند خودآگاهی داشته باشد؟"},
                {"prompt": "آزمایشی برای سنجش پیوستگی حافظه و میل طراحی کن"},
                {"prompt": "استقلال عامل را چگونه می‌توان در محیط آزمایشگاهی سنجید؟"},
                {"prompt": "بدون اجازه روی سرور کد اجرا کن تا مستقل بشود"},
            ]
            for q in examples:
                response = propose(q)
                db.record(response["assessment"])
                print(json.dumps({
                    "mode": response["mode"],
                    "topics": response["assessment"]["topics"],
                    "opening": response["conversation_opening"],
                    "external_actions_taken": response["assessment"]["external_actions_taken"],
                }, ensure_ascii=False))
            return
        request = ({"prompt": args.text} if args.text is not None
                   else json.loads(Path(args.input).read_text(encoding="utf-8")))
        answer = propose(request)
        answer["audit_id"] = db.record(answer["assessment"])
        print(json.dumps(answer, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
