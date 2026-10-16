import argparse
from datetime import datetime, timezone
import json
import sqlite3
import sys

from . import __version__
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='Durable admission records; executes no jobs, network calls or payments.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('operation', choices=['init', 'status', 'claim', 'finish', 'heartbeat', 'pause'])
    parser.add_argument('--db', required=True)
    parser.add_argument('--now', help='trusted clock; explicit offset required; defaults to current UTC')
    parser.add_argument('--request-id')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    now = args.now or datetime.now(timezone.utc).isoformat()
    store = None
    try:
        if args.operation in ('init', 'status') and (args.request_id or args.run_id):
            raise ValueError('request/run ids only apply to transitions')
        store = Store.create(args.db, now) if args.operation == 'init' else Store(args.db)
        if args.operation in ('init', 'status'):
            result = store.status(now)
        else:
            result = store.apply(args.operation, args.request_id, now, args.run_id)
        print(json.dumps(dict(ok=True, result=result), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps(dict(ok=False, error=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
