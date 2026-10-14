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
    p = argparse.ArgumentParser(description='Verified Tadash body loop; live API requires explicit api or allowed API wakeup')
    p.add_argument('command', choices=['start', 'observe', 'step', 'status', 'demo', 'test', 'api', 'api-test', 'run-status', 'authorize-continuation', 'schedule', 'wake', 'wake-watch', 'wake-status', 'wake-test', 'wake-demo', 'care-test', 'care-demo', 'care-memory', 'experience-test', 'experience-live-check', 'memory-ablation', 'decision-test', 'intent-status'])
    p.add_argument('--session', type=Path)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--fixture', choices=['normal', 'sleep'], default='normal')
    p.add_argument('--mode', choices=['observe', 'bounded'], default='bounded')
    p.add_argument('--max-actions', type=int, default=3)
    p.add_argument('--steps', type=int, default=3)
    p.add_argument('--decision-id')
    p.add_argument('--duration-s', type=float, default=.1)
    p.add_argument('--api-mode', choices=['observe', 'bounded'], default='observe')
    p.add_argument('--target-cycles', type=int, default=0)
    p.add_argument('--run-id', default='main')
    p.add_argument('--grant-id')
    p.add_argument('--observed-checkpoint-sha256')
    p.add_argument('--additional-actions', type=int)
    p.add_argument('--additional-calls', type=int)
    p.add_argument('--api-recovery', choices=['resume', 'fresh'], default='resume')
    p.add_argument('--max-reconnects', type=int, default=1)
    p.add_argument('--model')
    p.add_argument('--max-calls', type=int, default=40)
    p.add_argument('--timeout-seconds', type=float, default=30)
    p.add_argument('--wake-id')
    p.add_argument('--due-at')
    p.add_argument('--expires-at')
    p.add_argument('--wake-backend', choices=['synthetic', 'api', 'care'], default='synthetic')
    p.add_argument('--wake-attempts', type=int, default=3)
    p.add_argument('--retry-delay-seconds', type=float, default=30)
    p.add_argument('--watch-ticks', type=int, default=60)
    p.add_argument('--poll-seconds', type=float, default=1)
    p.add_argument('--allow-live-wakeup', action='store_true')
    args = p.parse_args(argv)
    if args.command not in ['demo', 'test', 'api-test', 'wake-test', 'wake-demo', 'care-test', 'care-demo', 'experience-test', 'memory-ablation', 'decision-test'] and args.session is None:
        p.error('--session required')
    if args.command in ('demo', 'wake-demo', 'care-demo', 'experience-live-check', 'memory-ablation') and args.output_dir is None:
        p.error('--output-dir required')
    if args.command == 'api' and (args.output_dir is None or not args.model):
        p.error('--output-dir and --model required for explicit live API')
    if args.command == 'authorize-continuation' and any(v is None for v in
            (args.grant_id, args.observed_checkpoint_sha256, args.additional_actions, args.additional_calls)):
        p.error('explicit grant, checkpoint, action count and call count required')
    if args.command in ('schedule', 'wake', 'wake-watch', 'experience-live-check') and not args.wake_id:
        p.error('--wake-id required')
    if args.command == 'schedule' and not all((args.due_at, args.expires_at, args.model)):
        p.error('--due-at, --expires-at and fixed --model required')
    if args.command == 'wake-watch' and not (1 <= args.watch_ticks <= 86400 and
            1 <= args.poll_seconds <= 60 and args.watch_ticks * args.poll_seconds <= 86400):
        p.error('finite watch up to one day, with polling every 1..60 seconds required')
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
        if args.command in ('api', 'experience-live-check') or (args.command in ('wake', 'wake-watch') and args.allow_live_wakeup):
            # The approved ignored file is read only for an explicit live
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
