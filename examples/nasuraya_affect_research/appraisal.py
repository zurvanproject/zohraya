"""Evidence-grounded replay into the EXISTING Nasuraya affect engine.

No new emotion taxonomy or native controller. This module makes a separate
research copy: no body mutation, model access, action, money, or background work.
Equations/thresholds are declared engineering assumptions, not human estimates.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SCHEMA = 'nasuraya-evidence-appraisal/1'
NATIVE_BLOBS = {
    'nasuraya_affective_layer_v01.py': 'c9ec0fe1f0474d14f6c98c93c0131aa1c784cce5',
    'nasuraya_emotion_spectrum_v01.py': '2b03e762e40659f68195627793db20e04f8465cc',
    'nasuraya_decision_core_v1.py': 'de18284b6daea5c75dd479fc3a27ec643f9e4c2a',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def unit(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('finite number in [0, 1] required')
    return float(value)


def sensory(observation):
    if observation.get('mode') != 'read_only_research':
        raise ValueError('native research observation required')
    if not re.fullmatch('[0-9a-f]{64}', observation.get('source_checkpoint_sha256', '')):
        raise ValueError('checkpoint digest required')
    q = observation['sensory']['q']
    if not isinstance(q, list) or len(q) != 6:
        raise ValueError('six declared native sensory features required')
    return [unit(x) for x in q]


def need_load(q):
    """Equal-weight deficits; same six variables as native research sensory q.

    NOT physiological truth. Mood, remembered fear, praise and prose are not
    inputs. A calmer mood alone cannot manufacture task or bodily progress.
    """
    energy, hydration, fatigue, pain, sleep_pressure, balance = q
    return (1-energy) + (1-hydration) + fatigue + pain + sleep_pressure + (1-balance)


def event_from_result(result):
    """Pure conversion. Structural checks are NOT authentication of a dict.

    Use preview_stored for records read from the existing controller's store.
    Only a resolved, completed native cycle is accepted. Unresolved effects
    are not imputed as failures or successes and never produce celebration.
    """
    if type(result.get('historical_native_cycles')) is not int or result['historical_native_cycles'] != 1:
        raise ValueError('one completed native cycle required')
    prediction = result['prediction']
    if (prediction.get('schema') != 'nasuraya-outcome-calibration/1' or
            prediction.get('target') != 'preferred_action_executed_by_native_body' or
            prediction.get('role') != 'report_only_no_decision_or_authority_writeback'):
        raise ValueError('existing native forecast contract required')
    outcome = prediction.get('outcome')
    if type(outcome) is not bool:
        raise ValueError('resolved boolean outcome required')
    source = prediction.get('outcome_source')
    if not isinstance(source, str) or not re.fullmatch(r'native-decision://[^/\s]+/[0-9a-f]{64}', source):
        raise ValueError('completed native receipt provenance required')
    preferred = result['preferred_action']
    if preferred not in ('walk', 'observe') or prediction['domain']['action'] != preferred:
        raise ValueError('forecast/action mismatch')
    actual = result['native_receipt']['actual_action']
    if not isinstance(actual, str) or outcome != (actual == preferred):
        raise ValueError('outcome disagrees with executed action')
    duration = prediction['domain']['duration_s']
    if type(duration) not in (int, float) or not math.isfinite(duration) or not .1 <= duration <= 1:
        raise ValueError('bounded native duration required')
    if not math.isclose(duration*10, round(duration*10), abs_tol=1e-9):
        raise ValueError('native time-grid mismatch')
    raw, calibrated = unit(prediction['raw_confidence']), unit(prediction['calibrated_confidence'])
    for name, p in (('raw_brier', raw), ('calibrated_brier', calibrated)):
        brier = unit(prediction[name])
        if not math.isclose(brier, (p-int(outcome))**2, rel_tol=0, abs_tol=1e-12):
            raise ValueError('forecast error inconsistent with receipt')
    before, after = sensory(result['research_before']), sensory(result['research_after'])
    d0, d1 = need_load(before), need_load(after)
    change = (d0-d1)/max(d0, d1, 1e-12)
    error = abs(calibrated-int(outcome))
    # Uncertainty of a binary prior and the measured outcome error are separate
    # evidence values; the larger value requests verification in the old engine.
    uncertainty = max(2*min(calibrated, 1-calibrated), error)
    signals = dict(success=float(outcome), prediction_error=error,
                   negative_prediction=max(0., calibrated-int(outcome)),
                   uncertainty=uncertainty, satisfaction=max(0., change),
                   threat_removed=max(0., change),
                   harm=max(0., after[3]-before[3]), value_goal=1.)
    event = dict(id='receipt-affect:'+hashlib.sha256(source.encode()).hexdigest(),
        source='synthetic_fixture', summary='appraisal of a recorded software-body outcome',
        signals=signals, confidence=1., energy=after[0],
        body=dict(pain=after[3], fatigue=after[2], hunger=1-after[0], thirst=1-after[1]),
        elapsed_hours=duration/3600.)
    evidence = dict(schema=SCHEMA, receipt_source=source,
        before_checkpoint=result['research_before']['source_checkpoint_sha256'],
        after_checkpoint=result['research_after']['source_checkpoint_sha256'],
        preferred_action_executed=outcome, body_need_change=change,
        forecast_error=error, prior_uncertainty=2*min(calibrated, 1-calibrated),
        raw_confidence=raw, calibrated_confidence=calibrated,
        outcome_scope='preferred action executed, NOT task/route completion',
        evidence_confidence_scope='trusted software receipt, NOT empirical forecast calibration')
    return event, evidence


def native_affect():
    """Reuse source-pinned retained modules. Import alone performs no transition."""
    root = Path(__file__).resolve().parents[2]
    folder = root/'runtimes/tadash_body/retained_extensions'
    for filename, expected in NATIVE_BLOBS.items():
        raw = (folder/filename).read_bytes()
        actual = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if actual != expected:
            raise ValueError('native affect source changed: '+filename)
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    import nasuraya_affective_layer_v01 as native
    for name in NATIVE_BLOBS:
        module = sys.modules[name[:-3]]
        if Path(module.__file__).resolve() != (folder/name).resolve():
            raise ValueError('unexpected native module')
    return native


def preview(affect_state, result, *, affect_enabled=True):
    """One explicit counterfactual transition on a copy; native engine is reused."""
    before = digest(dict(state=affect_state, result=result))
    event, evidence = event_from_result(result)
    native = native_affect()
    state = deepcopy(affect_state)
    record = native.transition(state, event, affect_enabled=affect_enabled)
    if digest(dict(state=affect_state, result=result)) != before:
        raise RuntimeError('input mutated')
    return dict(state=state, record=record, evidence=evidence,
                body_actions_executed=0, model_calls=0,
                role='isolated_research_copy_no_decision_writeback')


def preview_stored(controller, request_id, affect_state, *, affect_enabled=True):
    """Read an existing completed result. Never invoke controller.step().

    The controller validates its existing source/budget/integrity envelope.
    Host and filesystem remain trusted; a digest is not a digital signature.
    """
    from examples.nasuraya_research.controller import BoundedResearchController
    if not isinstance(controller, BoundedResearchController):
        raise ValueError('existing bounded research controller required')
    state = controller._load()
    intent = state['intents'].get(request_id)
    if intent is None or intent.get('result') is None:
        raise ValueError('completed stored result required; no action or retry')
    return preview(affect_state, intent['result'], affect_enabled=affect_enabled)
