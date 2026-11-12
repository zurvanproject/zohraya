"""Versioned adapters; no network, credentials, generator or remote executor."""
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from examples.tadash_interoception.model import Decoder
from examples.tadash_interoception.state import digest

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'docs/evidence/tadash-interoception-v01/confirmation-frozen_models.json.gz'
MODEL_SHA = '1f8c6dadc6eaa45b5bdf16e3e870cbb1a20cdd4bf020dd8fa503eda19abdec46'


def decoder():
    raw = MODEL.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MODEL_SHA:
        raise ValueError('frozen decoder file mismatch')
    row = json.loads(gzip.decompress(raw))['full']
    result = Decoder([(tuple(x), label, y) for x, label, y in row['examples']],
                     temperature=row['temperature'])
    if result.fingerprint() != row['sha256']:
        raise ValueError('frozen decoder parameter mismatch')
    return result


def source_identity():
    """Detect code changes across resume, in addition to inherited source pins."""
    from examples.nasuraya_body_loop.__main__ import verified_sources
    verified_sources()
    from examples.dios_nous.unified import body, evidence, state_models
    body._verified_sources()
    state_models._sources()
    evidence._assets()
    paths = []
    for directory in ('examples/nasuraya_runtime', 'examples/tadash_interoception',
                      'examples/dios_nous', 'examples/nasuraya_agent_loop',
                      'examples/nasuraya_body_loop', 'examples/nasuraya_research',
                      'runtimes/tadash_body'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.suffix in ('.py', '.json')
                     and '__pycache__' not in p.parts and not p.name.startswith('test'))
    rows = {str(p.relative_to(ROOT)).replace(os.sep, '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}
    rows['frozen_decoder'] = decoder().fingerprint()
    return digest(rows)


def visual_plan(*, recovery):
    """Execute PR175's text planner; body workload chooses an authored context."""
    folder = Path(__file__).parent / 'reused/visual'
    pins = json.loads((folder / 'provenance.json').read_text())
    for name, sha in pins['files'].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != sha:
            raise ValueError('visual source mismatch')
    from .reused.visual.visual_director import direct
    context = ('resting in a quiet courtyard with relaxed hands' if recovery
               else 'practicing a gentle open palm exercise in a courtyard')
    return direct({'current_prompt': 'A new single full-body scene, ' + context,
                   'previous_visual_brief': 'Adult Nasuraya, copper curls, curved red horns, '
                   'long tail, digitigrade feet, opaque practical clothing, ' + context,
                   'visual_intensity': 3, 'full_body': True, 'letter_required': False})


def fixture_summary(report):
    """Compare semantic state, not legacy JSON dictionary byte ordering.

    The complete raw-byte hashes stay in the retained execution report. The
    inherited affect serializer's dict insertion order varies across processes;
    its sorted semantic state digest is reproducible.
    """
    result = json.loads(json.dumps(report))
    result.pop('result_sha256')
    for model in result['models'].values():
        model.pop('checkpoint_sha256', None)
    result['checkpoint_byte_hashes'] = 'retained_in_fixed-models-report.json; not semantic identity'
    result['semantic_sha256'] = digest(result)
    return result


def native_call(payload):
    """A disposable pure simulation; caller commits its checkpoint atomically."""
    if sys.platform != 'linux':
        raise ValueError('native backend requires Linux; portable workshop is available')
    bootstrap = 'import sys;sys.path.insert(0,sys.argv[1]);from examples.nasuraya_runtime.native import main;main()'
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG')}
    env['PYTHONHASHSEED'] = '0'
    result = subprocess.run([sys.executable, '-I', '-S', '-X', 'utf8', '-c', bootstrap, str(ROOT)],
                            input=json.dumps(payload), text=True, encoding='utf-8',
                            capture_output=True, timeout=60, env=env)
    if result.returncode:
        # Retain diagnostics without dumping worker arguments or state to callers.
        raise RuntimeError('native_worker_failed: ' + result.stderr[-1600:])
    return json.loads(result.stdout)
