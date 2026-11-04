"""Command line front end; all subcommands remain offline and simulated."""
import argparse
import json
from pathlib import Path
from .engine import LESSONS, connect, demo, evaluate, status, train


def main() -> None:
    parser = argparse.ArgumentParser(description="Nasuraya virtual learning (synthetic only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("demo", "train", "evaluate", "status", "lessons"):
        p = sub.add_parser(cmd)
        if cmd != "lessons":
            p.add_argument("--db", type=Path, required=True)
        if cmd == "demo":
            p.add_argument("--rounds", type=int, default=4)
        if cmd == "train":
            p.add_argument("--context", choices=LESSONS, required=True)
            p.add_argument("--event-id", required=True)
    args = parser.parse_args()
    if args.cmd == "lessons":
        result = LESSONS
    elif args.cmd == "demo":
        result = demo(args.db, rounds=args.rounds)
    else:
        if not args.db.is_file():
            parser.error("database does not exist: run demo with a fresh path first")
        with connect(args.db) as conn:
            if args.cmd == "train":
                result = train(conn, args.event_id, args.context)
            elif args.cmd == "evaluate":
                result = evaluate(conn)
            else:
                result = status(conn)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
