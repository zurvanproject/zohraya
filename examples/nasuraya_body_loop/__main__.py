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
    p = argparse.ArgumentParser(description='Verified Tadash body loop; API only with explicit api command')
    p.add_argument('command', choices=['start', 'observe', 'step', 'status', 'demo', 'test', 'api', 'api-test', 'run-status', 'authorize-continuation', 'configure-metacognition', 'configure-language-advisor'])
    p.add_argument('--session', type=Path)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--fixture', choices=['normal', 'sleep', 'recovery-ready'], default='normal')
    p.add_argument('--mode', choices=['observe', 'bounded'], default='bounded')
    p.add_argument('--max-actions', type=int, default=3)
    p.add_argument('--steps', type=int, default=3)
    p.add_argument('--decision-id')
    p.add_argument('--preferred-action', choices=['walk', 'observe', 'sleep', 'rest'], default='walk')
    p.add_argument('--duration-s', type=float, default=.1)
    p.add_argument('--api-mode', choices=['observe', 'bounded'], default='observe')
    p.add_argument('--target-cycles', type=int, default=0)
    p.add_argument('--run-id', default='main')
    p.add_argument('--grant-id')
    p.add_argument('--observed-checkpoint-sha256')
    p.add_argument('--additional-actions', type=int)
    p.add_argument('--additional-calls', type=int)
    p.add_argument('--self-model', type=Path)
    p.add_argument('--metacognition-mode', choices=['shadow', 'enforce'])
    p.add_argument('--create-self-model', action='store_true')
    p.add_argument('--advisor-run',type=Path)
    p.add_argument('--advisor-base',type=Path)
    p.add_argument('--api-recovery', choices=['resume', 'fresh'], default='resume')
    p.add_argument('--max-reconnects', type=int, default=1)
    p.add_argument('--model')
    p.add_argument('--max-calls', type=int, default=40)
    p.add_argument('--timeout-seconds', type=float, default=30)
    args = p.parse_args(argv)
    if args.command not in ['demo', 'test', 'api-test'] and args.session is None:
        p.error('--session required')
    if args.command == 'demo' and args.output_dir is None:
        p.error('--output-dir required')
    if args.command == 'api' and (args.output_dir is None or not args.model):
        p.error('--output-dir and --model required for explicit live API')
    if args.command == 'authorize-continuation' and any(v is None for v in
            (args.grant_id, args.observed_checkpoint_sha256, args.additional_actions, args.additional_calls)):
        p.error('explicit grant, checkpoint, action count and call count required')
    if args.command == 'configure-metacognition' and any(v is None for v in
            (args.self_model, args.metacognition_mode, args.observed_checkpoint_sha256)):
        p.error('explicit self-model path, mode and checkpoint required')
    if args.command == 'configure-language-advisor' and any(v is None for v in
            (args.advisor_run,args.advisor_base,args.observed_checkpoint_sha256)):
        p.error('explicit advisor run, base and current checkpoint required')
    payload = vars(args)
    for key in ('session', 'output_dir', 'self_model','advisor_run','advisor_base'):
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
        if args.command == 'api':
            # The user-approved ignored file is read only for this explicit
            # command. The key is inherited by the worker, never serialized.
            key = os.environ.get('OPENAI_API_KEY')
            local = ROOT / '.env.local'
            if not key and local.is_file() and not local.is_symlink():
                if local.stat().st_mode & 0o077:
                    raise ValueError('API key file must be private')
                for line in local.read_text().splitlines():
                    if line.startswith('OPENAI_API_KEY='):
                        key = line.partition('=')[2].strip()
            if not key:
                raise ValueError('explicit live API requires the approved local key')
            env['OPENAI_API_KEY'] = key
        env['PYTHONPATH'] = str(work) + os.pathsep + str(ROOT)
        return subprocess.run([sys.executable, '-m', 'examples.nasuraya_body_loop.worker'],
                              cwd=work, env=env, input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
