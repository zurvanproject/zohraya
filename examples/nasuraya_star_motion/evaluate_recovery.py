"""Compare a full uninterrupted suffix with a stopped/fresh-process suffix.

Input is a source-pinned MotionGoal envelope, possibly an already accumulated
practice body. No native state is initialized, migrated, refilled or overwritten.
Private evidence is written only to the caller's new output directory.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(args):
    sys.path.insert(0, str(Path(args.native_root).resolve()))
    from motion_goal import MotionGoal, LIMITS
    from persistent_embodiment_v1 import atomic_json, digest, PersistentEmbodiment
    from coordinated_support import CoordinatedSupport

    source = Path(args.source).resolve()
    before_hash = sha(source)
    goal = MotionGoal.restore(json.loads(source.read_text()))
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    initial = goal.checkpoint()
    initial_fuel = goal.body.owner.owner.body.state.fuel_J
    rows = []
    physical = dict(substeps=0, invalid=0, minimum_support=1.)
    actual = False
    old_sim, old_step = PersistentEmbodiment._simulate, CoordinatedSupport.step

    def simulate(owner, *a, **kw):
        nonlocal actual
        previous = actual
        actual = kw.get('actual', False)
        try:
            return old_sim(owner, *a, **kw)
        finally:
            actual = previous

    def step(p, environment):
        frame = old_step(p, environment)
        if actual:
            physical['substeps'] += 1
            physical['invalid'] += int(not frame['balance']['model_valid'])
            physical['minimum_support'] = min(physical['minimum_support'], frame['contact']['joint_support_fraction'])
        return frame

    PersistentEmbodiment._simulate, CoordinatedSupport.step = simulate, step
    try:
        while goal.task['status'] == 'running':
            request = goal.request()
            receipt = goal.step()
            p = goal.body.owner.physical
            rows.append(dict(event_id=request['event_id'], request_sha256=digest(request),
                receipt_sha256=digest(receipt), elapsed=goal.task['elapsed'],
                counts=deepcopy(goal.task['counts']), cursor=deepcopy(p.star_started),
                landings=len(goal.task['landings']), time_s=p.state.time_s,
                fuel_J=p.body.state.fuel_J, reserve_J=p.body.state.reserve_J,
                fatigue=deepcopy(p.body.state.fatigue), status=goal.task['status'],
                selected=receipt['owner']['selected_action'], valid=receipt['owner']['physical_model_valid'],
                audit=receipt['whole_body_audit'], fuel_used_J=sum(x['fuel_used_J'] for x in receipt['trace'])))
            print(json.dumps(dict(pid=os.getpid(), elapsed=goal.task['elapsed'],
                landings=len(goal.task['landings']), phase=goal.task['phase'])), flush=True)
            if args.stop_landings and len(goal.task['landings']) >= args.stop_landings:
                break
        final = goal.checkpoint()
        atomic_json(out / 'goal.json', final)
        summary = dict(pid=os.getpid(), source_file_sha256=before_hash,
            initial_goal_sha256=initial['sha256'], final_goal_sha256=final['sha256'],
            native_sha256=final['payload']['body']['payload']['native']['sha256'],
            rows=rows, task=deepcopy(goal.task), physical=physical,
            fuel_debit_J=initial_fuel-goal.body.owner.owner.body.state.fuel_J,
            final_fuel_J=goal.body.owner.owner.body.state.fuel_J,
            final_reserve_J=goal.body.owner.owner.body.state.reserve_J,
            final_fatigue=deepcopy(goal.body.owner.owner.body.state.fatigue),
            final_time_s=goal.body.owner.physical.state.time_s,
            remaining={k:LIMITS[k]-goal.task['counts'][k] for k in LIMITS},
            source_unchanged=sha(source)==before_hash,
            official_state_advanced=False, model_api_calls=0)
        atomic_json(out / 'summary.json', summary)
        assert summary['source_unchanged']
        if args.stop_landings:
            # Real process termination after fsynced checkpoint; no live object
            # or Python binding can be carried to the fresh continuation owner.
            os._exit(75)
    finally:
        PersistentEmbodiment._simulate, CoordinatedSupport.step = old_sim, old_step


def run(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    cmd = [sys.executable, str(Path(__file__).resolve()), 'worker', '--native-root',
           str(Path(args.native_root).resolve())]
    logs = [(out/n).open('w') for n in ('baseline.log','partial.log','resumed.log')]
    baseline = subprocess.Popen(cmd+['--source',str(Path(args.source).resolve()),
        '--output',str(out/'baseline')], stdout=logs[0], stderr=subprocess.STDOUT)
    partial = subprocess.Popen(cmd+['--source',str(Path(args.source).resolve()),
        '--output',str(out/'partial'),'--stop-landings',str(args.stop_landings)],
        stdout=logs[1], stderr=subprocess.STDOUT)
    assert partial.wait() == 75, 'partial owner did not stop at durable boundary'
    resumed = subprocess.Popen(cmd+['--source',str(out/'partial/goal.json'),
        '--output',str(out/'resumed')], stdout=logs[2], stderr=subprocess.STDOUT)
    assert resumed.wait() == 0, 'fresh continuation failed'
    assert baseline.wait() == 0, 'baseline failed'
    for log in logs:
        log.close()
    a,b,c = [json.loads((out/n/'summary.json').read_text()) for n in ('baseline','partial','resumed')]
    compare = dict(full_trace_equal=a['rows']==b['rows']+c['rows'],
        final_goal_hash_equal=a['final_goal_sha256']==c['final_goal_sha256'],
        final_native_hash_equal=a['native_sha256']==c['native_sha256'],
        task_equal=a['task']==c['task'], remaining_equal=a['remaining']==c['remaining'],
        time_equal=a['final_time_s']==c['final_time_s'], energy_equal=a['final_fuel_J']==c['final_fuel_J'] and a['final_reserve_J']==c['final_reserve_J'],
        fatigue_equal=a['final_fatigue']==c['final_fatigue'],
        distinct_processes=len({a['pid'],b['pid'],c['pid']})==3,
        saved_boundary_equal=b['final_goal_sha256']==c['initial_goal_sha256'],
        valid_support=not any(x['physical']['invalid'] for x in (a,b,c)),
        sources_unchanged=all(x['source_unchanged'] for x in (a,b,c)))
    reference_hash = None
    if args.reference:
        reference_hash=json.loads(Path(args.reference).read_text())['sha256']
        compare['matches_prior_uninterrupted_endpoint']=a['final_goal_sha256']==reference_hash
    result=dict(schema='nasuraya-full-motion-recovery/1', compare=compare,
        accepted=all(compare.values()) and c['task']['status']=='completed',
        input_file_sha256=sha(args.source), source_goal_sha256=a['initial_goal_sha256'],
        source_landings=len(json.loads(Path(args.source).read_text())['payload']['task']['landings']),
        interruption_landings=len(b['task']['landings']), final_landings=len(c['task']['landings']),
        process_ids=[a['pid'],b['pid'],c['pid']], partial_exit_code=75,
        resumed_ticks=len(c['rows']), baseline_ticks=len(a['rows']),
        final_goal_sha256=c['final_goal_sha256'], final_native_sha256=c['native_sha256'],
        final_time_s=c['final_time_s'], final_fuel_J=c['final_fuel_J'],
        final_fatigue=c['final_fatigue'], counts=c['task']['counts'], remaining=c['remaining'],
        prior_reference_hash=reference_hash, official_state_advanced=False, model_api_calls=0,
        scope='full suffix from recorded accumulated-body goal; deliberate saved boundary, not mid-action recovery')
    (out/'comparison.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    assert result['accepted'], 'full continuation mismatch'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('run','worker'))
    parser.add_argument('--native-root',required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--stop-landings',type=int,default=0)
    parser.add_argument('--reference')
    args=parser.parse_args()
    if args.mode=='worker':worker(args)
    else:
        if args.stop_landings<=0:parser.error('run requires --stop-landings')
        run(args)
