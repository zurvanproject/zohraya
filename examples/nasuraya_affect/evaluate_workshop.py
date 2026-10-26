"""Paired synthetic executions and continuation from the existing affect ledger."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from examples.nasuraya_agent_loop.local import State
from .engine import AffectiveAgent
from .workshop import AffectiveWorkshop


def paired_trials():
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        for name, state, budget in [
                ('depleted_four_action_budget', State(29, 78, 3), 4),
                ('ordinary_workshop', State(45, 50, 3), 8),
                ('empty_queue_requires_recovery', State(0, 100, 0), 4)]:
            conditions = {}
            for enabled in (False, True):
                with AffectiveAgent(Path(folder)/(name+str(enabled)+'.sqlite')) as agent:
                    work = AffectiveWorkshop.attach(agent, state, max_actions=budget, use_affect=enabled)
                    run = work.run()
                    conditions['affect_on' if enabled else 'affect_off'] = run
            rows.append(dict(scenario=name, conditions=conditions))
    return rows


def project_continuation(output):
    root = Path(__file__).resolve().parents[2]
    seed = root/'evidence/affective-continuity-v01/project-state.sqlite'
    seed_hash = hashlib.sha256(seed.read_bytes()).hexdigest()
    path = output/'continued-project.sqlite'
    if path.exists():
        raise ValueError('continuation already exists; refusing overwrite')
    shutil.copyfile(seed, path)
    with AffectiveAgent(path) as agent:
        before = agent.state()
        work = AffectiveWorkshop.attach(agent, State(29, 78, 3), max_actions=4)
        first = work.step('first')
        assert first['this_call_actions'] == 1
    prefix = [sys.executable, '-m', 'examples.nasuraya_affect.workshop']
    replay = json.loads(subprocess.check_output(prefix+['step','--db',str(path),
                                                      '--request-id','first'], text=True))
    assert replay['replayed'] and replay['this_call_actions'] == 0
    continued = json.loads(subprocess.check_output(prefix+['run','--db',str(path)], text=True))
    with tempfile.TemporaryDirectory() as folder:
        reference = Path(folder)/'reference.sqlite'
        shutil.copyfile(seed, reference)
        with AffectiveAgent(reference) as agent:
            work = AffectiveWorkshop.attach(agent, State(29,78,3), max_actions=4)
            work.step('first')
            uninterrupted = work.run()
    assert continued['final'] == uninterrupted['final']
    assert continued['status'] == 'completed'
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == seed_hash
    return dict(seed_sha256=seed_hash, seed_unchanged=True,
                original_affect_revision=before['revision'], first_receipt=first,
                cold_replay_executed_actions=replay['this_call_actions'],
                cold_continuation_matches_uninterrupted=True, continuation=continued)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output/'results.json').exists() or (args.output/'continued-project.sqlite').exists():
        raise ValueError('final evaluation already exists; use a fresh output directory')
    result = dict(scope='Three deliberately constructed paired workshop scenarios; no language model or physical body',
                  interpretation='Authored policy demonstrates causal execution effects; not learned or general performance improvement',
                  paired=paired_trials(), project=project_continuation(args.output))
    (args.output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    for row in result['paired']:
        print(row['scenario'], {k: (v['status'], v['final']['actions_used'],v['final']['state']['tick'])
                                for k,v in row['conditions'].items()})
    print('Cold continuation equals uninterrupted:', result['project']['cold_continuation_matches_uninterrupted'])


if __name__ == '__main__':
    main()
