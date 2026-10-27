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
    parser.add_argument('--archive', required=True, type=Path, action='append')
    parser.add_argument('--expected-sha256', required=True, action='append')
    parser.add_argument('--query', required=True)
    parser.add_argument('--max-results', type=int, default=10)
    args = parser.parse_args()
    if len(args.archive) != len(args.expected_sha256) or not 1 <= len(args.archive) <= 4:
        parser.error('provide 1..4 --archive entries with the same number of --expected-sha256 entries, paired by position')
    pairs = [dict(archive=str(path.resolve()), expected_sha256=pin)
             for path, pin in zip(args.archive, args.expected_sha256)]
    payload = dict(query=args.query, max_results=args.max_results)
    if len(pairs) == 1:
        payload.update(pairs[0])
    else:
        payload['archives'] = pairs
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
