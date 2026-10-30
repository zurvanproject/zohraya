"""Rebuild and audit saved evaluation evidence without executing body cycles."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .__main__ import ROOT, SOURCE, verified_sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    path = args.output_dir.resolve()
    if not path.is_dir():
        parser.error('existing completed evaluation directory required')
    if args.worker:
        from .continuous_self_eval import finalize
        result = finalize(path)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-self-audit-') as tmp:
        for name in manifest:
            dest = Path(tmp)/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, dest)
        env = dict(os.environ); env.pop('OPENAI_API_KEY', None)
        env['PYTHONPATH'] = tmp + os.pathsep + str(ROOT)
        return subprocess.run([sys.executable, '-m', __spec__.name, str(path), '--worker'],
                              cwd=tmp, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
