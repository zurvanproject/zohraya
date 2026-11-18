"""CLI: python -m examples.dios_nous [analyze|probe|demo|stats]"""
import argparse
import json
from pathlib import Path
from .protocol import propose
from .metrics import evaluate_binary_predictions
from .audit import Ledger

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
    args = parser.parse_args()
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
