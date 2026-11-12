"""Declared research interventions, never accepted by an ordinary session.

The intervention changes a disposable copy of actual native state and journals
the cause. Sensor faults change the readout only. Neither can alter native guards.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .adapters import ROOT
from .veto_review import FIELDS

FIXTURE_KEYS = {'sleep_pressure', 'secondary_sleep_pressure', 'age_s', 'missing',
                'execution_sleep_pressure'}


def validate(value):
    if value is None:
        value = {}
    if type(value) is not dict or set(value) - FIXTURE_KEYS:
        raise ValueError('closed research fixture required')
    result = dict(sleep_pressure=None, secondary_sleep_pressure=None, age_s=0.,
                  missing=False, execution_sleep_pressure=None)
    result.update(value)
    for key in ('sleep_pressure', 'secondary_sleep_pressure', 'execution_sleep_pressure'):
        x = result[key]
        if x is not None and (type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1):
            raise ValueError('invalid synthetic sleep index')
    age = result['age_s']
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 6:
        raise ValueError('invalid synthetic observation age')
    if type(result['missing']) is not bool:
        raise ValueError('missing must be boolean')
    return result


def observe(native, fixture, source):
    values = {k: native['export']['minimum_state'][k] for k in FIELDS}
    if fixture['missing']:
        values['sleep_pressure'] = None
    return dict(source=source, model=native['model'], action='walk',
                sample_id=native['export']['native_checkpoint_sha256'],
                sampled_at_s=native['clock'] - fixture['age_s'], now_s=native['clock'],
                values=values, secondary_sleep_pressure=fixture['secondary_sleep_pressure'],
                guard_reasons=native['research_guard']['walking_restrictions'])


def call(request):
    if sys.platform != 'linux':
        raise ValueError('native research fixture requires Linux')
    bootstrap = 'import sys;sys.path.insert(0,sys.argv[1]);from examples.nasuraya_runtime.veto_fixture import main;main()'
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG')}
    env['PYTHONHASHSEED'] = '0'
    run = subprocess.run([sys.executable, '-I', '-S', '-X', 'utf8', '-c', bootstrap, str(ROOT)],
                         input=json.dumps(request, allow_nan=False), text=True, encoding='utf-8',
                         capture_output=True, timeout=60, env=env)
    if run.returncode:
        raise RuntimeError('research_fixture_failed: ' + run.stderr[-1600:])
    return json.loads(run.stdout)


def main():
    from examples.nasuraya_body_loop.__main__ import SOURCE, verified_sources
    from .native import capture, run
    request = json.load(sys.stdin)
    fixture = validate(request.pop('research_fixture'))
    phase = request.pop('research_phase')
    if phase not in ('observe', 'execute'):
        raise ValueError('known research phase required')
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-veto-research-') as tmp:
        staging = Path(tmp)
        for name in manifest:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        sys.path.insert(0, str(staging))
        os.chdir(staging)
        from synthetic_fixture import prepare_defaults
        from unified_body_v2 import UnifiedBody
        from audit_self_model import assess
        prepare_defaults()
        body = UnifiedBody.restore(request['checkpoint'])
        pressure = fixture['sleep_pressure' if phase == 'observe' else 'execution_sleep_pressure']
        if pressure is not None:
            from persistent_embodiment_v1 import digest
            before_outer = digest(dict(native=body.owner.body(), modules=body.modules, affect=body.affect))
            before = body.owner.body()
            body.owner.aux['sleep_pressure'] = pressure
            body.owner._record(before, body.owner.body(), 'external_input',
                'declared isolated veto-review fixture: sleep-pressure intervention; no physical observation', 0.)
            # An explicit zero-time fixture event at BOTH journal layers. Never
            # rewrite a prior digest, remigrate/reset the body, or weaken restore.
            body.revision += 1
            entry = dict(event_id='research-context-' + str(body.revision), revision=body.revision,
                request_sha256=digest(dict(phase=phase, fixture=fixture)),
                before_sha256=before_outer,
                after_sha256=digest(dict(native=body.owner.body(), modules=body.modules, affect=body.affect)),
                previous_event_sha256=body.journal[-1]['sha256'] if body.journal else None,
                causes=['declared_research_sleep_pressure_intervention'], simulated_seconds=0.,
                owner_ticks=0, wall_utc=body.owner.wall_utc)
            entry['sha256'] = digest(entry)
            body.journal.append(entry)
            body._publish()
        if phase == 'observe':
            result = capture(body, None)
            result['research_guard'] = assess(body)
        else:
            request['checkpoint'] = body.checkpoint()
            result = run(request, staging)
        os.chdir(staging.parent)
    verified_sources()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
