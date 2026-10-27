"""Credential-free launcher for the source-verified native body/message bridge."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE, verified_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'message', 'status', 'trace', 'recall', 'consolidate', 'pause', 'resume', 'test', 'evaluate',
        'history-inspect', 'history-export', 'history-trace', 'history-recall', 'history-replay', 'history-test'))
    parser.add_argument('--message-id')
    parser.add_argument('--cue', action='append', default=[])
    parser.add_argument('--session-dir', type=Path)
    parser.add_argument('--seed-affect', type=Path)
    parser.add_argument('--message', type=Path)
    parser.add_argument('--fixture', choices=('normal', 'sleep'), default='normal')
    parser.add_argument('--max-actions', type=int, choices=(1,2,3), default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    history_read = args.command in ('history-trace', 'history-recall', 'history-replay')
    if args.command not in ('test','evaluate', 'history-test') and not history_read and args.session_dir is None:
        parser.error('--session-dir required')
    if history_read and (args.archive is None or args.expected_sha256 is None):
        parser.error('--archive and independently retained --expected-sha256 required')
    if args.command in ('message', 'history-replay') and args.message is None:
        parser.error('--message JSON required; intent must be explicit')
    if args.command in ('trace', 'history-trace') and args.message_id is None:
        parser.error('--message-id required')
    if args.command in ('evaluate', 'history-export') and args.output is None:
        parser.error('--output required')
    if args.command.startswith('history-') and args.command != 'history-test':
        if args.seed_affect or (history_read and args.session_dir is not None):
            parser.error('history recovery has no destination session or active-state seed')
    if args.seed_affect and args.command != 'init':
        parser.error('seed can only be used during explicit initialization')
    payload = vars(args)
    for key in ('session_dir', 'seed_affect', 'message', 'output', 'archive'):
        if payload[key] is not None:
            payload[key] = str(payload[key].resolve())
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-dialogue-body-') as temporary:
        work = Path(temporary)
        for name in manifest:
            destination = work/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, destination)
        env = dict(PATH=os.defpath, PYTHONPATH=str(work)+os.pathsep+str(ROOT),
                   PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-S', '-m', 'examples.nasuraya_affect.dialogue_worker'],
                                cwd=work, env=env, input=json.dumps(payload), text=True)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
