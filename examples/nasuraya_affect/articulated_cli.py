"""Local articulated dialogue pilot; no credentials or automatic listener."""
import argparse
import json
from pathlib import Path
import sqlite3
from .engine import AffectiveAgent
from .articulated_dialogue import ArticulatedDialogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'message', 'status', 'pause'))
    parser.add_argument('--session-dir', required=True, type=Path)
    parser.add_argument('--seed-affect', type=Path)
    parser.add_argument('--message', type=Path)
    args = parser.parse_args()
    if args.command == 'message' and args.message is None:
        parser.error('--message required')
    if args.seed_affect and args.command != 'init':
        parser.error('seed only allowed at initialization')
    path = args.session_dir/'affect.sqlite'
    if args.command == 'init':
        args.session_dir.mkdir(parents=True, exist_ok=False)
        if args.seed_affect:
            if not args.seed_affect.is_file():
                parser.error('existing seed required')
            with sqlite3.connect(args.seed_affect.resolve().as_uri()+'?mode=ro', uri=True) as src:
                with sqlite3.connect(path) as dst:
                    src.backup(dst)
    elif not path.is_file():
        parser.error('existing session required')
    with AffectiveAgent(path) as affect:
        bridge = ArticulatedDialogue.enable(affect) if args.command=='init' else ArticulatedDialogue(affect)
        if args.command == 'pause':
            bridge.pause()
        result = bridge.receive(json.loads(args.message.read_text())) if args.command=='message' else bridge.status()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
