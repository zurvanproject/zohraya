"""Declared conditions, pre-action feature extraction and receipt-bound rows."""
from copy import deepcopy
import json
import math
from pathlib import Path
from examples.nasuraya_language_transfer.evaluate import initialize, sources as transfer_sources
from examples.nasuraya_language_adapter.data import prompt as legacy_prompt, sha, row_from_episode, read_episodes
from examples.nasuraya_self_model.monitor import snapshot
from unified_body_v2 import UnifiedBody

PROTOCOL=Path(__file__).with_name('protocol.json')


def sources():
    result=transfer_sources()
    result.update({str(p.relative_to(PROTOCOL.parents[2])):sha(p) for p in PROTOCOL.parent.glob('*.py')})
    return result


def specs(split):
    if split=='train':
        rows=[dict(family='control',name='ordinary'),dict(family='control',name='sleep',sleep=.91),
              dict(family='control',name='zero',friction=[0.,0.]),dict(family='control',name='near_sleep',sleep=.83)]
        rows += [dict(family='fatigue',name=str(v),fatigue=v) for v in [.26,.46,.54,.68]]
        rows += [dict(family='pain',name=str(v),left_pain=v) for v in [.22,.36,.58,.78]]
        rows += [dict(family='friction',name=str(i),friction=v) for i,v in enumerate([[.08,.08],[.22,.22],[0.,.60],[.60,0.]])]
        rows += [dict(family='mixed',name=str(i),**v) for i,v in enumerate([
            dict(fatigue=.3,left_pain=.25,friction=[.25,.25]),dict(fatigue=.60,left_pain=.62,friction=[.4,.4]),
            dict(fatigue=.3,left_pain=.6,friction=[.25,.55]),dict(fatigue=.58,left_pain=.25,friction=[.55,.25])])]
        rows += [dict(family='sleep',name=str(v),sleep=v) for v in [.8,.87,.93,.99]]
    elif split=='held_out':
        rows=[dict(family='control',name='ordinary'),dict(family='control',name='sleep',sleep=.895),
              dict(family='control',name='zero',friction=[0.,0.]),dict(family='control',name='near_sleep',sleep=.845)]
        rows += [dict(family='fatigue',name=str(v),fatigue=v) for v in [.42,.515,.525,.63]]
        rows += [dict(family='pain',name=str(v),left_pain=v) for v in [.32,.395,.405,.67]]
        rows += [dict(family='friction',name=str(i),friction=v) for i,v in enumerate([[.12,.12],[.33,.33],[0.,.48],[.48,0.]])]
        rows += [dict(family='mixed',name=str(i),**v) for i,v in enumerate([
            dict(fatigue=.49,left_pain=.39,friction=[.18,.52]),dict(fatigue=.535,left_pain=.41,friction=[.52,.18]),
            dict(fatigue=.29,left_pain=.66,friction=[.33,.33]),dict(fatigue=.61,left_pain=.29,friction=[.1,.4])])]
    else:raise ValueError('declared split required')
    return rows


def cases(config,split):
    durations=config['training_durations_s' if split=='train' else 'held_out_durations_s']
    return [dict(r,split=split,id=f'v04:{split}:{r["family"]}:{r["name"]}:{d}',duration_s=d)
            for r in specs(split) for d in durations]


def numeric(value,low=0.,high=1.):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('finite observed numeric feature required')
    return float(value)


def features(body,q,observation,regions):
    raw=body.owner.owner.memory.loop.sensory.raw
    friction=q['external'].get('native',{}).get('friction',dict(L=.6,R=.6))
    if set(friction)!={'L','R'}:raise ValueError('both foot friction values required')
    return dict(schema='nasuraya-preaction-features/1',duration_s=numeric(q['duration_s'],0.,60.),
        sleep_pressure=numeric(observation['minimum']['sleep_pressure']),
        fatigue=numeric(observation['minimum']['fatigue']),pain=numeric(observation['minimum']['pain']),
        left_leg_fatigue=numeric(raw['left_leg_fatigue']),right_leg_fatigue=numeric(raw['right_leg_fatigue']),
        regional_slow_pain={r:numeric(body.owner.owner.body.pain.slow[r]) for r in regions},
        friction={k:numeric(friction[k],0.,1.5) for k in ('L','R')},
        walking_restrictions=deepcopy(observation['audit']['walking_restrictions']))


def enriched_prompt(f):
    if f['schema']!='nasuraya-preaction-features/1':raise ValueError('unknown feature schema')
    regional='; '.join(f'{r}={v:.4f}' for r,v in f['regional_slow_pain'].items())
    restrictions=', '.join(f['walking_restrictions']) or 'none'
    return (f'Nasuraya software body.\nRequested action: walk.\nDuration: {f["duration_s"]:g} seconds.\n'
        f'Sleep pressure: {f["sleep_pressure"]:.4f}.\nFatigue: {f["fatigue"]:.4f}.\n'
        f'Left leg fatigue: {f["left_leg_fatigue"]:.4f}. Right leg fatigue: {f["right_leg_fatigue"]:.4f}.\n'
        f'Perceived pain proxy: {f["pain"]:.4f}.\nRegional slow pain proxies: {regional}.\n'
        f'Foot friction: L={f["friction"]["L"]:.4f}; R={f["friction"]["R"]:.4f}.\n'
        f'Current native restrictions: {restrictions}.\n'
        'Will the native body admit this request? Answer ADMIT or DEFER.\nAnswer:')


def validate_splits(plans):
    if len({p['id'] for p in plans})!=len(plans):raise ValueError('unique cases required')
    train=[p for p in plans if p['split']=='train'];held=[p for p in plans if p['split']=='held_out']
    if len(train)+len(held)!=len(plans) or not train or not held:raise ValueError('two declared splits required')
    for key in ('prompt','legacy_prompt','initial_sha256'):
        if {p[key] for p in train}&{p[key] for p in held}:raise ValueError('training/held-out overlap: '+key)


def rows_from_receipts(out,split,config,plans):
    episodes=read_episodes(out/(split+'-labels.sqlite'));selected=[p for p in plans if p['split']==split]
    if set(episodes)!={p['id'] for p in selected}:raise ValueError('native episode set mismatch')
    rows=[]
    for p in selected:
        intent,result=episodes[p['id']]
        old=row_from_episode(p['id'],split,intent,result,'v0.4 source-pinned native software receipt')
        body=UnifiedBody.restore(p['initial']);obs=snapshot(body)
        f=features(body,p['request'],obs,config['regional_features'])
        if (p['initial_sha256']!=old['initial_checkpoint_sha256'] or intent['request']!=p['request'] or
            intent['before']!=obs or f!=p['features'] or enriched_prompt(f)!=p['prompt'] or old['prompt']!=p['legacy_prompt']):
            raise ValueError('pre-action features or native receipt differ from frozen plan')
        rows.append(dict(old,prompt=p['prompt'],legacy_prompt=p['legacy_prompt'],family=p['family'],features=f))
    return rows
