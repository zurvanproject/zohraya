"""Verify the public bundle and run only generated fixtures in a temporary tree."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def verify_sources():
    manifest = json.loads((ROOT / 'PUBLIC_FILES_SHA256.json').read_text())
    for name, expected in manifest.items():
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError('manifest path escapes bundle')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('public file checksum mismatch: ' + name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional destination for synthetic logs/results')
    parser.add_argument('--endurance', action='store_true', help='Also run 200 longitudinal cycles')
    parser.add_argument('--special', action='store_true', help='Also check special organs without food/drink inputs')
    parser.add_argument('--reflection', action='store_true', help='Also verify source-linked decisions, feedback and restart')
    args = parser.parse_args()
    manifest = verify_sources()
    start = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix='tadash-synthetic-') as directory:
        work = Path(directory)
        for name in manifest:
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        def execute(*command):
            return subprocess.run([sys.executable, *command], cwd=work,
                                  capture_output=True, text=True)
        defaults = execute('synthetic_fixture.py')
        if defaults.returncode:
            sys.stderr.write(defaults.stderr)
            return defaults.returncode
        modules = ['test_unified_body_v2', 'test_audit_20261011',
                   'test_checkpoint_cache_order', 'test_privacy_boundary']
        if args.reflection:
            modules.append('test_reflection_cycle')
            modules.append('test_stage2_memory')
        units = execute('-m', 'unittest', '-v', *modules)
        core_units = execute('-m','unittest','discover','-s','tests','-v') if args.reflection else None
        reflection_eval = execute('run_reflection_evaluation.py','--output',str(work/'reflection_evaluation')) if args.reflection else None
        reflection_demo = execute('run_reflection_demo.py','--output',str(work/'reflection_demo')) if args.reflection else None
        scenarios = execute('run_synthetic_scenarios.py')
        endurance = execute('run_endurance.py') if args.endurance else None
        special = execute('run_special_coordination.py') if args.special else None
        unit_log = units.stdout + units.stderr
        match = re.search(r'Ran (\d+) tests', unit_log)
        scenario_result = None
        if scenarios.returncode == 0:
            scenario_result = json.loads(scenarios.stdout)
        result = dict(schema='tadash-public-test-run/1', start_utc=start,
                      end_utc=datetime.now(timezone.utc).isoformat(),
                      python=sys.version, platform=platform.platform(),
                      fixture='deterministic defaults; no Library state loaded',
                      checked_public_files=len(manifest),
                      unit_tests_run=int(match.group(1)) if match else 0,
                      unit_tests_passed=units.returncode == 0,
                      decision_core_tests_run=int(re.search(r'Ran (\d+) tests',core_units.stdout+core_units.stderr).group(1)) if core_units and re.search(r'Ran (\d+) tests',core_units.stdout+core_units.stderr) else 0,
                      decision_core_tests_passed=core_units.returncode == 0 if core_units else None,
                      reflection_evaluation=json.loads((work/'reflection_evaluation/comparison.json').read_text()) if reflection_eval and reflection_eval.returncode == 0 else None,
                      reflection_demo=json.loads((work/'reflection_demo/demo_results.json').read_text()) if reflection_demo and reflection_demo.returncode == 0 else None,
                      scenario_result=scenario_result,
                      scenarios_passed=scenarios.returncode == 0,
                      endurance_result=json.loads((work / 'endurance_results.json').read_text())
                          if endurance is not None and (work / 'endurance_results.json').exists() else None,
                      endurance_passed=endurance.returncode == 0 if endurance is not None else None,
                      special_result=json.loads(special.stdout) if special is not None and special.returncode == 0 else None,
                      special_passed=special.returncode == 0 if special is not None else None,
                      canonical_state_modified=False,
                      empirical_validation=False)
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'unit_tests.log').write_text(unit_log)
            (args.output / 'scenarios.log').write_text(scenarios.stdout + scenarios.stderr)
            (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
            if endurance is not None:
                (args.output / 'endurance.log').write_text(endurance.stdout + endurance.stderr)
            if special is not None:
                (args.output / 'special_coordination.log').write_text(special.stdout + special.stderr)
            if core_units is not None:
                (args.output / 'decision_core_tests.log').write_text(core_units.stdout+core_units.stderr)
                (args.output / 'reflection_evaluation.log').write_text(reflection_eval.stdout+reflection_eval.stderr)
                (args.output / 'reflection_demo.log').write_text(reflection_demo.stdout+reflection_demo.stderr)
                if (work/'reflection_evaluation').exists():
                    shutil.copytree(work/'reflection_evaluation',args.output/'reflection_evaluation',dirs_exist_ok=True)
                if (work/'reflection_demo').exists():
                    shutil.copytree(work/'reflection_demo',args.output/'reflection_demo',dirs_exist_ok=True)
        printable = dict(result)
        if printable['endurance_result'] is not None:
            printable['endurance_result'] = {k:v for k,v in printable['endurance_result'].items() if k!='steps'}
        if printable['special_result'] is not None:
            printable['special_result'] = {k:v for k,v in printable['special_result'].items() if k!='records'}
        if printable['reflection_evaluation'] is not None:
            printable['reflection_evaluation']={k:v for k,v in printable['reflection_evaluation'].items() if k!='records'}
        print(json.dumps(printable, indent=2))
        if units.returncode or scenarios.returncode or (endurance is not None and endurance.returncode) or (special is not None and special.returncode) or any(r is not None and r.returncode for r in [core_units,reflection_eval,reflection_demo]):
            sys.stderr.write(unit_log + scenarios.stdout + scenarios.stderr)
            if special is not None:
                sys.stderr.write(special.stdout + special.stderr)
            for r in [core_units,reflection_eval,reflection_demo]:
                if r is not None and r.returncode:sys.stderr.write(r.stdout+r.stderr)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
