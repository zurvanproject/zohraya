"""Isolated source-verified native worker. Never runs in the repository runtime."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def run(request, staging):
    from .profile import CURRENT, LEGACY, prepare
    model_id=request.get('body_profile',CURRENT)
    if model_id not in (CURRENT,LEGACY): raise ValueError('unknown native body profile')
    profile_receipt=prepare(staging) if model_id==CURRENT else None
    sys.path.insert(0, str(staging))
    os.chdir(staging)
    from synthetic_fixture import prepare_defaults, synthetic_body, synthetic_origin
    from run_reflection_demo import sleep_fixture
    from unified_body_v2 import UnifiedBody
    from examples.nasuraya_research.native_snapshot import snapshot
    from examples.dios_nous.unified.body import project_native_snapshot, MODEL
    from examples.tadash_interoception.state import digest
    prepare_defaults()
    if request['checkpoint'] is None:
        if request['fixture'] == 'sleep':
            body = sleep_fixture()
        elif request['fixture'] == 'transient_pain':
            # Explicit initial fixture intervention, followed only by the original
            # native decay equations. No later reset of pain or physiology.
            from persistent_embodiment_v1 import PersistentEmbodiment
            owner = PersistentEmbodiment.restore(synthetic_origin())
            before = owner.body()
            # One unique maximum avoids an inherited insertion-order tie in the
            # legacy location readout when JSON is restored in a fresh process.
            region = sorted(owner.owner.body.pain.slow)[0]
            owner.owner.body.pain.slow[region] = 1.0
            owner._record(before, owner.body(), 'external_input',
                          'declared transient nociceptive fixture; not a physical measurement', 0.)
            body = UnifiedBody.migrate(owner.checkpoint())
            body.migration['fixture_intervention'] = 'initial nociceptive slow channel '+region+'=1.0; native decay only thereafter'
        elif request['fixture'] == 'normal':
            body = synthetic_body()
        else:
            raise ValueError('unknown native fixture')
        receipt = None
    else:
        body = UnifiedBody.restore(request['checkpoint'])
        before_pose=body.owner.pose()['parts']
        before_steps=body.owner.physical.state.walk_steps
        origin_sha = body.checkpoint()['sha256']
        at = (datetime.fromisoformat(body.owner.wall_utc) + timedelta(seconds=request['duration'])).isoformat()
        external = {'sensors': {'touch': {'value': request['touch'],
                    'source_id': request.get('touch_source','shared-session-palm-state-v1'),
                    'sampled_at_s': body.owner.owner.body.state.time_s,
                    'kind': 'declared_simulated_input'}}}
        result = body.cycle(event_id=request['event_id'], at_utc=at,
                            duration_s=request['duration'], external=external,
                            requested=request['requested'], expected_revision=body.revision)
        if request.get('mode') == 'preflight':
            return {'kind': 'counterfactual_copy_not_committed_execution',
                    'origin_checkpoint_sha': origin_sha, 'requested': request['requested'],
                    'selected': result['owner']['selected_action'],
                    'actual_session_cycles_committed': 0}
        receipt = {'requested': request['requested'], 'executed': result['owner']['selected_action'],
                   'body_veto': result['owner']['selected_action'] != request['requested'],
                   'audit': result['whole_body_audit'], 'touch': body.modules['senses']['samples']['touch'],
                   'native_prediction_error': result['owner']['prediction']['mean_scaled_absolute_error'],
                   'systems': result['systems'], 'regional_packets': result['regional_packets'],
                   'execution_scope':'native action selection; completed locomotion measured separately',
                   'physical_outcome':{'walk_touchdowns':body.owner.physical.state.walk_steps-before_steps,
                       'foot_displacement_m':{side:[b-a for a,b in zip(before_pose['foot_'+side],
                           body.owner.pose()['parts']['foot_'+side])] for side in ('L','R')}}}
    checkpoint = body.checkpoint()
    return {'checkpoint': checkpoint,
            'export': project_native_snapshot(snapshot(body), model_id=model_id,
                                               finite_stocks=body.owner.body()['finite_stocks']),
            'receipt': receipt, 'neural_ticks': body.modules['neural']['integration_ticks'],
            'affect': body.affect['affect'], 'somatic_feedback': body.affect['somatic'],
            'affect_state_sha': digest(body.affect), 'model': model_id,
            'profile_receipt': profile_receipt,
            'physical_parameters': {'mass_kg':body.owner.physical.design['mass_kg'],
                'weight_N':body.owner.physical.weight,'tail_length_m':body.owner.physical.design['tail_length_m'],
                'walk_touchdowns':body.owner.physical.state.walk_steps,'pose':body.owner.pose()},
            'clock': body.owner.owner.body.state.time_s}


def main():
    from examples.nasuraya_body_loop.__main__ import SOURCE, verified_sources
    request = json.load(sys.stdin)
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-common-body-') as tmp:
        staging = Path(tmp)
        for name in manifest:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        result = run(request, staging)
        os.chdir(staging.parent)
    verified_sources()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
