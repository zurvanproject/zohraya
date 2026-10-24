"""Constructed contract demonstration, not a blinded aesthetic benchmark."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from examples.nasuraya_body_loop.host import BodyLoop
from .appraisal import apply
from .fixtures import observation, similarity


def cases():
    rows = []
    for name, obs, expected in (
        ('self_beautiful', observation(), 'acknowledge_image'),
        ('other_same_beauty', observation(subject='other'), 'acknowledge_image'),
        ('self_unknown_identity', observation(image_sha256='1'*64), 'verify_identity'),
        ('self_low_beauty', observation(beauty=.1), 'acknowledge_image'),
        ('self_missing_beauty', observation(beauty=None), 'acknowledge_image')):
        obs['id'] = name; rows.append((name, obs, expected))
    drift = observation(beauty=1., image_sha256='1'*64)
    drift['id'] = 'beautiful_identity_drift'; drift['identity_similarity'] = similarity(.2)
    rows.append(('beautiful_identity_drift', drift, 'verify_identity'))
    prop = observation(); prop['id'] = 'declared_short_arms'
    prop['ratings']['proportion'] = dict(value=.2, confidence=1., kind='synthetic_fixture',
                                        source_ref='fixture://declared-short-arms')
    rows.append(('declared_short_arms', prop, 'review_proportions'))
    uncertain = observation(image_sha256='1'*64); uncertain['id'] = 'uncertain_identity'
    uncertain['identity_similarity'] = similarity(.95, .2)
    rows.append(('uncertain_identity', uncertain, 'verify_identity'))
    return rows


def evaluate(output_dir=None):
    with tempfile.TemporaryDirectory(prefix='aesthetic-comparison-') as tmp:
        output = Path(output_dir) if output_dir else Path(tmp)
        if output_dir: output.mkdir(mode=0o700, parents=True, exist_ok=False)
        rows = []
        for name, obs, expected in cases():
            with BodyLoop.start(output / (name + '-baseline.sqlite'), max_actions=1) as baseline:
                baseline.observe(); base = baseline.step(preferred_action='observe')
                base_affect = deepcopy(baseline.body().affect)
            with BodyLoop.start(output / (name + '-appraisal.sqlite'), max_actions=1) as treatment:
                value = apply(treatment, obs)
                after = treatment.body().affect
                rows.append(dict(case=name, observation=obs, expected_recommendation=expected,
                    recommendation=value['report']['recommendation'],
                    recommendation_matches=value['report']['recommendation'] == expected,
                    baseline_plan=base_affect['history'][-1]['plan']['action'],
                    appraisal_plan=value['affect_transition']['plan']['action'],
                    native_action_baseline=base['actual_action'],
                    native_action_appraisal=value['native_receipt']['actual_action'],
                    affect_delta={key: after['affect'][key] - base_affect['affect'][key]
                                  for key in ('admiration', 'contentment', 'surprise', 'shame', 'trust')},
                    rating_scope=value['report']['policy_scope']))
        result = dict(schema='nasuraya-aesthetic-evaluation/1', constructed_cases=len(rows),
            recommendation_matches=sum(row['recommendation_matches'] for row in rows),
            native_cycles_executed=2*len(rows), model_api_calls=0,
            evidence_scope='constructed synthetic ratings and declared hashes; not image perception or felt beauty',
            self_other_beauty_invariant=rows[0]['observation']['ratings'] == rows[1]['observation']['ratings'],
            rows=rows)
        if output_dir:
            (output / 'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        return result
