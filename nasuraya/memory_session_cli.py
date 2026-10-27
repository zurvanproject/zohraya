"""Explicit, credential-free launcher for source-attributed dialogue sessions."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE, verified_sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'message', 'status', 'trace', 'pause', 'resume'))
    parser.add_argument('--session-dir', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--message', type=Path)
    parser.add_argument('--message-id')
    parser.add_argument('--query')
    parser.add_argument('--max-results', type=int, default=3)
    parser.add_argument('--fixture', choices=('normal', 'sleep'), default='normal')
    parser.add_argument('--max-actions', type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args(argv)
    if (args.command == 'init') != (args.archive is not None):
        parser.error('--archive is required for init and is not accepted by other commands')
    if (args.command == 'message') != (args.message is not None):
        parser.error('--message JSON is required for message and is not accepted by other commands')
    if (args.command == 'trace') != (args.message_id is not None):
        parser.error('--message-id is required for trace and is not accepted by other commands')
    if args.query is not None and args.command != 'message':
        parser.error('--query is accepted only for message')
    if not 1 <= args.max_results <= 3:
        parser.error('--max-results must be in 1..3')
    payload = vars(args)
    for key in ('session_dir', 'archive', 'message'):
        if payload[key] is not None:
            payload[key] = str(payload[key].resolve())
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-memory-session-') as temporary:
        work = Path(temporary)
        for name in manifest:
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        env = dict(PATH=os.defpath, PYTHONPATH=str(work) + os.pathsep + str(ROOT),
                   PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run(
            [sys.executable, '-S', '-m', 'nasuraya.memory_session_worker'],
            cwd=work, env=env, input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
