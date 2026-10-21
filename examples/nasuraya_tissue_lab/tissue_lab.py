"""Read-only regional observer for the fictional Nasuraya body.

Reduced, uncalibrated tissue indices, NOT biological cells or gas tensions.
Paid native organ watts are partitioned as annotations, never debited again.
The observer cannot actuate or modify the native body. Forecasts are labelled.
"""
from copy import deepcopy
import hashlib
import json
import math

SCHEMA = 'nasuraya-tissue-observer/1'
# Flow fractions leave 78.6% explicitly outside these six selected beds.
REGIONS = {
    'brain': (.13, 'neural', .7),
    'myocardium': (.04, None, 0.),
    'resonan_L': (.001, 'special', .3),
    'resonan_R': (.001, 'special', .3),
    'spandar': (.0005, 'special', .4),
    'face': (.0415, 'neural', .3),
}
NAMES = tuple(REGIONS)


def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()


def number(x, lo, hi):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f'finite value in [{lo}, {hi}] required')
    return x


def clamp(x):
    return max(0., min(1., x))


def adapter(envelope, *, reference_flow_L_min):
    """Validate a native checkpoint digest; copy only declared observable fields.

    reference_flow is an explicit scenario baseline, not an estimated normal CO.
    No oxygen saturation or oxygen content is inferred from adequacy_proxy.
    """
    if set(envelope) != {'payload', 'sha256'} or digest(envelope['payload']) != envelope['sha256']:
        raise ValueError('native checkpoint digest mismatch')
    p = envelope['payload']; m = p['modules']; o = m['outputs']
    return dict(source_id=envelope['sha256'], kind='recorded_snapshot',
        source_tick=m['tick'], Q_L_min=o['cardiorespiratory']['Q_L_min'],
        reference_flow_L_min=reference_flow_L_min,
        oxygen_proxy=o['cardiorespiratory']['oxygen_adequacy_proxy'],
        paid_W={k: m['last_paid_W'][k] for k in ('special', 'neural', 'immune')},
        systemic_inflammation=o['immune']['inflammation'],
        patency={n: 1. for n in NAMES}, lymph={n: 1. for n in NAMES},
        insult={n: 0. for n in NAMES})


def validate_input(x):
    expected = {'source_id','kind','source_tick','Q_L_min','reference_flow_L_min',
        'oxygen_proxy','paid_W','systemic_inflammation','patency','lymph','insult'}
    if set(x) != expected or not isinstance(x['source_id'], str) or not x['source_id']:
        raise ValueError('exact input contract and source identity required')
    if x['kind'] not in ('recorded_snapshot','forecast') or type(x['source_tick']) is not int or x['source_tick'] < 0:
        raise ValueError('source type/tick invalid')
    number(x['Q_L_min'], 0, 1000); number(x['reference_flow_L_min'], .001, 1000)
    number(x['oxygen_proxy'], 0, 1); number(x['systemic_inflammation'], 0, 1)
    if set(x['paid_W']) != {'special','neural','immune'}: raise ValueError('budget keys')
    for v in x['paid_W'].values(): number(v, 0, 10000)
    for k in ('patency','lymph','insult'):
        if set(x[k]) != set(NAMES): raise ValueError('region keys')
        for v in x[k].values(): number(v, 0, 1)


class TissueObserver:
    def __init__(self):
        self.state = dict(schema=SCHEMA, time_s=0., steps=0, last_source=None,
            seen_sources=[], last_recorded_tick=-1,
            regions={n:dict(edema_index=0., inflammation_index=0.) for n in NAMES})

    def checkpoint(self):
        return dict(payload=deepcopy(self.state), sha256=digest(self.state))

    @classmethod
    def restore(cls, e):
        if set(e) != {'payload','sha256'} or digest(e['payload']) != e['sha256']:
            raise ValueError('observer digest mismatch')
        p = e['payload']; obj = cls()
        if set(p) != set(obj.state) or p['schema'] != SCHEMA or set(p['regions']) != set(NAMES):
            raise ValueError('observer schema')
        number(p['time_s'], 0, 1e9)
        if type(p['steps']) is not int or not 0 <= p['steps'] <= 100000: raise ValueError('step count')
        if type(p['last_recorded_tick']) is not int or p['last_recorded_tick'] < -1: raise ValueError('tick')
        if not isinstance(p['seen_sources'],list) or len(p['seen_sources']) != p['steps'] or len(set(p['seen_sources'])) != p['steps']:
            raise ValueError('source history')
        if any(not isinstance(s,str) or not s for s in p['seen_sources']): raise ValueError('source identity')
        if p['last_source'] != (p['seen_sources'][-1] if p['steps'] else None): raise ValueError('last source')
        for r in p['regions'].values():
            if set(r) != {'edema_index','inflammation_index'}: raise ValueError('region state')
            for v in r.values(): number(v,0,1)
        obj.state=deepcopy(p); return obj

    def advance(self, x, dt_s=.1):
        """Advance observer time; all biological time constants are authored fixtures.

        A recorded observation is consumed once. Constant-input extrapolation
        must use kind=forecast and distinct source IDs. No native time advances.
        """
        validate_input(x); number(dt_s,.001,1.)
        if self.state['steps'] >= 100000: raise ValueError('bounded run exhausted')
        if x['source_id'] in self.state['seen_sources']: raise ValueError('source replay')
        if x['kind']=='recorded_snapshot' and x['source_tick'] <= self.state['last_recorded_tick']:
            raise ValueError('stale recorded tick')
        s=deepcopy(self.state); rows={}; total_flow=0.; annotated={k:0. for k in x['paid_W']}
        for n,(share,budget,weight) in REGIONS.items():
            r=s['regions'][n]; flow=x['Q_L_min']*share*x['patency'][n]; total_flow+=flow
            target_i=clamp(x['systemic_inflammation']+x['insult'][n])
            r['inflammation_index'] += -math.expm1(-dt_s/120.)*(target_i-r['inflammation_index'])
            target_e=clamp(r['inflammation_index']*(1.-x['lymph'][n])+.5*x['insult'][n])
            r['edema_index'] += -math.expm1(-dt_s/60.)*(target_e-r['edema_index'])
            delivery=clamp(flow/(x['reference_flow_L_min']*share))*x['oxygen_proxy']/(1.+2.*r['edema_index'])
            # Neural/special are an annotation partition, not ATP production.
            support=1. if budget is None else min(1.,x['paid_W'][budget]/({'special':.2,'neural':2.}[budget]))
            reserved_J=0. if budget is None else x['paid_W'][budget]*weight*dt_s
            if budget is not None: annotated[budget]+=reserved_J
            immune_J=x['paid_W']['immune']*share/sum(v[0] for v in REGIONS.values())*dt_s
            annotated['immune']+=immune_J
            functional=delivery*support*(1.-.5*r['inflammation_index'])
            rows[n]=dict(flow_L_min=flow,delivery_index=delivery,
                function_ceiling=clamp(functional),edema_index=r['edema_index'],
                inflammation_index=r['inflammation_index'],
                support_annotation_J=reserved_J,immune_annotation_J=immune_J,
                warning=delivery<.6)
        s['time_s']+=dt_s; s['steps']+=1; s['last_source']=x['source_id'];s['seen_sources'].append(x['source_id'])
        if x['kind']=='recorded_snapshot':s['last_recorded_tick']=x['source_tick']
        out=dict(schema=SCHEMA,kind=x['kind'],source_id=x['source_id'],
            source_tick=x['source_tick'],observer_time_s=s['time_s'],regions=rows,
            allocated_flow_L_min=total_flow,unassigned_flow_L_min=x['Q_L_min']-total_flow,
            flow_residual_L_min=x['Q_L_min']-total_flow-(x['Q_L_min']-total_flow),
            paid_annotation_J=annotated,
            paid_residual_J={k:x['paid_W'][k]*dt_s-v for k,v in annotated.items()},
            native_energy_debit_J=0.,native_state_mutated=False,
            scope='uncalibrated proxy observer; no repair, antigen solver or actuation')
        self.state=s; return out


def forecast(x, *, seconds=180, intervention=None):
    if type(seconds) is not int or not 1 <= seconds <= 3600: raise ValueError('forecast 1..3600 seconds')
    base=deepcopy(x); base['kind']='forecast'
    if intervention: intervention(base)
    model=TissueObserver(); rows=[]
    for i in range(seconds):
        z=deepcopy(base); z['source_id']=f"{x['source_id']}/forecast/{i}"
        rows.append(model.advance(z,1.))
    return model, rows
