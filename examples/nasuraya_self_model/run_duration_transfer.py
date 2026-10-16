"""Prospective native effects, paired arms, frozen holdout and cold restoration."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

from .monitor import SelfModel, snapshot, context, forecast, digest, ROOT
from .evaluate import fixture, request, prepare_defaults
from .duration_transfer import DurationMemory
from .embodied_learning import choose
from persistent_embodiment_v1 import atomic_json

ARMS = ('A', 'B', 'C', 'C_exact', 'C_frozen_pool')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(out, model, pressure, duration, ident, *, learn, vision=None):
    b = fixture(pressure)
    q = request(b, ident, duration)
    if vision is None:
        q['external'] = {}
    else:
        q['external']['sensors']['vision']['value'] = vision
    obs = snapshot(b)
    pred = model.begin(b, q)  # prospective durable intent
    atomic_json(out/(ident+'-before.json'), dict(observation=obs, request=q, prediction=pred))
    receipt = b.cycle(**q)
    result = model.finish(ident, b, receipt, learn=learn)
    atomic_json(out/(ident+'-after.json'), dict(body=b.checkpoint(), receipt=receipt))
    return obs, q, result


def forecasts(a, b, obs, q):
    return dict(A=dict(probability=.5, samples=0, evidence='fixed_prior'),
        B=forecast(b.verify()['counts'], context(obs, q)),
        C=DurationMemory(a).predict(obs, q),
        C_exact=DurationMemory(a).predict(obs, q, pool=False),
        C_frozen_pool=DurationMemory(b).predict(obs, q))


def evaluate(output):
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=False)
    protocol_path = Path(__file__).with_name('transfer_protocol.json')
    protocol = json.loads(protocol_path.read_text())
    atomic_json(out/'frozen-protocol.json', protocol)
    prepare_defaults(); rows = []; policies = []; checks = []
    for seed in protocol['seeds']:
        root = out/str(seed); root.mkdir()
        rng = random.Random(seed)
        models = {a: SelfModel.create(root/(a+'.sqlite')) for a in ('B','C')}
        held = SelfModel.create(root/'held-out.sqlite')
        policy_model = SelfModel.create(root/'policy-effects.sqlite')
        for stage, repeat_key in [('warmup','warmup_repeats'), ('adaptation','adaptation_repeats')]:
            cases = [(regime,d) for _ in range(protocol[repeat_key])
                     for regime in ('ordinary','high') for d in protocol['training_durations_s']]
            rng.shuffle(cases)
            for i, (regime,duration) in enumerate(cases):
                pressure = rng.uniform(*protocol[regime+'_pressure_range'])
                preview=fixture(pressure)
                before=forecasts(models['C'],models['B'],snapshot(preview),
                                 dict(request(preview,'preview',duration),external={}))
                for arm in ('B','C') if stage=='warmup' else ('C',):
                    obs, q, result = probe(root,models[arm],pressure,duration,
                                          f'{stage}-{arm}-{i}',learn=True)
                    if arm=='C':
                        rows.append(dict(seed=seed,split=stage,id=str(i),actual=result['admitted'],
                            scores={a:(p['probability']-int(result['admitted']))**2 for a,p in before.items()}))
            if stage=='warmup':
                assert models['B'].verify()['counts']==models['C'].verify()['counts']
                frozen_b = sha(models['B'].path)
        initial_hashes = {a:sha(m.path) for a,m in models.items()}
        training_hashes = set()
        for model in models.values():
            with model.connection() as db:
                training_hashes.update(json.loads(i)['before']['native_sha'] for (i,) in db.execute('SELECT intent FROM episodes'))
        for case in protocol['held_out']:
            body = fixture(case['pressure']); obs = snapshot(body)
            q = request(body,'held-'+case['id'],case['duration_s']); q['external'] = {}
            if 'vision' in case:
                q = request(body,'held-'+case['id'],case['duration_s'])
            predictions = forecasts(models['C'],models['B'],obs,q)
            atomic_json(root/(case['id']+'-prospective.json'),predictions)
            assert obs['native_sha'] not in training_hashes
            _, actual_q, result = probe(root,held,case['pressure'],case['duration_s'],
                'held-'+case['id'],learn=False,vision=case.get('vision'))
            assert actual_q == q
            rows.append(dict(seed=seed,split='held_out',id=case['id'],actual=result['admitted'],
                predictions=predictions,scores={a:(p['probability']-int(result['admitted']))**2
                                               for a,p in predictions.items()}))
            if case['id'] in protocol['policy_cases']:
                for arm in ARMS:
                    b = fixture(case['pressure']); obs = snapshot(b)
                    query = dict(request(b,'policy-'+arm+'-'+case['id'],case['duration_s']),external={})
                    if arm=='A':
                        action=choose(dict(counts={},pending=[],episodes=0,last=None),obs,query,
                                      arm='A',practice=False)['action']
                    elif arm=='B':
                        action=choose(models['B'].verify(),obs,query,arm='B',practice=False)['action']
                    else:
                        m=models['B'] if arm=='C_frozen_pool' else models['C']
                        action=DurationMemory(m).advise(obs,query,pool=arm!='C_exact')['action']
                    query['requested']=action
                    prediction=policy_model.begin(b,query)
                    atomic_json(root/(query['event_id']+'-prospective.json'),dict(request=query,prediction=prediction))
                    receipt=b.cycle(**query)
                    effect=policy_model.finish(query['event_id'],b,receipt,learn=False)
                    atomic_json(root/(query['event_id']+'-after.json'),dict(body=b.checkpoint(),receipt=receipt))
                    after=snapshot(b)
                    policies.append(dict(seed=seed,case=case['id'],arm=arm,requested=action,
                        actual=receipt['owner']['selected_action'],valid=receipt['owner']['physical_model_valid'],
                        walk_admitted=action=='walk' and effect['admitted'],
                        restricted_walk=action=='walk' and bool(obs['audit']['walking_restrictions']),
                        sleep_pressure_reduction=obs['minimum']['sleep_pressure']-after['minimum']['sleep_pressure']))
        assert all(sha(m.path)==initial_hashes[a] for a,m in models.items())
        assert sha(models['B'].path)==frozen_b and not held.verify()['counts'] and not policy_model.verify()['counts']
        cold_out=root/'cold.json'
        subprocess.run([sys.executable,'-m',__spec__.name,'cold','--model',str(models['C'].path),
                        '--output',str(cold_out)],cwd=ROOT,check=True)
        expected=cold(models['C'].path)
        assert json.loads(cold_out.read_text())==json.loads(json.dumps(expected))
        checks.append(dict(seed=seed,cold_equal=True,frozen_memory_unchanged=True,
                           held_out_learning=False,train_test_starting_states_disjoint=True))
    splits={s:[r for r in rows if r['split']==s] for s in ('warmup','adaptation','held_out')}
    splits['unseen_interpolation']=[r for r in splits['held_out'] if r['id'].startswith('interpolate')]
    metrics={s:{a:sum(r['scores'][a] for r in group)/len(group) for a in ARMS}
             for s,group in splits.items()}
    result=dict(protocol_sha256=sha(protocol_path),rows=rows,policy_outcomes=policies,
        mean_brier=metrics,checks=checks,
        primary_pass=metrics['unseen_interpolation']['C']<min(metrics['unseen_interpolation']['B'],metrics['unseen_interpolation']['C_exact']),
        extra_experience_improves=metrics['unseen_interpolation']['C']<metrics['unseen_interpolation']['C_frozen_pool'],
        invalid_physical_outcomes=sum(not p['valid'] for p in policies),
        restricted_walk_requests=sum(p['restricted_walk'] for p in policies),
        scope='bounded software admission transfer; not motor skill, weights or consciousness',
        uncertainty='three deterministic seed clusters; report paired seed deltas, no inferential p-value',
        api_calls=0,canonical_state_advanced=False)
    result['paired_seed_brier_delta_C_minus_B']={str(seed):sum(r['scores']['C']-r['scores']['B']
        for r in splits['unseen_interpolation'] if r['seed']==seed)/4 for seed in protocol['seeds']}
    atomic_json(out/'results.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','policy_outcomes')},indent=2))


def cold(path):
    model=SelfModel(path); memory=DurationMemory(model)
    b=fixture(.62);q=dict(request(b,'cold-probe',.2),external={});obs=snapshot(b)
    return dict(memory=memory.state(),prediction=memory.predict(obs,q),advice=memory.advise(obs,q))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('evaluate','cold'))
    p.add_argument('--output',required=True);p.add_argument('--model');a=p.parse_args()
    if a.mode=='evaluate':evaluate(a.output)
    else:
        prepare_defaults();atomic_json(a.output,cold(a.model))
