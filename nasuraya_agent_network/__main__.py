"""CLI: run/status/pause/resume; no daemon or schedule is created."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from .engine import run


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('run', 'status', 'pause', 'resume'))
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--run-id', default='manual-001')
    parser.add_argument('--max-workers', type=int, default=2)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if args.command == 'run':
        report = run(args.root, workspace, args.run_id, args.max_workers)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report['status'] == 'passed' else 1
    if args.command in ('pause', 'resume'):
        workspace.mkdir(parents=True, exist_ok=True)
        if args.command == 'pause':
            (workspace / 'STOP').touch(exist_ok=True)
        else:
            (workspace / 'STOP').unlink(missing_ok=True)
        print(json.dumps({'paused': (workspace / 'STOP').exists(), 'scope': 'this workspace only'}))
        return 0
    path = workspace / 'ledger.sqlite'
    rows = []
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT id,status FROM runs ORDER BY rowid').fetchall()
    print(json.dumps({'paused': (workspace / 'STOP').exists(), 'runs': rows}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
