"""Explicit CLI for at most three native simulation cycles; never a daemon."""
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('init', 'run', 'step', 'status', 'pause', 'resume', 'test', 'evaluate', 'transfer', 'transfer-test'))
    p.add_argument('--session', type=Path)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--fixture', choices=('normal', 'sleep'), default='normal')
    p.add_argument('--max-actions', type=int, choices=(1, 2, 3), default=3)
    p.add_argument('--steps', type=int, choices=(1, 2, 3), default=1)
    p.add_argument('--duration-s', type=float, default=.1)
    p.add_argument('--request-id')
    p.add_argument('--forecast-confidence', type=float,
                   help='init only: opt in to report-only calibration with this declared prior')
    args = p.parse_args(argv)
    if args.forecast_confidence is not None:
        from .confidence import probability
        try:
            probability(args.forecast_confidence)
        except ValueError as exc:
            p.error(str(exc))
        if args.command != 'init':
            p.error('--forecast-confidence is fixed at init; use a new disposable session')
    if args.command == 'transfer' and args.output_dir is None:
        p.error('--output-dir is required for sealed transfer evidence')
    if args.output_dir is not None and args.command != 'transfer':
        p.error('--output-dir is only used by transfer')
    if args.command not in ('test', 'evaluate', 'transfer', 'transfer-test') and args.session is None:
        p.error('--session is required')
    if args.command == 'step' and not args.request_id:
        p.error('--request-id is required for replayable step')
    payload = vars(args)
    if args.session is not None:
        payload['session'] = str(args.session.absolute())
    if args.output_dir is not None:
        payload['output_dir'] = str(args.output_dir.absolute())
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='research-control-native-') as tmp:
        work = Path(tmp)
        for name in manifest:
            dest = work / name; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, dest)
        # The simulation worker needs no inherited credentials or external API.
        env = {'PATH': os.defpath, 'PYTHONPATH': str(work) + os.pathsep + str(ROOT),
               'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        return subprocess.run([sys.executable, '-S', '-m',
            'examples.nasuraya_research.control_worker'], cwd=work, env=env,
            input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
