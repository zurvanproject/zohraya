import argparse
from datetime import datetime, timezone
import json
import sqlite3
import sys

from . import __version__
from .store import Store
from .local_job import LocalJobs, MAX_INPUT_BYTES


def main():
    parser = argparse.ArgumentParser(description='Durable admission and bounded local integrity reports; no network or payments.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('operation', choices=['init', 'status', 'claim', 'finish', 'heartbeat', 'pause',
                                             'run-local', 'inspect-local', 'abandon-local'])
    parser.add_argument('--db', required=True)
    parser.add_argument('--now', help='trusted clock; explicit offset required; defaults to current UTC')
    parser.add_argument('--request-id')
    parser.add_argument('--run-id')
    parser.add_argument('--input', help='run-local: local UTF-8 JSON list; maximum 65536 bytes')
    parser.add_argument('--operator', help='abandon-local: responsible host identity (trusted declaration)')
    parser.add_argument('--evidence', help='abandon-local: host review note')
    parser.add_argument('--worker-stopped', action='store_true', help='host attests the previous worker has stopped')
    args = parser.parse_args()
    now = args.now or datetime.now(timezone.utc).isoformat()
    store = None
    try:
        if args.operation in ('init', 'status') and (args.request_id or args.run_id):
            raise ValueError('request/run ids only apply to transitions')
        if args.input is not None and args.operation != 'run-local':
            raise ValueError('--input only applies to run-local')
        if (args.operator or args.evidence or args.worker_stopped) and args.operation != 'abandon-local':
            raise ValueError('host reconciliation flags only apply to abandon-local')
        store = Store.create(args.db, now) if args.operation == 'init' else Store(args.db)
        if args.operation in ('init', 'status'):
            result = store.status(now)
        elif args.operation == 'run-local':
            if not args.input:
                raise ValueError('--input required')
            # Bound reads and refuse FIFOs/devices; trusted local regular files only.
            import os
            import stat
            fd = os.open(args.input, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError('input must be a regular local file')
                raw = source.read(MAX_INPUT_BYTES + 1)
            result = LocalJobs(store).run(args.request_id, args.run_id, now, raw)
        elif args.operation == 'inspect-local':
            if args.request_id:
                raise ValueError('inspect-local does not accept a request id')
            result = LocalJobs(store).inspect(args.run_id)
        elif args.operation == 'abandon-local':
            result = LocalJobs(store).abandon(args.request_id, args.run_id, now,
                args.operator, args.evidence, args.worker_stopped)
        else:
            result = store.apply(args.operation, args.request_id, now, args.run_id)
        print(json.dumps(dict(ok=True, result=result), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, UnicodeError, OSError, sqlite3.Error) as exc:
        print(json.dumps(dict(ok=False, error=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
