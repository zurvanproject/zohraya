"""Isolated source-verified native worker. Never runs in the repository runtime."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def run(request, staging):
    sys.path.insert(0, str(staging))
    os.chdir(staging)
    from synthetic_fixture import prepare_defaults, synthetic_body
    from run_reflection_demo import sleep_fixture
    from unified_body_v2 import UnifiedBody
    from examples.nasuraya_research.native_snapshot import snapshot
    from examples.dios_nous.unified.body import project_native_snapshot, MODEL
    from examples.tadash_interoception.state import digest
    prepare_defaults()
    if request['checkpoint'] is None:
        body = sleep_fixture() if request['fixture'] == 'sleep' else synthetic_body()
        receipt = None
    else:
        body = UnifiedBody.restore(request['checkpoint'])
        at = (datetime.fromisoformat(body.owner.wall_utc) + timedelta(seconds=request['duration'])).isoformat()
        external = {'sensors': {'touch': {'value': request['touch'],
                    'source_id': 'shared-session-palm-state-v1',
                    'sampled_at_s': body.owner.owner.body.state.time_s,
                    'kind': 'declared_simulated_input'}}}
        result = body.cycle(event_id=request['event_id'], at_utc=at,
                            duration_s=request['duration'], external=external,
                            requested=request['requested'], expected_revision=body.revision)
        receipt = {'requested': request['requested'], 'executed': result['owner']['selected_action'],
                   'body_veto': result['owner']['selected_action'] != request['requested'],
                   'audit': result['whole_body_audit'], 'touch': body.modules['senses']['samples']['touch'],
                   'native_prediction_error': result['owner']['prediction']['mean_scaled_absolute_error'],
                   'systems': result['systems'], 'regional_packets': result['regional_packets']}
    return capture(body, receipt)


def capture(body, receipt):
    from examples.nasuraya_research.native_snapshot import snapshot
    from examples.dios_nous.unified.body import project_native_snapshot, MODEL
    from examples.tadash_interoception.state import digest
    checkpoint = body.checkpoint()
    return {'checkpoint': checkpoint,
            'export': project_native_snapshot(snapshot(body), model_id=MODEL,
                                               finite_stocks=body.owner.body()['finite_stocks']),
            'receipt': receipt, 'neural_ticks': body.modules['neural']['integration_ticks'],
            'affect': body.affect['affect'], 'somatic_feedback': body.affect['somatic'],
            'affect_state_sha': digest(body.affect), 'model': MODEL,
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
