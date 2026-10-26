"""One launcher for explicit project commands; no automatic activation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .catalog import CAPABILITIES, ROOT, validate


def environment():
    env = os.environ.copy()
    # Legacy modules have sibling imports. Keep their resolution deterministic.
    paths = [ROOT, ROOT/'examples/nasuraya_security', ROOT/'examples/nasuraya_star_motion',
             ROOT/'runtimes/tadash_body']
    env['PYTHONPATH'] = os.pathsep.join(map(str, paths))
    env['NASURAYA_NATIVE_ROOT'] = str(ROOT/'runtimes/tadash_body')
    return env


def invoke(capability, arguments, *, capture=False):
    if capability not in CAPABILITIES:
        raise ValueError('unknown capability')
    module, profile, _ = CAPABILITIES[capability]
    # Explicit environment selection supports incompatible optional lockfiles.
    python = os.environ.get('NASURAYA_PYTHON_' + profile.upper(), sys.executable)
    if not Path(python).is_file():
        raise ValueError('profile interpreter must be an existing absolute file')
    env = environment()
    target = ROOT.joinpath(*module.split('.'))
    sibling = target if target.is_dir() else target.parent
    env['PYTHONPATH'] = str(sibling) + os.pathsep + env['PYTHONPATH']
    return subprocess.run([python, '-m', module, *arguments], cwd=ROOT,
                          env=env, capture_output=capture, text=True)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in CAPABILITIES:
        return invoke(args[0], args[1:]).returncode
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('catalog', help='List all entry points and dependency profiles')
    demo = sub.add_parser('demo', help='Fresh offline genome/message/body/affect/replay scenario')
    demo.add_argument('--output', required=True, type=Path)
    continuity = sub.add_parser('continuity-demo', help='Cold dialogue/memory/forecast/body/learning demonstration')
    continuity.add_argument('--output', required=True, type=Path)
    tests = sub.add_parser('test', help='Isolated test modules; no live service calls')
    tests.add_argument('--profile', choices=('core','mechanics','tensor','sdk','all'), default='core')
    tests.add_argument('--output', required=True, type=Path)
    tests.add_argument('--module', action='append', default=[])
    parsed = parser.parse_args(args)
    if parsed.command == 'catalog':
        print(json.dumps(dict(schema='nasuraya.capabilities/1', capabilities=validate()),
                         ensure_ascii=False, indent=2))
        return 0
    if parsed.command in ('demo', 'continuity-demo'):
        if parsed.command == 'demo':
            from .demo import run
        else:
            from .continuity_demo import run
        print(json.dumps(run(parsed.output), ensure_ascii=False, indent=2))
        return 0
    from .testing import run
    return run(parsed.output, parsed.profile, parsed.module)


if __name__ == '__main__':
    raise SystemExit(main())
