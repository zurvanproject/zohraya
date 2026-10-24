"""Separate aesthetic ratings, reference identity and designed affect.

No model is downloaded or invoked. Ratings are explicit operator declarations,
externally produced model estimates, or synthetic fixtures. A file SHA256 can
establish identical bytes only; it cannot recognize a face in a new rendering.
The coefficients below are authored engineering policy, not fitted psychology.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = 'nasuraya-visual-appraisal/1'
REFERENCE = Path(__file__).with_name('reference.json')
RATING_KINDS = {'operator_rating', 'model_estimate', 'synthetic_fixture'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':'))


def text(value, name, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('bounded nonempty string required: ' + name)
    return value


def sha(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('lowercase SHA256 required')
    return value


def unit(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError('finite number in [0,1] required')
    return float(value)


def reference(value=None):
    value = deepcopy(value) if value is not None else json.loads(REFERENCE.read_text())
    if not isinstance(value, dict) or set(value) != {
            'schema', 'character', 'filename', 'sha256', 'status', 'approved_at'}:
        raise ValueError('reference contract mismatch')
    if value['schema'] != 'nasuraya-visual-reference/1' or value['status'] != 'user_approved_provisional':
        raise ValueError('explicitly approved provisional reference required')
    for key in ('character', 'filename', 'approved_at'): text(value[key], key)
    sha(value['sha256'])
    return value


def rating(row):
    if not isinstance(row, dict) or set(row) != {'value', 'confidence', 'kind', 'source_ref'}:
        raise ValueError('rating value, confidence, kind and source_ref required')
    if row['kind'] not in RATING_KINDS:
        raise ValueError('unknown rating provenance')
    return dict(value=unit(row['value']), confidence=unit(row['confidence']),
                kind=row['kind'], source_ref=text(row['source_ref'], 'rating source'))


def appraise(observation, *, approved_reference=None, image_path=None):
    """Pure report and native-event preparation; missing ratings stay unknown."""
    ref = reference(approved_reference)
    required = {'id', 'image_sha256', 'subject', 'source', 'source_ref', 'ratings'}
    if (not isinstance(observation, dict) or not required <= set(observation)
            or set(observation) - required - {'identity_similarity'}):
        raise ValueError('observation contract mismatch')
    obs = deepcopy(observation)
    text(obs['id'], 'observation id', 90)
    sha(obs['image_sha256']); text(obs['source_ref'], 'observation source')
    if obs['subject'] not in {'self', 'other', 'unknown'}:
        raise ValueError('explicit subject attribution required')
    if obs['source'] not in {'operator_report', 'explicit_user_message', 'synthetic_fixture'}:
        raise ValueError('observation provenance required')
    if not isinstance(obs['ratings'], dict) or set(obs['ratings']) - {'beauty', 'proportion'}:
        raise ValueError('only beauty and proportion ratings accepted')
    obs['ratings'] = {key: rating(row) for key, row in obs['ratings'].items()}
    if image_path is not None:
        if hashlib.sha256(Path(image_path).read_bytes()).hexdigest() != obs['image_sha256']:
            raise ValueError('ratings do not refer to the supplied image bytes')
    identity = dict(status='unknown', similarity=None, confidence=0., source_ref=None)
    estimated = obs.get('identity_similarity')
    if estimated is not None:
        if not isinstance(estimated, dict) or set(estimated) != {
                'value', 'confidence', 'kind', 'source_ref', 'reference_sha256'}:
            raise ValueError('identity estimate must bind the approved reference')
        if sha(estimated['reference_sha256']) != ref['sha256']:
            raise ValueError('identity estimate targets a different reference')
        estimate = rating({k: v for k, v in estimated.items() if k != 'reference_sha256'})
        obs['identity_similarity'] = dict(estimate, reference_sha256=ref['sha256'])
        identity = dict(status='declared_estimate', similarity=estimate['value'],
                        confidence=estimate['confidence'], source_ref=estimate['source_ref'])
    if obs['image_sha256'] == ref['sha256']:
        if estimated is not None and estimated['value'] != 1.:
            raise ValueError('estimate contradicts exact reference bytes')
        identity = dict(status='exact_reference_bytes' if image_path is not None else 'matching_declared_hash',
                        similarity=1., confidence=1.,
                        source_ref='sha256:' + ref['sha256'])
    beauty = obs['ratings'].get('beauty')
    proportion = obs['ratings'].get('proportion')
    aesthetic = beauty['value'] * beauty['confidence'] if beauty else 0.
    own = obs['subject'] == 'self'
    match = identity['similarity']
    recognized = own and match is not None and match >= .8 and identity['confidence'] >= .5
    uncertain_self = own and (match is None or identity['confidence'] < .5)
    drift = own and match is not None and match < .8 and identity['confidence'] >= .5
    reasons = []
    if uncertain_self: reasons.append('identity_unknown_or_low_confidence')
    if drift: reasons.append('identity_drift')
    proportion_issue = proportion and proportion['confidence'] >= .5 and proportion['value'] < .6
    if proportion_issue:
        reasons.append('declared_proportion_issue')
    signals = {'excellence': .6 * aesthetic,
               'satisfaction': .5 * aesthetic + (.25 * match * identity['confidence'] if recognized else 0.),
               'prediction_error': (1. - match) * identity['confidence'] if drift else 0.,
               'uncertainty': .9 if uncertain_self or drift or proportion_issue else 0.}
    # Beauty never supplies intelligence, morality, relationship trust, shame,
    # attraction, self-worth, or an achievement signal. Appearance is not merit.
    report = dict(schema=SCHEMA, observation=obs, approved_reference=ref,
        image_bytes_verified=image_path is not None, identity=identity,
        subject_attribution='caller_declared', aesthetic_rating=beauty,
        proportion_rating=proportion, reasons=reasons,
        recommendation='verify_identity' if uncertain_self or drift else (
            'review_proportions' if 'declared_proportion_issue' in reasons else 'acknowledge_image'),
        policy_scope='authored appraisal; ratings and similarities are unvalidated caller declarations',
        subjective_experience_established=False, self_worth_change=0., ethical_merit_change=0.)
    event = dict(id=obs['id'], source=obs['source'], confidence=1., signals=signals,
                 summary=canonical(report))
    return dict(report=report, social_event=event)


def apply(loop, observation, *, approved_reference=None, image_path=None):
    """One explicit budgeted native cycle; the host owns persistence and replay."""
    prepared = appraise(observation, approved_reference=approved_reference, image_path=image_path)
    decision_id = 'visual:' + observation['id']
    if loop.engine.get(decision_id) is None:
        loop.observe()
    native = loop.step(decision_id=decision_id, preferred_action='observe',
                       social_event=prepared['social_event'])
    record = loop.engine.get(decision_id)
    checkpoint = (record.get('actual_outcome') or {}).get('body_checkpoint')
    # Use this execution's historical receipt on replay, not the latest body.
    affect_record = checkpoint['payload']['affect']['history'][-1] if checkpoint else None
    return dict(report=prepared['report'], native_receipt=native,
                affect_transition=deepcopy(affect_record), model_api_calls=0)
