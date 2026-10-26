"""Retrospective pain-support diagnosis, not a new held-out learning benchmark."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path

from synthetic_fixture import prepare_defaults
from unified_body_v2 import UnifiedBody
from .closed_loop_benchmark import fixture
from .native_preflight import preview
from .self_maintenance import digest


def receipt_evidence(receipt):
    owner = receipt['owner']
    return {'full_receipt_sha256': digest(receipt), 'event_id': receipt['event_id'],
            'revision': receipt['revision'], 'whole_body_audit': receipt['whole_body_audit'],
            'owner': {k: owner[k] for k in ('physical_model_valid', 'selected_action',
                      'start_minimum_state', 'outcome_minimum_state', 'resource_and_gas_audit')},
            'scope': 'native receipt excerpt; omitted regional packets/candidates are hash-bound'}


def run_diagnostic(output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    prepare_defaults()
    protocol = {'scope': 'retrospective native support regression; synthetic inputs',
                'intensities': [0., .1, .3, .5, .65, .8], 'actions': ['walk', 'observe'],
                'duration_s': .1, 'sleep_pressure': .2, 'muscle_tone': .3,
                'source_equations_modified': False, 'training': False}
    rows = []
    for intensity in protocol['intensities']:
        for action in protocol['actions']:
            body = fixture({'id': 'support-diagnostic', 'sleep_pressure': .2,
                            'muscle_tone': .3, 'warmup_walks': 0})
            pain = {'id': 'diagnostic-pain', 'location': 'forefoot_L', 'intensity': intensity,
                    'quality': 'pressure', 'cause': 'declared retrospective native regression',
                    'duration_s': 10.}
            if intensity:
                body.owner._external({'pain': [pain]})
            initial = body.checkpoint()
            predicted = preview(body, action)
            actual_body = UnifiedBody.restore(initial)
            at = (datetime.fromisoformat(actual_body.owner.wall_utc) + timedelta(seconds=.1)).isoformat()
            receipt = actual_body.cycle(event_id='diagnostic-actual', at_utc=at, duration_s=.1,
                                        requested=action, external={})
            frame = actual_body.owner.physical.last
            assert body.checkpoint() == initial
            assert predicted['physical_model_valid'] == receipt['owner']['physical_model_valid']
            assert predicted['failed_reason'] == frame['posture']['failed_reason']
            rows.append({'intensity': intensity, 'action': action, 'before_sha': initial['sha256'],
                         'preflight': predicted, 'actual_receipt': receipt_evidence(receipt),
                         'actual_frame': {k: deepcopy(frame[k]) for k in ('motor', 'contact', 'balance', 'ledger')},
                         'actual_posture': {k: frame['posture'][k] for k in ('phase', 'failed_reason')},
                         'source_unchanged': True,
                         'would_block_before_main_action': not predicted['physical_model_valid']})
    # Negative control: the original unexpected pain is absent at preflight.
    unseen = fixture({'id': 'unobserved-control', 'sleep_pressure': .2,
                      'muscle_tone': .3, 'warmup_walks': 0})
    p = preview(unseen, 'observe')
    at = (datetime.fromisoformat(unseen.owner.wall_utc) + timedelta(seconds=.1)).isoformat()
    surprise = unseen.cycle(event_id='surprise', at_utc=at, duration_s=.1, requested='observe',
                            external={'native': {'pain': [{'id': 'surprise-pain', 'location': 'forefoot_L',
                            'intensity': .8, 'quality': 'pressure', 'cause': 'unobserved negative control',
                            'duration_s': 10.}]}})
    assert p['physical_model_valid'] and not surprise['owner']['physical_model_valid']
    summary = {'cases': len(rows), 'known_input_validity_matches': len(rows),
               'known_input_would_block': sum(r['would_block_before_main_action'] for r in rows),
               'unknown_disturbance_detected_before_action': False,
               'api_calls': 0, 'learning_updates': 0, 'source_equations_modified': False,
               'new_independent_learning_improvement_established': False}
    report = {'schema': 'nasuraya-support-diagnostic/1', 'protocol': protocol,
              'protocol_sha256': digest(protocol), 'rows': rows, 'summary': summary,
              'unobserved_negative_control': {'preflight': p, 'actual_receipt': receipt_evidence(surprise)}}
    (out / 'support_diagnostic.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report
