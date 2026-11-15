"""Run the optional setar bridge inside the existing verified body runtime."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['bind', 'status', 'evaluate', 'step', 'lesson', 'test'])
    parser.add_argument('--session', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--max-steps', type=int, default=3)
    parser.add_argument('--seed', type=int, default=4110000)
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument('--realtime', action='store_true')
    timing.add_argument('--accelerated', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'test' and args.session is None:
        parser.error('--session required')
    if args.command in ('step', 'lesson') and (not args.run_id or args.output_dir is None
                                  or not (args.realtime or args.accelerated)):
        parser.error('step requires --run-id, fresh --output-dir and explicit timing mode')
    if args.command not in ('step', 'lesson') and (args.realtime or args.accelerated or args.output_dir or args.run_id):
        parser.error('timing, output and run-id are step/lesson-only options')
    if args.command != 'bind' and args.checkpoint is not None:
        parser.error('--checkpoint is a bind-only option')
    # Reuse the same source manifest validation as the native body launcher.
    from examples.nasuraya_body_loop.__main__ import verified_sources, SOURCE, ROOT
    manifest = verified_sources()
    payload = vars(args)
    for key in ('session', 'checkpoint', 'output_dir'):
        if payload[key] is not None:
            payload[key] = str(payload[key].absolute())
    with tempfile.TemporaryDirectory(prefix='setar-verified-body-') as folder:
        work = Path(folder)
        for name in manifest:
            dest = work / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, dest)
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        env['PYTHONPATH'] = str(work) + os.pathsep + str(ROOT)
        return subprocess.run([sys.executable, '-m', 'examples.setar_practice.body_worker'],
            cwd=work, env=env, input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
