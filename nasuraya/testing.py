"""Run component suites in separate processes to isolate legacy import state."""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from .catalog import ROOT
from .__main__ import environment


def inventory():
    result = {}
    for directory in ('nasuraya', 'examples', 'continuity', 'continuity_host', 'project_fund',
                      'services', 'nasuraya_continuity_kit', 'zohraya'):
        for path in sorted((ROOT/directory).rglob('test_*.py')):
            if 'vendor' in path.parts:
                continue
            module = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
            profile = ('tensor' if any(x in module for x in ('nasuraya_language', 'nasuraya_lm_internals', 'test_adaptive_support')) else
                       'mechanics' if '.articulated.' in module or module.endswith('test_running_balance') else
                       'sdk' if module.endswith(('test_sdk_transport','test_loopback')) else 'core')
            result[module] = profile
    return result


def run(output, profile='core', modules=()):
    found = inventory()
    if set(modules) - found.keys():
        raise ValueError('module must be a discovered project test')
    chosen = sorted(modules or [m for m,p in found.items() if profile=='all' or p==profile])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = environment()
    env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for key in ('OPENAI_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN', 'GH_HOST_TOKEN'):
        env.pop(key, None)
    def execute(module):
        python = os.environ.get('NASURAYA_PYTHON_'+found[module].upper(), sys.executable)
        module_env = dict(env)
        sibling = ROOT.joinpath(*module.split('.')).parent
        module_env['PYTHONPATH'] = str(sibling) + os.pathsep + env['PYTHONPATH']
        start = time.monotonic()
        try:
            proc = subprocess.run([python,'-m','unittest',module,'-v'], cwd=ROOT, env=module_env,
                                  capture_output=True, text=True, timeout=300)
            log, code = proc.stdout+proc.stderr, proc.returncode
        except subprocess.TimeoutExpired:
            log, code = 'Component suite exceeded the 300 second limit.\n', 124
        (output/(module+'.log')).write_text(log)
        match = re.search(r'Ran (\d+) tests?', log)
        skipped = re.search(r'skipped=(\d+)', log)
        row = dict(module=module, profile=found[module], exit_code=code,
                   tests=int(match[1]) if match else 0, skipped=int(skipped[1]) if skipped else 0,
                   seconds=round(time.monotonic()-start,2))
        print(json.dumps(row), flush=True)
        return row
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(execute, chosen))
    report = dict(schema='nasuraya.unified-tests/1', modules=rows,
                  tests=sum(r['tests'] for r in rows), skipped=sum(r['skipped'] for r in rows),
                  failed_modules=sum(r['exit_code']!=0 for r in rows))
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return int(report['failed_modules'] != 0)
