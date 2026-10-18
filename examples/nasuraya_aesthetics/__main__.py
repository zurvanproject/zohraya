"""Report visual appraisal, or explicitly apply one budgeted body simulation cycle."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .appraisal import appraise
from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE, verified_sources


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('report', 'apply', 'test', 'evaluate'))
    p.add_argument('--observation', type=Path)
    p.add_argument('--image', type=Path)
    p.add_argument('--reference', type=Path)
    p.add_argument('--session', type=Path)
    p.add_argument('--output-dir', type=Path)
    args = p.parse_args(argv)
    payload = dict(command=args.command)
    if args.command in ('report', 'apply'):
        if args.observation is None: p.error('--observation required')
        payload['observation'] = json.loads(args.observation.read_text())
        payload['approved_reference'] = json.loads(args.reference.read_text()) if args.reference else None
        payload['image_path'] = str(args.image.resolve()) if args.image else None
        # Validate the input before opening a body session.
        prepared = appraise(payload['observation'], approved_reference=payload['approved_reference'],
                           image_path=payload['image_path'])
        if args.command == 'report':
            print(json.dumps(prepared, ensure_ascii=False, indent=2)); return 0
        if args.session is None or args.image is None:
            p.error('apply requires an existing --session and --image to verify the rated bytes')
        payload['session'] = str(args.session.resolve())
    if args.output_dir:
        if args.command != 'evaluate': p.error('--output-dir is for evaluate only')
        payload['output_dir'] = str(args.output_dir.resolve())
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='aesthetic-native-') as tmp:
        work = Path(tmp)
        for name in manifest:
            dest = work / name; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, dest)
        env = dict(PATH=os.defpath, PYTHONPATH=str(work) + os.pathsep + str(ROOT),
                   PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, '-S', '-m', 'examples.nasuraya_aesthetics.worker'],
                              cwd=work, env=env, input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
