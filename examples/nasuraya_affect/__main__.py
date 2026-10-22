"""Run from repository root: python -m examples.nasuraya_affect --help."""
import argparse
import json
from pathlib import Path

from .engine import AffectiveAgent


def main():
    parser = argparse.ArgumentParser(description='Persistent affective planning; no actions executed.')
    parser.add_argument('command', choices=('init', 'show', 'step'))
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--request', type=Path)
    args = parser.parse_args()
    if args.command == 'init' and args.db.exists():
        parser.error('ledger already exists; use show or step')
    if args.command != 'init' and not args.db.exists():
        parser.error('ledger missing; initialize explicitly')
    if args.command == 'step' and args.request is None:
        parser.error('step requires --request')
    with AffectiveAgent(args.db) as agent:
        if args.command == 'step':
            request = json.loads(args.request.read_text())
            result = agent.step(**request)
        else:
            result = agent.state()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
