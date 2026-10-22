"""Prospective self-efficacy estimates from verified local body receipts.

This monitors whether my requested action is actually admitted by my native
body. It does not replace the existing physiological predictor or its guards.
Counts describe a software context, not subjective experience or a calibrated
probability for a physical body. SQLite/hash integrity assumes a trusted host.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
NATIVE=ROOT/'runtimes/tadash_body'
sys.path.insert(0,str(NATIVE))
from unified_body_v2 import UnifiedBody
from persistent_embodiment_v1 import digest, instant, ACTIONS
from audit_self_model import assess

SCHEMA='nasuraya-evidence-self-model/1'
POLICY=dict(prior_success=1,prior_failure=1,min_samples=3,continue_threshold=.7,
            max_age_s=5.,max_episodes=128)


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def source():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def snapshot(body):
    checkpoint=body.checkpoint()
    UnifiedBody.restore(checkpoint)  # validate clocks, sources and native journal
    audit=assess(body)
    cls=type(body.owner.physical)
    module=Path(sys.modules[cls.__module__].__file__)
    result=dict(native_sha=checkpoint['sha256'],revision=body.revision,
        time_s=body.owner.physical.state.time_s,minimum=deepcopy(audit['saved_minimum_state']),
        audit=audit,body_before_digest=digest(dict(native=body.owner.body(),modules=body.modules,affect=body.affect)),
        source_identity=digest(dict(native=checkpoint['payload']['source_fingerprints'],
            controller=cls.__module__+'.'+cls.__qualname__,controller_sha=hashlib.sha256(module.read_bytes()).hexdigest())),
        evidence_kind='source_pinned_software_observation')
    result['observation_sha256']=digest(result)
    return result


def verify_observation(observation):
    if (not isinstance(observation,dict) or observation.get('evidence_kind')!='source_pinned_software_observation' or
        observation.get('observation_sha256')!=digest({k:v for k,v in observation.items() if k!='observation_sha256'})):
        raise ValueError('damaged or unsupported observation')


def context(observation,request):
    verify_observation(observation)
    m=observation['minimum']
    return digest(dict(source=observation['source_identity'],action=request['requested'],
        duration_s=request['duration_s'],posture=m['posture'],
        sleep='high' if m['sleep_pressure']>.85 else 'ordinary',
        fatigue='high' if m['fatigue']>.52 else 'ordinary',
        pain='high' if m['pain']>.40 else 'ordinary',external=structural_inputs(request['external'],observation['time_s'])))


def structural_inputs(external,body_time):
    # Preserve sensory semantics/freshness and all physical interventions.
    # Ignore only per-sample IDs and absolute times, which are bookkeeping.
    result={k:v for k,v in external.items() if k!='sensors'}
    result['sensors']={k:dict(value=v['value'],kind=v['kind'],
        fresh=0<=body_time-v['sampled_at_s']<=POLICY['max_age_s'])
        for k,v in external.get('sensors',{}).items()}
    return result


def forecast(counts,key):
    success,failure=counts.get(key,(0,0));n=success+failure
    return dict(context=key,samples=n,successes=success,failures=failure,
        probability=(success+1)/(n+2),unseen_context=n==0,
        kind='Beta(1,1) mean for verified software requested-action admission; not globally calibrated')


class SelfModel:
    def __init__(self,path):
        self.path=Path(path).resolve()
        if not self.path.is_file():raise FileNotFoundError(self.path)
        self.verify()

    @classmethod
    def create(cls,path):
        path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''CREATE TABLE contract (value TEXT NOT NULL);
                CREATE TABLE episodes (id TEXT PRIMARY KEY,intent TEXT NOT NULL,intent_sha TEXT NOT NULL,
                    result TEXT,result_sha TEXT);''')
            db.execute('INSERT INTO contract VALUES (?)',(encode(dict(schema=SCHEMA,policy=POLICY,source=source())),))
        return cls(path)

    def connection(self):
        db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _verify(self,db):
        rows=db.execute('SELECT value FROM contract').fetchall()
        if len(rows)!=1 or json.loads(rows[0][0])!=dict(schema=SCHEMA,policy=POLICY,source=source()):
            raise ValueError('self-model source/policy mismatch')
        counts={};pending=[];total=0;last=None
        for event,raw,h,result,rh in db.execute('SELECT * FROM episodes ORDER BY rowid'):
            total+=1;i=json.loads(raw)
            if digest(i)!=h or i['request']['event_id']!=event or i['prediction']!=forecast(counts,context(i['before'],i['request'])):
                raise ValueError('self-model intent/history mismatch')
            if result is None:
                if rh is not None:raise ValueError('partial self-model result')
                pending.append(event);continue
            if pending:raise ValueError('learning passed an unresolved outcome')
            r=json.loads(result)
            receipt=r['receipt'];matched=(receipt['owner']['selected_action']==i['request']['requested'] and receipt['owner']['physical_model_valid'])
            verify_observation(r['after'])
            if (type(r['learned']) is not bool or type(r['admitted']) is not bool or
                digest(r)!=rh or r['admitted']!=matched or receipt['event_id']!=event or
                r['after']['revision']!=i['before']['revision']+1 or
                r['brier']!=(i['prediction']['probability']-int(matched))**2):
                raise ValueError('self-model result/history mismatch')
            if r['learned']:
                key=i['prediction']['context'];s,f=counts.get(key,(0,0));counts[key]=(s+int(matched),f+int(not matched))
            last=dict(requested=i['request']['requested'],actual=receipt['owner']['selected_action'],
                admitted=matched,receipt_sha256=digest(receipt),native_prediction_error=receipt['owner']['prediction']['mean_scaled_absolute_error'])
        if total>POLICY['max_episodes'] or len(pending)>1:raise ValueError('self-model budget/pending mismatch')
        return dict(counts=counts,pending=pending,episodes=total,last=last)

    def verify(self):
        with self.connection() as db:return self._verify(db)

    def inspect(self,observation,request,*,at_simulated_s=None):
        state=self.verify();key=context(observation,request);p=forecast(state['counts'],key)
        now=observation['time_s'] if at_simulated_s is None else at_simulated_s
        if type(now) not in (int,float) or not math.isfinite(now) or now<observation['time_s']:
            raise ValueError('valid evaluation clock required')
        reasons=[]
        if now-observation['time_s']>POLICY['max_age_s']:reasons.append('stale_body_evidence')
        if state['pending']:reasons.append('unresolved_outcome')
        if request['requested']=='walk' and observation['audit']['walking_restrictions']:
            reasons.extend(observation['audit']['walking_restrictions'])
        if p['samples']<POLICY['min_samples']:reasons.append('insufficient_context_experience')
        if p['probability']<POLICY['continue_threshold']:reasons.append('low_observed_self_efficacy')
        return dict(schema=SCHEMA,observed=dict(native_sha=observation['native_sha'],
            revision=observation['revision'],time_s=observation['time_s'],minimum=observation['minimum']),
            inferred=p,unknown=['subjective_experience','physical_world_without_sensors','empirical_body_calibration']+
                (['current_body_state'] if 'stale_body_evidence' in reasons else []),
            recommendation='pause_and_observe' if reasons else 'continue_with_native_guards',
            reasons=reasons,last_verified_effect=state['last'],pending=state['pending'],
            scope='local functional metacognition; no native action issued')

    def begin(self,body,request):
        if not isinstance(request,dict) or set(request)!={'event_id','at_utc','duration_s','requested','expected_revision','external'}:
            raise ValueError('exact native request required')
        if not re.fullmatch(r'[A-Za-z0-9_:.\-]{1,100}',request['event_id']):raise ValueError('bounded event id')
        if request['expected_revision']!=body.revision or request['requested'] not in ACTIONS:
            raise ValueError('explicit action and current native revision required')
        body.validate_input(request['external'],instant(request['at_utc']),request['duration_s'])
        before=snapshot(body)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE');state=self._verify(db)
            existing=db.execute('SELECT intent FROM episodes WHERE id=?',(request['event_id'],)).fetchone()
            if existing:
                prior=json.loads(existing[0])
                if prior['request']!=request or prior['before']!=before:raise ValueError('conflicting self-model event')
                return prior['prediction']
            if state['pending']:raise ValueError('unknown outcome must not be retried or bypassed')
            if state['episodes']>=POLICY['max_episodes']:raise ValueError('self-model episode budget exhausted')
            i=dict(before=before,request=deepcopy(request),prediction=forecast(state['counts'],context(before,request)))
            db.execute('INSERT INTO episodes VALUES (?,?,?,NULL,NULL)',(request['event_id'],encode(i),digest(i)))
            return i['prediction']

    def finish(self,event,body,receipt,*,learn=True):
        if type(learn) is not bool:raise ValueError('explicit learning flag')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE');self._verify(db)
            row=db.execute('SELECT intent,result FROM episodes WHERE id=?',(event,)).fetchone()
            if row is None:raise ValueError('prediction was not recorded before action')
            i=json.loads(row[0])
            if row[1] is not None:
                r=json.loads(row[1])
                if r['receipt']!=receipt or r['learned']!=learn:raise ValueError('conflicting result replay')
                return r
            after=snapshot(body);request=i['request'];before=i['before']
            request_hash=digest({k:(instant(v).isoformat() if k=='at_utc' else v) for k,v in request.items() if k!='event_id'})
            if (body.results.get(event)!=receipt or body.requests.get(event)!=request_hash or
                after['revision']!=before['revision']+1 or after['source_identity']!=before['source_identity'] or
                receipt.get('event_id')!=event or body.journal[-1]['event_id']!=event or
                body.journal[-1]['before_sha256']!=before['body_before_digest']):
                raise ValueError('unverified, unrelated or discontinuous body result')
            if any(abs(receipt['whole_body_audit'][k])>v for k,v in [('energy_error_J',5e-5),('water_error_L',1e-8),('light_error_J',1e-8)]):
                raise ValueError('native conservation audit failed')
            admitted=receipt['owner']['selected_action']==request['requested'] and receipt['owner']['physical_model_valid']
            r=dict(after=after,receipt=deepcopy(receipt),admitted=admitted,
                   brier=(i['prediction']['probability']-int(admitted))**2,learned=learn)
            db.execute('UPDATE episodes SET result=?,result_sha=? WHERE id=?',(encode(r),digest(r),event))
            return r
