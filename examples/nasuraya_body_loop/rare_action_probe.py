"""Finite exploratory native-body challenge for a selected stage-3 research goal.

Strictly bounded, no trained weights/algorithm changes, no API, no real actuators.
Cases are deliberately targeted from prior failure descriptions and are NOT blind
or independent evidence of generalization. Freeze training before all outcomes.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import itertools
import json
import math
import os
from pathlib import Path
import tempfile

from reflection_cycle import ReflectionCycle, canonical, digest
from synthetic_fixture import prepare_defaults, synthetic_origin
from persistent_embodiment_v1 import PersistentEmbodiment
from unified_body_v2 import UnifiedBody
from .experience import context, metrics
from .host import BodyLoop, KEY, SCHEMA, executed_body
from .self_knowledge import BUCKETS, forecast_action, score_action

SCHEMA_PROBE = 'nasuraya-stage3-rare-breath-probe/1'
CASES = tuple(dict(
    id=f'case-{i:02}', fatigue=fatigue, sleep_pressure=sleep, pain=pain,
    preferred='walk', duration_s=.1 if pain < .15 else .3,
) for i, (fatigue, sleep, pain) in enumerate(itertools.product(
    (.495, .515, .535, .565), (.34, .52, .70), (.10, .18)), 1))
EXPECTED_TRAINING = 40


def put(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                    allow_nan=False, indent=2) + '\n', encoding='utf-8')


def append(path: Path, value):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def read_strict(path: Path):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('duplicate JSON key')
            out[k] = v
        return out
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('non-finite JSON constant')))


def frozen_training(path: Path):
    raw = read_strict(path)
    if not isinstance(raw, dict) or set(raw) != {'episodes', 'sha256'}:
        raise ValueError('frozen training envelope missing')
    episodes = raw['episodes']
    if (not isinstance(episodes, list) or len(episodes) != EXPECTED_TRAINING
            or raw['sha256'] != digest(episodes)):
        raise ValueError('training sample count or digest mismatch')
    identifiers = set()
    for e in episodes:
        if not isinstance(e, dict) or e.get('kind') != 'observed_software_outcome':
            raise ValueError('not an observed training receipt')
        if e.get('id') in identifiers or not isinstance(e.get('id'), str):
            raise ValueError('duplicate training episode')
        identifiers.add(e['id'])
        if not isinstance(e.get('source'), str) or not e['source'].startswith('native-decision://'):
            raise ValueError('invalid training source')
        if e.get('preferred') not in ('walk', 'observe') or e.get('duration_s') not in (.1, .3):
            raise ValueError('training protocol mismatch')
    return raw


def modified_body(origin, case):
    owner = PersistentEmbodiment.restore(deepcopy(origin))
    before = owner.body()
    for key in owner.owner.body.state.fatigue:
        owner.owner.body.state.fatigue[key] = case['fatigue']
    owner.owner.body.pain.slow[sorted(owner.owner.body.pain.slow)[0]] = case['pain']
    owner.aux['sleep_pressure'] = case['sleep_pressure']
    sensory = owner.owner.memory.loop.sensory
    sensory.raw = sensory._owner_values(owner.physical)
    owner._record(before, owner.body(), 'external_input',
                  'predeclared exploratory stage-3 synthetic perturbation', 0.)
    return UnifiedBody.migrate(owner.checkpoint())


def session(path, case, body):
    config = {'fixture': 'synthetic-stage3-rare', 'mode': 'bounded',
              'max_actions': 1, 'context': 'stage3/rare/' + case['id'],
              'initial_checkpoint_sha256': body.checkpoint()['sha256']}
    with ReflectionCycle(path) as e:
        e.attach_runtime(KEY, body.checkpoint())
        e.db.execute('INSERT INTO meta VALUES(?,?)', (SCHEMA, canonical(config)))
    return BodyLoop(path)


def validate(output_dir):
    output = Path(output_dir)
    declared = read_strict(output / 'protocol.json')
    expected = dict(schema=SCHEMA_PROBE, cases=list(CASES), expected_training=EXPECTED_TRAINING,
                    purpose='exploratory synthetic rare-action stress test; not blind generalization',
                    no_weight_updates=True)
    if declared != dict(expected, protocol_sha256=digest(expected)):
        raise ValueError('protocol changed after outcomes')
    training = frozen_training(output / 'training.json')
    preds = [json.loads(x) for x in (output / 'predictions.jsonl').read_text().splitlines()]
    outcomes = [json.loads(x) for x in (output / 'outcomes.jsonl').read_text().splitlines()]
    if len(preds) != len(outcomes) or len(preds) != len(CASES):
        raise ValueError('incomplete native evaluation')
    scores, rare_count, other_count, protected = [], 0, 0, 0
    for case, pre, actual in zip(CASES, preds, outcomes):
        ident = case['id']
        if pre.get('id') != ident or actual.get('id') != ident or pre.get('case') != case:
            raise ValueError('case/order mismatch')
        if pre.get('training_sha256') != training['sha256'] or pre.get('training_count') != EXPECTED_TRAINING:
            raise ValueError('training leakage or inconsistency')
        forecast = forecast_action(training['episodes'], context=pre['context'],
                                   preferred=case['preferred'], duration_s=case['duration_s'])
        if forecast != pre['forecast']:
            raise ValueError('forecast altered after outcome')
        if actual.get('before_checkpoint_sha256') != pre.get('before_checkpoint_sha256'):
            raise ValueError('before checkpoint mismatch')
        source = actual.get('source')
        if not isinstance(source, str) or not source.startswith('native-decision://' + ident + '/'):
            raise ValueError('native outcome provenance missing')
        if actual.get('scored') is not True or actual.get('native_completed_cycles') != 1:
            raise ValueError('native action missing')
        if actual.get('replayed') is not False:
            raise ValueError('native trial replayed unexpectedly')
        if actual.get('actual_action') not in ('walk', 'observe', 'protect', 'slow_breath',
                                               'rapid_breath', 'rest', 'cool', 'sleep', 'other'):
            raise ValueError('unknown native action')
        audit = actual.get('body_audit')
        if not isinstance(audit, dict) or any(type(audit.get(k)) not in (int,float)
            or not math.isfinite(audit[k]) or abs(audit[k]) > bound
            for k, bound in (('energy_error_J',1e-6),('water_error_L',1e-8))):
            raise ValueError('native conservation error')
        recreated = score_action(forecast, actual['actual_action'], source)
        if recreated != actual.get('score'):
            raise ValueError('outcome scoring modified')
        scores.append(recreated)
        rare_count += actual['actual_action'] == 'slow_breath'
        other_count += actual['actual_action'] not in BUCKETS[:3]
        protected += actual['actual_action'] == 'protect'
    mean = lambda key: sum(r[key] for r in scores) / len(scores)
    brier = mean('brier')
    pooled_brier = mean('pooled_brier')
    conclusion = 'observed_taxonomy_limitation' if rare_count else 'no_slow_breath_in_challenge'
    summary = dict(schema=SCHEMA_PROBE, validation_passed=True,
        protocol_sha256=declared['protocol_sha256'], training_sha256=training['sha256'],
        cases=len(CASES), native_cycles=len(outcomes), slow_breath_events=rare_count,
        other_bucket_events=other_count, protect_events=protected,
        brier=brier, pooled_brier=pooled_brier,
        # The current model only knows walk/observe/protect/other. It literally
        # has no exact slow_breath prediction label. Do NOT call this recall > 0.
        exact_slow_breath_predictions=0,
        exact_slow_breath_recall=0.0 if rare_count else None,
        conclusion=conclusion, api_calls=0, physical_actuator_calls=0,
        learning_updates=0, weights_unchanged=True,
        limitation='Targeted synthetic stress conditions, not independent/blinded '
                   'generalization; exact slow_breath label absent from existing four-way model.')
    return summary


def run_probe(output_dir: Path, training_file: Path):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    training = frozen_training(training_file)
    expected = dict(schema=SCHEMA_PROBE, cases=list(CASES), expected_training=EXPECTED_TRAINING,
                    purpose='exploratory synthetic rare-action stress test; not blind generalization',
                    no_weight_updates=True)
    put(output / 'protocol.json', dict(expected, protocol_sha256=digest(expected)))
    put(output / 'training.json', training)
    prepare_defaults()
    origin = synthetic_origin()
    for case in CASES:
        body = modified_body(origin, case)
        with tempfile.TemporaryDirectory(prefix=case['id'] + '-', dir=output) as tmp:
            with session(Path(tmp) / 'native.sqlite', case, body) as loop:
                snapshot = loop.observe()
                ctx = context(metrics(snapshot))
                prior = forecast_action(training['episodes'], context=ctx,
                                        preferred=case['preferred'], duration_s=case['duration_s'])
                before = dict(id=case['id'], case=case, context=ctx,
                              before_checkpoint_sha256=snapshot['checkpoint_sha256'],
                              training_sha256=training['sha256'], training_count=len(training['episodes']),
                              forecast=prior)
                # A distinct fsync-ed file before calling the native simulator.
                append(output / 'predictions.jsonl', before)
                result = loop.step(decision_id=case['id'], duration_s=case['duration_s'],
                                   preferred_action=case['preferred'])
                native = loop.engine.get(case['id'])
                if not executed_body(native) or result.get('status') != 'complete':
                    raise RuntimeError('native outcome not complete')
                if native['request']['evidence'][0]['source_sha256'] != snapshot['checkpoint_sha256']:
                    raise ValueError('native observation does not match prior prediction')
                source = 'native-decision://' + case['id'] + '/' + digest(native)
                scored = score_action(prior, result['actual_action'], source)
                append(output / 'outcomes.jsonl', dict(id=case['id'], actual_action=result['actual_action'],
                        scored=True, source=source, score=scored, before_checkpoint_sha256=
                        snapshot['checkpoint_sha256'], after_checkpoint_sha256=
                        result['self_model_after']['checkpoint_sha256'], body_audit=result['body_audit'],
                        native_completed_cycles=loop.status()['completed_cycles'],
                        replayed=result['replayed']))
        # All native DBs are disposable. Native record SHA remains in each source.
    summary = validate(output)
    put(output / 'summary.json', summary)
    return summary
