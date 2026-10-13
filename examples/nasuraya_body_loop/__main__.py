"""Launch each command with verified legacy sources in an isolated process."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'runtimes/tadash_body'


def verified_sources():
    encoded = (SOURCE / 'PUBLIC_FILES_SHA256.json').read_bytes()
    provenance = json.loads((SOURCE / 'IMPORT_PROVENANCE.json').read_text())
    if hashlib.sha256(encoded).hexdigest() != provenance['source_manifest_sha256']:
        raise ValueError('recovered manifest mismatch')
    manifest = json.loads(encoded)
    for name, expected in manifest.items():
        p = SOURCE / name
        if not p.resolve().is_relative_to(SOURCE) or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('recovered source mismatch: ' + name)
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description='Verified local Tadash body loop; no API calls')
    p.add_argument('command', choices=['start', 'observe', 'step', 'status', 'demo', 'test'])
    p.add_argument('--session', type=Path)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--fixture', choices=['normal', 'sleep'], default='normal')
    p.add_argument('--mode', choices=['observe', 'bounded'], default='bounded')
    p.add_argument('--max-actions', type=int, default=3)
    p.add_argument('--steps', type=int, default=3)
    p.add_argument('--decision-id')
    p.add_argument('--duration-s', type=float, default=.1)
    args = p.parse_args(argv)
    if args.command not in ['demo', 'test'] and args.session is None:
        p.error('--session required')
    if args.command == 'demo' and args.output_dir is None:
        p.error('--output-dir required')
    payload = vars(args)
    for key in ('session', 'output_dir'):
        if payload[key] is not None:
            payload[key] = str(payload[key].resolve())
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-body-runtime-') as tmp:
        work = Path(tmp)
        for name in manifest:
            dest = work / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, dest)
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        env['PYTHONPATH'] = str(work) + os.pathsep + str(ROOT)
        return subprocess.run([sys.executable, '-m', 'examples.nasuraya_body_loop.worker'],
                              cwd=work, env=env, input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
