"""Predeclared train/validation/test evaluation using actual native body receipts.

All validation predictions are persisted before execution. One configuration
is selected using validation only; it is frozen before any held-out body runs.
The unchanged categorical estimator sees exactly the same training receipts.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import time

from reflection_cycle import ReflectionCycle, canonical, digest
from synthetic_fixture import prepare_defaults, synthetic_origin
from unified_body_v2 import UnifiedBody, PersistentEmbodiment
from . import continuous_self_knowledge as continuous
from .experience import context, metrics
from .host import BodyLoop, KEY, SCHEMA, executed_body
from .self_knowledge import BUCKETS, forecast_action
from .self_knowledge_eval import _append, _write


ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = [dict(continuous.DEFAULT_CONFIG)] + [
    dict(continuous.DEFAULT_CONFIG, radius=radius, neighbors=neighbors, prior_strength=prior)
    for radius in (.08, .16, .28) for neighbors in (3, 9) for prior in (1., 4.)]
PROFILES = {
    'smoke': dict(seeds=[531], train=8, validation=4, test=4, novelty=2, rounds=2),
    'full': dict(seeds=[531, 947, 1561], train=72, validation=24, test=64, novelty=8, rounds=2),
}


def cases(seed, size, split):
    rng = random.Random(seed * 101 + {'train':1, 'validation':2, 'test':3, 'novelty':4}[split])
    rows = []
    for i in range(size):
        if i < size//2 and split != 'novelty':
            axis = ('fatigue', 'sleep', 'pain')[i%3]
            changes = {axis: round(rng.uniform(.025, .975), 6)}
        else:
            changes = {key: round(rng.uniform(.025, .975), 6) for key in ('fatigue', 'sleep', 'pain')}
        rows.append(dict(id=f'{split}-{i:03}', changes=changes))
    return rows


def protocol(profile):
    if profile not in PROFILES:
        raise ValueError('known finite evaluation profile required')
    settings = deepcopy(PROFILES[profile])
    inputs = {str(seed): {split: cases(seed, settings[split], split)
              for split in ('train','validation','test','novelty')} for seed in settings['seeds']}
    names = ('continuous_self_knowledge.py', 'continuous_self_eval.py', 'experience.py',
             'self_knowledge.py', 'host.py', '__main__.py', 'worker.py')
    source_hashes = {name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                     for name in names}
    native_manifest = ROOT/'runtimes/tadash_body/PUBLIC_FILES_SHA256.json'
    return dict(schema='nasuraya-continuous-self-evaluation/1', profile=profile,
        settings=settings, inputs=inputs, preferences=['walk','observe'], durations_s=[.1,.3],
        novelty_duration_s=.2, candidates=CANDIDATES, source_hashes=source_hashes,
        native_manifest_sha256=hashlib.sha256(native_manifest.read_bytes()).hexdigest(),
        order='all training folds; all validation folds; select once; all test folds; novelty',
        selection='minimum mean validation multiclass Brier; fixed candidate index breaks ties',
        fit='train for validation; train+validation for test; never fit held-out outcomes',
        criteria=dict(relative_brier_reduction_vs_v1=.10, no_worse_than_pooled=True,
                      supported_accuracy=.85, supported_protect_recall=.5,
                      novelty_assertions=0, max_fold_relative_brier_regression=.05),
        scope='constructed synthetic starting states; two correlated cycles per trajectory; not IID')


def make_body(origin, changes):
    owner = PersistentEmbodiment.restore(deepcopy(origin)); before = owner.body()
    if 'fatigue' in changes:
        for key in owner.owner.body.state.fatigue:
            owner.owner.body.state.fatigue[key] = changes['fatigue']
    if 'pain' in changes:
        owner.owner.body.pain.slow[sorted(owner.owner.body.pain.slow)[0]] = changes['pain']
    if 'sleep' in changes:
        owner.aux['sleep_pressure'] = changes['sleep']
    sensory = owner.owner.memory.loop.sensory
    sensory.raw = sensory._owner_values(owner.physical)
    owner._record(before, owner.body(), 'external_input',
                  'predeclared self-forecast evaluation '+canonical(changes), 0.)
    body = UnifiedBody.migrate(owner.checkpoint())
    UnifiedBody.restore(json.loads(canonical(body.checkpoint())))
    return body


def start_session(path, name, body, budget):
    config = dict(fixture='synthetic-generalization', mode='bounded', max_actions=budget,
        context='forecast-eval/'+name, initial_checkpoint_sha256=body.checkpoint()['sha256'])
    with ReflectionCycle(path) as engine:
        engine.attach_runtime(KEY, body.checkpoint())
        engine.db.execute('INSERT INTO meta VALUES(?,?)', (SCHEMA, canonical(config)))
    return BodyLoop(path)


def without_feedback(history):
    rows = deepcopy(history)
    for row in rows:
        row['feedback'] = dict(walk=None, observe=None)
    return rows


def shuffled_observations(history, seed):
    rows = deepcopy(history); groups = {}
    for i, row in enumerate(rows):
        groups.setdefault((row['preferred'], row['duration_s'], canonical(row['feedback'])), []).append(i)
    rng = random.Random(seed)
    for indexes in groups.values():
        observations = [rows[i]['before'] for i in indexes]
        rng.shuffle(observations)
        for i, observation in zip(indexes, observations):
            rows[i]['before'] = observation
    return rows


def forecasts(history, before, feedback, preferred, duration, split, selected=None):
    args = dict(before=before, feedback=feedback, preferred=preferred, duration_s=duration)
    old = forecast_action(history, context=context(before), preferred=preferred, duration_s=duration)
    result = dict(v1=old, default=continuous.forecast_action(history, **args))
    if split == 'validation':
        result['candidates'] = [continuous.forecast_action(history, config=c, **args) for c in CANDIDATES]
    if split in ('test','novelty'):
        result['selected'] = continuous.forecast_action(history, config=selected, **args)
        result['without_feedback'] = continuous.forecast_action(without_feedback(history),
            config=selected, **dict(args, feedback=None))
        result['shuffled_body'] = continuous.forecast_action(shuffled_observations(history, 701),
            config=selected, **args)
    # The full evidence lists are already stored once in the frozen histories.
    # Retain each full forecast's digest, vectors, support and small local list,
    # avoiding millions of duplicated receipt IDs in the evaluation artifact.
    def compact(value):
        fields = ('distribution','pooled_distribution','samples','pooled_samples',
                  'status','predicted_action','nearest_distance','agreement','model_digest')
        item = {key:deepcopy(value[key]) for key in fields if key in value}
        item.update(schema='nasuraya-evaluation-forecast-vector/1',
                    original_schema=value['schema'],full_forecast_sha256=digest(value))
        if len(value.get('source_ids',[])) <= 9:
            item['local_source_ids'] = list(value.get('source_ids',[]))
        return item
    return {key:[compact(v) for v in value] if isinstance(value,list) else compact(value)
            for key,value in result.items()}


def _bucket(action):
    return action if action in BUCKETS[:3] else 'other'


def summarize(rows, name):
    if not rows:
        return dict(n=0, brier=None, raw_accuracy=None, supported_accuracy=None, coverage=0.)
    losses, correct, bins, asserted = [], [], [[] for _ in range(10)], []
    protect_total = protect_claims = protect_correct = 0
    statuses = Counter()
    for row in rows:
        f = row['forecasts']['v1' if name == 'pooled' else name]
        p = f['pooled_distribution'] if name == 'pooled' else f['distribution']
        actual = _bucket(row['actual_action']); predicted = max(BUCKETS, key=p.get)
        confidence = p[predicted]; ok = predicted == actual
        losses.append(sum((p[a] - (a == actual))**2 for a in BUCKETS))
        correct.append(ok); bins[min(9,int(confidence*10))].append((confidence,ok))
        label = (predicted if f['pooled_samples'] >= 3 else None) if name == 'pooled' else f['predicted_action']
        if label is not None:
            asserted.append(label == actual)
        protect_total += actual == 'protect'
        protect_claims += label == 'protect'
        protect_correct += label == 'protect' and actual == 'protect'
        statuses[f['status']] += 1
    ece = sum(abs(sum(p for p,_ in group)-sum(ok for _,ok in group)) for group in bins)/len(rows)
    return dict(n=len(rows), brier=sum(losses)/len(rows), raw_accuracy=sum(correct)/len(rows),
        top_label_ece=ece, coverage=len(asserted)/len(rows), asserted=len(asserted),
        supported_accuracy=sum(asserted)/len(asserted) if asserted else None,
        actual_protect=protect_total, claimed_protect=protect_claims, correct_protect=protect_correct,
        supported_protect_recall=protect_correct/protect_total if protect_total else None,
        supported_protect_precision=protect_correct/protect_claims if protect_claims else None,
        statuses=dict(statuses))


def run_evaluation(output_dir, profile='full'):
    output = Path(output_dir); output.mkdir(mode=0o700, parents=True, exist_ok=False)
    declared = protocol(profile); declared['protocol_sha256'] = digest(declared)
    _write(output/'protocol.json', declared)  # Freeze inputs and sources before any outcomes.
    started = time.monotonic(); start_utc = datetime.now(timezone.utc).isoformat()
    prepare_defaults(); origin = synthetic_origin()
    _write(output/'origin.json', origin)
    histories = {str(seed): [] for seed in declared['settings']['seeds']}
    rows = []; selected = None; count = 0
    # One compression stream retains exact full native records without thousands of live ledgers.
    with open(output/'native-records.jsonl.gz','wb') as raw:
      with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=6) as archive:
        for split in ('train','validation','test','novelty'):
            if split == 'test':
                validation = [r for r in rows if r['split'] == 'validation']
                losses = []
                for i in range(len(CANDIDATES)):
                    loss = sum(sum((r['forecasts']['candidates'][i]['distribution'][a]
                        - (a == _bucket(r['actual_action'])))**2 for a in BUCKETS) for r in validation)/len(validation)
                    losses.append(loss)
                winner = min(range(len(CANDIDATES)), key=lambda i:(losses[i],i))
                selected = deepcopy(CANDIDATES[winner])
                _write(output/'selection.json', dict(config=selected, index=winner,
                    validation_brier=losses, validation_count=len(validation),
                    frozen_before_test=True, test_outcomes_seen=0))
                _write(output/'selected-config.json', selected)
                print('selected configuration from validation:', canonical(selected), flush=True)
            for fold in histories:
                if split == 'validation':
                    frozen = deepcopy(histories[fold])
                    _write(output/f'fold-{fold}-train.json', frozen)
                elif split in ('test','novelty'):
                    frozen = deepcopy(histories[fold])
                    if split == 'test': _write(output/f'fold-{fold}-fit.json', frozen)
                else:
                    frozen = None
                stamp = digest(frozen) if frozen is not None else None
                for case in declared['inputs'][fold][split]:
                    body = make_body(origin, case['changes'])
                    for preferred in declared['preferences']:
                      durations = [declared['novelty_duration_s']] if split == 'novelty' else declared['durations_s']
                      for duration in durations:
                        rounds = 1 if split == 'novelty' else declared['settings']['rounds']
                        session_id = f'f{fold}-{case["id"]}-{preferred}-{int(duration*10)}'
                        with tempfile.TemporaryDirectory(prefix='self-eval-session-') as tmp:
                          with start_session(Path(tmp)/'body.sqlite', session_id, body, rounds) as loop:
                            for step in range(rounds):
                                ident = session_id+f'-{step}'
                                snapshot = loop.observe(); before = metrics(snapshot)
                                feedback = continuous.native_feedback(loop,snapshot,duration)
                                history = histories[fold] if frozen is None else frozen
                                pre = dict(id=ident, fold=fold, split=split, case=case['id'], step=step,
                                    before=before, feedback=feedback, preferred=preferred, duration_s=duration,
                                    before_checkpoint_sha256=snapshot['checkpoint_sha256'],
                                    training_sha256=digest(history), training_count=len(history),
                                    forecasts=forecasts(history,before,feedback['state'],preferred,duration,split,selected))
                                _append(output/'predictions.jsonl',pre)
                                receipt = loop.step(decision_id=ident,duration_s=duration,preferred_action=preferred)
                                record = loop.engine.get(ident)
                                if not executed_body(record):
                                    raise ValueError('native outcome incomplete: '+ident)
                                source = 'native-decision://'+ident+'/'+digest(record)
                                archive.write((canonical(record)+'\n').encode())
                                row = dict(pre, actual_action=receipt['actual_action'], source=source,
                                    receipt=receipt, native_record_sha256=digest(record))
                                _append(output/'trials.jsonl',row); rows.append(row); count += 1
                                if split in ('train','validation'):
                                    histories[fold].append(dict(id=ident,source=source,
                                        kind='observed_software_outcome',before=before,feedback=feedback['state'],
                                        context=context(before),preferred=preferred,duration_s=duration,
                                        actual_action=receipt['actual_action']))
                                if frozen is not None and digest(frozen) != stamp:
                                    raise ValueError('frozen evaluation history mutated')
                            if loop.status()['actions_remaining'] != 0:
                                raise ValueError('unexpected session budget')
                        if count%32 == 0:
                            print(canonical(dict(completed=count,split=split,fold=fold,
                                elapsed_seconds=round(time.monotonic()-started,1))),flush=True)
        archive.flush()
      raw.flush(); os.fsync(raw.fileno())
    summary = finalize(output)
    summary.update(started_utc=start_utc,completed_utc=datetime.now(timezone.utc).isoformat(),
                   elapsed_seconds=time.monotonic()-started,model_api_calls=0,physical_actuator_calls=0,
                   initialization_warmup_cycles=1)
    _write(output/'summary.json',summary)
    return summary


def finalize(output_dir):
    """Reconstruct every prediction from strictly earlier evidence and rescore.

    Native records are checked against outcome/source hashes and checkpoints.
    This validates saved evidence without executing the body a second time.
    """
    output = Path(output_dir)
    declared = json.loads((output/'protocol.json').read_text())
    expected = dict(declared); stamp = expected.pop('protocol_sha256')
    if digest(expected) != stamp:
        raise ValueError('protocol integrity mismatch')
    current = protocol(declared['profile'])
    if current != expected:
        raise ValueError('protocol/source differs from frozen evaluation')
    preds = [json.loads(x) for x in (output/'predictions.jsonl').read_text().splitlines()]
    rows = [json.loads(x) for x in (output/'trials.jsonl').read_text().splitlines()]
    selection = json.loads((output/'selection.json').read_text())
    fitted, training = {}, {}
    for fold in declared['inputs']:
        training[fold] = json.loads((output/f'fold-{fold}-train.json').read_text())
        fitted[fold] = json.loads((output/f'fold-{fold}-fit.json').read_text())
    prior = {fold:[] for fold in fitted}; seen = set(); all_checks = []; records_by_id = {}
    expected_ids = []
    for split in ('train','validation','test','novelty'):
      for seed in declared['settings']['seeds']:
        fold = str(seed)
        for case in declared['inputs'][fold][split]:
          for preference in declared['preferences']:
            durations = [declared['novelty_duration_s']] if split == 'novelty' else declared['durations_s']
            for duration in durations:
              for step in range(1 if split == 'novelty' else declared['settings']['rounds']):
                expected_ids.append(f'f{fold}-{case["id"]}-{preference}-{int(duration*10)}-{step}')
    if [r['id'] for r in rows] != expected_ids:
        raise ValueError('trial sequence differs from predeclared inputs')
    if len(preds) != len(rows): raise ValueError('prediction/outcome length mismatch')
    with gzip.open(output/'native-records.jsonl.gz','rt') as records:
      for p,r,line in zip(preds,rows,records,strict=True):
        record = json.loads(line)
        if r['id'] in seen: raise ValueError('duplicate trial ID')
        seen.add(r['id']); split=r['split']; fold=r['fold']
        history = prior[fold] if split == 'train' else training[fold] if split == 'validation' else fitted[fold]
        rebuilt = forecasts(history,r['before'],r['feedback']['state'],r['preferred'],
                            r['duration_s'],split,selection['config'])
        observed_start = record['actual_outcome']['body_receipt']['owner']['start_minimum_state']
        sources = r['feedback']['source_ids']
        memory_matches = True
        for action, source_id in sources.items():
            if source_id is None:
                memory_matches = memory_matches and r['feedback']['state'][action] is None
            else:
                previous = records_by_id.get(source_id)
                memory_matches = memory_matches and bool(previous and
                    previous['context'] == record['context'] and previous['selected_action'] == action
                    and previous['feedback']['verified'] is True
                    and previous['feedback']['success'] is r['feedback']['state'][action])
        checks = [all(r[k] == v for k,v in p.items()), rebuilt == r['forecasts'],
            digest(history) == r['training_sha256'], len(history) == r['training_count'],
            digest(record) == r['native_record_sha256'], executed_body(record),
            r['source'] == 'native-decision://'+r['id']+'/'+digest(record),
            record['id'] == r['id'], record['actual_outcome']['selected_action'] == r['actual_action'],
            record['actual_outcome']['body_checkpoint']['sha256'] == r['receipt']['self_model_after']['checkpoint_sha256'],
            record['request']['evidence'][0]['source_sha256'] == r['before_checkpoint_sha256'],
            {k:observed_start[k] for k in continuous.FEATURES} == r['before'], memory_matches,
            set(record['recalled_feedback_ids']) == {v for v in sources.values() if v is not None},
            not any(e['id'] == r['id'] for e in history),
            abs(r['receipt']['body_audit']['energy_error_J']) < 1e-6,
            abs(r['receipt']['body_audit']['water_error_L']) < 1e-9]
        if not all(checks): raise ValueError('evidence validation failed: '+r['id']+' '+str(checks))
        records_by_id[r['id']] = {key:record[key] for key in ('context','selected_action','feedback')}
        all_checks.extend(checks)
        if split == 'train':
            prior[fold].append(dict(id=r['id'],source=r['source'],kind='observed_software_outcome',
                before=r['before'],feedback=r['feedback']['state'],context=context(r['before']),
                preferred=r['preferred'],duration_s=r['duration_s'],actual_action=r['actual_action']))
    validation = [r for r in rows if r['split']=='validation']
    losses = [sum(sum((r['forecasts']['candidates'][i]['distribution'][a]
        - (a == _bucket(r['actual_action'])))**2 for a in BUCKETS) for r in validation)/len(validation)
        for i in range(len(CANDIDATES))]
    winner = min(range(len(CANDIDATES)),key=lambda i:(losses[i],i))
    if (selection['config'] != CANDIDATES[winner] or selection['validation_brier'] != losses
            or selection['test_outcomes_seen'] != 0):
        raise ValueError('validation-only selection mismatch')
    for fold in fitted:
        validation_rows = [r for r in validation if r['fold']==fold]
        evidence = prior[fold] + [dict(id=r['id'],source=r['source'],kind='observed_software_outcome',
            before=r['before'],feedback=r['feedback']['state'],context=context(r['before']),
            preferred=r['preferred'],duration_s=r['duration_s'],actual_action=r['actual_action']) for r in validation_rows]
        if evidence != fitted[fold] or prior[fold] != training[fold]:
            raise ValueError('training file differs from earlier native receipts')
    held = [r for r in rows if r['split']=='test']; novelty=[r for r in rows if r['split']=='novelty']
    names = ('selected','default','v1','pooled','without_feedback','shuffled_body')
    overall = {name:summarize(held,name) for name in names}
    folds = {fold:{name:summarize([r for r in held if r['fold']==fold],name) for name in names} for fold in fitted}
    selected, old, pooled = (overall[x] for x in ('selected','v1','pooled'))
    novelty_summary = summarize(novelty,'selected')
    reduction = (old['brier']-selected['brier'])/old['brier']
    criteria = dict(brier_reduction=reduction>=.10,
        no_worse_than_pooled=selected['brier']<=pooled['brier'],
        supported_accuracy=(selected['supported_accuracy'] or 0)>=.85,
        supported_protect_recall=(selected['supported_protect_recall'] or 0)>=.5,
        no_novelty_assertions=novelty_summary['asserted']==0,
        no_fold_regression=all(v['selected']['brier']<=1.05*v['v1']['brier'] for v in folds.values()))
    expected_count = len(fitted)*(sum(declared['settings'][s] for s in ('train','validation','test'))*4*
        declared['settings']['rounds'] + declared['settings']['novelty']*2)
    if len(rows) != expected_count: raise ValueError('incomplete declared evaluation')
    return dict(schema=declared['schema'],profile=declared['profile'],native_cycles=len(rows),
        split_counts=dict(Counter(r['split'] for r in rows)), selected_config=selection['config'],
        heldout=overall,by_fold=folds,novel_duration=novelty_summary,
        by_step={str(i):{name:summarize([r for r in held if r['step']==i],name) for name in names}
                 for i in range(declared['settings']['rounds'])},
        relative_brier_reduction_vs_v1=reduction,acceptance_criteria=criteria,
        all_acceptance_criteria_passed=all(criteria.values()),validation_passed=True,
        evidence_checks=len(all_checks),protocol_sha256=stamp,
        limitations=['Synthetic inputs were designed with knowledge of controller code.',
                     'Two steps per trajectory and shared synthetic origin are correlated.',
                     'Unseen-duration rejection does not establish general novelty detection.',
                     'Feedback-aware forecasting observes ledger state; it does not read LLM internals.',
                     'The monitor changes forecasts, not the native action policy.'])
