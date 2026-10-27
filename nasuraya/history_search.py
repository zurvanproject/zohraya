"""Run offline history search in a verified native-source subprocess."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from examples.nasuraya_body_loop.__main__ import verified_sources, SOURCE, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--query', required=True)
    parser.add_argument('--max-results', type=int, default=10)
    args = parser.parse_args()
    payload = dict(archive=str(args.archive.resolve()), expected_sha256=args.expected_sha256,
                   query=args.query, max_results=args.max_results)
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-history-fts-') as temporary:
        work = Path(temporary)
        for name in manifest:
            target = work/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, target)
        env = dict(PATH=os.defpath, PYTHONPATH=str(work)+os.pathsep+str(ROOT),
                   PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-S', '-m', 'nasuraya.history_search_worker'],
                                cwd=work, env=env, input=json.dumps(payload), text=True)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
