"""Before/after availability check on an isolated recorded MotionGoal copy.

The baseline directory must hold motion_journal.py and recovery_fault_worker.py
from commit 3e704eb6280b7baeccbb78566a1ee89d60a632a7. Both owners are killed
inside their final SQLite transaction after completing the same native tick.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


def run(args):
    native=Path(args.native_root).resolve()
    current=Path(__file__).resolve().parent
    baseline=Path(args.baseline_root).resolve()
    source=Path(args.source).resolve()
    output=Path(args.output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(native))
    from motion_goal import MotionGoal
    from motion_journal import MotionJournal
    from persistent_embodiment_v1 import digest, atomic_json
    from unified_body_v2 import UnifiedBody
    from coordinated_support import CoordinatedSupport

    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    saved=json.loads(source.read_text())
    initial=MotionGoal.restore(saved)
    initial_time=initial.body.owner.physical.state.time_s
    initial_fuel=initial.body.owner.owner.body.state.fuel_J
    request=initial.request()

    spec=importlib.util.spec_from_file_location('old_motion_journal',baseline/'motion_journal.py')
    old=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    old_store=old.MotionJournal.create(output/'baseline.sqlite',initial)
    new_store=MotionJournal.create(output/'improved.sqlite',MotionGoal.restore(saved))
    environment={**os.environ,'PYTHONPATH':os.pathsep.join((str(current),str(native)))}
    for label,root in (('baseline',baseline),('improved',current)):
        result=subprocess.run([sys.executable,str(root/'recovery_fault_worker.py'),
            '--native-root',str(native),'--journal',str(output/(label+'.sqlite')),
            '--marker',str(output/(label+'_crash.json')),'--fault','writing'],
            env=environment,text=True,capture_output=True,timeout=240)
        if result.returncode!=86:
            raise AssertionError((label,result.returncode,result.stderr))

    old_before=old_store.inspect()
    try:old_store.load()
    except old.UnknownMotionOutcome:baseline_blocked=True
    else:raise AssertionError('baseline unexpectedly recovered')
    assert old_store.inspect()==old_before

    expected=MotionGoal.restore(saved)
    first_receipt=expected.step()
    expected_after_tick=expected.checkpoint()
    # Forbid both native execution and prediction throughout reconciliation.
    with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('repeated native cycle')), \
         patch.object(CoordinatedSupport,'step',side_effect=AssertionError('repeated physical integration')):
        recovery=new_store.recover()
        recovered=new_store.load()
        assert recovered.checkpoint()==expected_after_tick
        retry=new_store.step(event_id=request['event_id'],expected_head=saved['sha256'])
        assert retry==first_receipt
        assert new_store.load().checkpoint()==expected_after_tick
    # Make progress after recovering, with normal native arbitration enabled.
    receipt_hashes=[digest(first_receipt)]
    for _ in range(2):
        goal=new_store.load()
        receipt=new_store.step(event_id=goal.request()['event_id'],expected_head=goal.checkpoint()['sha256'])
        expected_receipt=expected.step()
        assert receipt==expected_receipt
        receipt_hashes.append(digest(receipt))
    final=new_store.load()
    assert final.checkpoint()==expected.checkpoint()
    atomic_json(output/'advanced_goal.json',final.checkpoint())
    result=dict(schema='nasuraya-verified-outcome-improvement/1',
        source_sha256=source_hash,source_goal_sha256=saved['sha256'],
        baseline_commit='3e704eb6280b7baeccbb78566a1ee89d60a632a7',
        baseline_blocked=baseline_blocked,baseline_committed_ticks_after_crash=0,
        improved_recovery=recovery,duplicate_receipt_exact=retry==first_receipt,
        improved_committed_ticks_after_recovery=1,improved_committed_ticks_after_continuation=3,
        baseline_head_unchanged=old_store.inspect()==old_before,
        before_elapsed=initial.task['elapsed'],after_elapsed=final.task['elapsed'],
        before_time_s=initial_time,after_time_s=final.body.owner.physical.state.time_s,
        before_fuel_J=initial_fuel,after_fuel_J=final.body.owner.owner.body.state.fuel_J,
        after_fatigue=final.body.owner.owner.body.state.fatigue,
        final_goal_sha256=final.checkpoint()['sha256'],
        uninterrupted_three_tick_goal_sha256=expected.checkpoint()['sha256'],
        actual_receipts_sha256=receipt_hashes,source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,
        private_practice_copy_advanced=True,official_state_advanced=False,model_api_calls=0,
        scope='local durable completed outcome; missing/partial outcomes remain blocked')
    assert result['source_unchanged'] and recovery['native_actions_executed']==0
    atomic_json(output/'comparison.json',result)
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native-root','baseline-root','source','output'):
        parser.add_argument('--'+name,required=True)
    run(parser.parse_args())
