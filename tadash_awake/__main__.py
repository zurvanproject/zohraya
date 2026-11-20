"""CLI to drive bounded ticks from Windows Task Scheduler."""
import argparse
import json
from pathlib import Path
import sys
from . import core

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["init", "ingest", "tick", "status", "pause", "resume"])
    p.add_argument("--root", required=True)
    p.add_argument("--file")
    args = p.parse_args(argv)
    try:
        if args.command == "init":
            db = core.connect(args.root)
            db.close()
            result = {"status": "initialized_paused"}
        elif args.command == "ingest":
            if not args.file:
                p.error("ingest requires --file")
            f = Path(args.file)
            if f.stat().st_size > 64000:
                raise ValueError("input too large")
            result = core.ingest(args.root, json.loads(f.read_text(encoding="utf-8")))
        elif args.command == "tick":
            result = core.tick(args.root)
        elif args.command == "status":
            result = core.status(args.root)
        else:
            result = core.set_paused(args.root, args.command == "pause")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
