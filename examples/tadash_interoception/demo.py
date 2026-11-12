"""Connect numeric palm state to existing agent tools and native body runtime."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from examples.nasuraya_agent_loop.local import Journal, State, ToolHost, run_local
from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE, verified_sources
from .sensory import Stimulus, transduce
from .state import observe
from .integration import SensoryPolicy, correction_gate
from .evaluate import write_json, dataset, training_rows
from .model import Decoder


def native_demo(directory):
    if sys.platform != 'linux':
        return {'status': 'not_executed_native_runtime_requires_linux'}
    directory = Path(directory).resolve()
    directory.mkdir()
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='interoception-native-') as temp:
        staging = Path(temp)
        for name in manifest:
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, dest)
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        env['PYTHONPATH'] = str(staging) + os.pathsep + str(ROOT)
        env['PYTHONUTF8'] = '1'
        result = subprocess.run([sys.executable, '-m', 'examples.tadash_interoception.native_worker', str(directory)],
                                cwd=staging, env=env, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError('native demonstration failed: ' + result.stderr[-4000:])
        receipt = json.loads(result.stdout)
    verified_sources()  # Original runtime remains unchanged; only staging advanced.
    return dict(receipt, verified_source_files=len(manifest), original_sources_unchanged=True)


def run(directory, *, native=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    results = {}
    decoder = Decoder(training_rows(dataset('train', seeds=range(2000, 2080))))
    for name, intensity in (('none', 0.), ('mechanical', .95)):
        stimulus = Stimulus('left_palm', intensity, .8, 12., name, .025, .2)
        state = observe(transduce(stimulus, seed=183))
        policy = SensoryPolicy(state, directory / name)
        journal = Journal(directory / name / 'agent.jsonl')
        host = ToolHost(State(70, 30, 2), journal, max_actions=1)
        output = run_local(host, policy, max_steps=1)
        write_json(directory / name / 'state.json', state.checkpoint())
        # This run deliberately executes one step, not full task completion.
        results[name] = {'internal_load': state.load, 'attention': state.attention,
                         'state_checkpoint': state.checkpoint()['sha256'],
                         'agent': output, 'rotation': policy.last_rotation,
                         'goal': policy.plan, 'introspection': policy.introspect(decoder)}
        policy.stop()
        restored = SensoryPolicy(state, directory / name)
        results[name]['stop_survives_reopen'] = restored.plan['selected_goal'] is None
    results['behavior_changed'] = results['none']['agent']['final_state'] != results['mechanical']['agent']['final_state']
    # Existing evidence memory really revises its view on successive measured gates.
    results['revision'] = [
        correction_gate(directory / 'revision', {'brier': .1, 'accuracy': .8},
                        {'brier': .2, 'accuracy': .8}, phase=1),
        correction_gate(directory / 'revision', {'brier': .1, 'accuracy': .8},
                        {'brier': .05, 'accuracy': .8}, phase=2)]
    results['revision_fixture_is_authored'] = True
    if native: results['native_body'] = native_demo(directory / 'native')
    results['limits'] = ['One-step behavior change is not a demonstrated gain in task utility.',
                         'Native palm projection is scalar touch; no hand-specific native reflex exists.',
                         'No subjective experience or live LLM integration is established.']
    write_json(directory / 'demo.json', results)
    return results


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--native', action='store_true')
    args = p.parse_args()
    print(json.dumps(run(args.output, native=args.native), indent=2))


if __name__ == '__main__': main()
