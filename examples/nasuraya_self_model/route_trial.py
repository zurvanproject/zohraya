"""Explicit paired-policy experiment on private copies of a retained MotionGoal.

Only the fuel term differs: original online action EMA or frozen context energy
calibration. Eligibility, urgency, ETA/fatigue learning and native execution reuse
the original planner. This is a new source-pinned experiment envelope.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path

from . import planning as base
from .energy import EnergyCalibration, features, score as energy_score, fingerprints
from .monitor import digest

SCHEMA='nasuraya-paired-route-trial/1'
MODES=('old','calibrated')


def sources():
    return {**fingerprints(),'route_trial.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def selection(mode,phase,initial,candidates,learning,spent,model):
    if mode not in MODES:raise ValueError('unknown route trial policy')
    if mode=='old':return base.choose(phase,initial['minimum'],candidates,learning,spent)
    adjusted=deepcopy(candidates);cost_learning=deepcopy(learning);cost_learning['fuel_bias_J']={}
    for action,c in candidates.items():
        total=0.;prior=initial
        for i,step in enumerate(c['series']):
            total+=model.predict(features(prior,step,i),prior['fuel_J']-step['fuel_J']);prior=step
        adjusted[action]['fuel_debit_J']=total
        if not math.isclose(base.score(adjusted[action],cost_learning),energy_score(c,initial,model,learning),abs_tol=1e-9):
            raise ValueError('energy scoring adapter disagrees')
    # Reuse every original admission, current-need and remaining-budget rule.
    return base.choose(phase,initial['minimum'],adjusted,cost_learning,spent)


class RouteTrial:
    def __init__(self,goal,session,model):
        self.goal=goal;self.session=deepcopy(session);self.model=model;self._prepared=None;self.validate()

    @property
    def body(self):return self.goal.body

    @property
    def task(self):return self.goal.task

    @classmethod
    def start(cls,goal,mode,model,knowledge):
        if mode not in MODES or model.stage!='frozen' or goal.task['status']!='running':
            raise ValueError('running goal, known policy and frozen model required')
        if knowledge['pending']:raise ValueError('unresolved knowledge')
        return cls(goal,dict(mode=mode,initial_goal_sha=goal.checkpoint()['sha256'],initial=base.state(goal),
            retained_knowledge=deepcopy(knowledge),max_ticks=230-goal.task['elapsed'],records=[],status='running'),model)

    def derived(self):
        learning=base.empty_learning()
        for row in self.session['records']:learning=base.learn(learning,row)
        return learning

    def validate(self):
        self.goal.validate();s=self.session;rows=s['records'];previous=s['initial_goal_sha'];before=s['initial']
        if s['mode'] not in MODES or self.model.stage!='frozen' or s['retained_knowledge']['pending']:
            raise ValueError('route trial policy/model/knowledge')
        if (s['max_ticks']!=230-before['elapsed'] or len(rows)>s['max_ticks'] or
            len(rows)!=self.task['elapsed']-before['elapsed']):raise ValueError('route trial budget/clock')
        learning=base.empty_learning();prior=[]
        for index,row in enumerate(rows):
            d=row['decision'];p=d['plan'];i=d['offset']
            if d['before_goal_sha']!=previous or d['before']!=before or d['index']!=index:
                raise ValueError('route trial predecessor')
            if base.needs_plan(prior,before):
                if i!=0 or p['origin_goal_sha']!=previous or p['initial']!=before or p['calibration']!=learning:
                    raise ValueError('route trial origin/calibration')
                action,reason=selection(s['mode'],before['goal_phase'],before,p['candidates'],learning,base.counts(prior),self.model)
                if (p['chosen'],p['reason'])!=(action,reason):raise ValueError('route trial selection')
            elif p!=prior[-1]['decision']['plan'] or i!=prior[-1]['decision']['offset']+1:
                raise ValueError('route trial continuation')
            expected=deepcopy(d['base_request']);expected['requested']=p['candidates'][p['chosen']]['series'][i]['requested']
            if d['request']!=expected or row['receipt']['event_id']!=expected['event_id']:
                raise ValueError('route trial receipt/request')
            if row['after']['elapsed']!=before['elapsed']+1 or abs(row['after']['time_s']-before['time_s']-1)>1e-8:
                raise ValueError('route trial native time')
            if row['feedback']!=base.feedback(row,learning,prior):raise ValueError('route trial feedback')
            learning=base.learn(learning,row);previous=row['after_goal_sha'];before=row['after'];prior.append(row)
        if previous!=self.goal.checkpoint()['sha256'] or before!=base.state(self.goal):raise ValueError('route trial head')
        if base.counts(rows)['observe']>3 or base.counts(rows)['recovery']>3:raise ValueError('route trial regulation budget')
        status='goal_finished' if self.task['status']!='running' else 'budget_exhausted' if len(rows)==s['max_ticks'] else 'running'
        if s['status']!=status:raise ValueError('route trial status')

    def checkpoint(self):
        self.validate();p=dict(schema=SCHEMA,sources=sources(),policy=base.POLICY,
            goal=self.goal.checkpoint(),session=deepcopy(self.session),model=self.model.checkpoint())
        return dict(payload=p,sha256=digest(p))

    @classmethod
    def restore(cls,envelope):
        p=envelope['payload']
        if digest(p)!=envelope['sha256'] or p['schema']!=SCHEMA or p['sources']!=sources() or p['policy']!=base.POLICY:
            raise ValueError('route trial checksum/source/policy')
        return cls(base.MotionGoal.restore(p['goal']),p['session'],EnergyCalibration.restore(p['model']))

    def prepare(self):
        self.validate()
        if self.session['status']!='running':raise ValueError('terminal route trial')
        rows=self.session['records'];initial=base.state(self.goal);request=self.goal.request();learning=self.derived()
        if base.needs_plan(rows,initial):
            spent=base.counts(rows);remaining=dict(prelude=6,route=220,closure=4)[self.task['phase']]-self.task['counts'][self.task['phase']]
            horizon=min(base.POLICY['horizon'],remaining)
            actions=['slow_breath'] if self.task['phase']!='route' else ['walk','observe','sleep' if initial['minimum']['sleep_pressure']>.85 else 'rest']
            owner=base.projection_owner(self.goal)
            candidates={a:base.rollout(self.goal,a,horizon,min(2,3-spent['recovery']) if a in ('rest','sleep') and spent['recovery']<3 else 1,owner=owner)
                for a in actions if a!='observe' or spent['observe']<3 if a not in ('rest','sleep') or spent['recovery']<3}
            action,reason=selection(self.session['mode'],self.task['phase'],initial,candidates,learning,spent,self.model)
            plan=dict(origin_goal_sha=self.goal.checkpoint()['sha256'],initial=initial,calibration=learning,
                      candidates=candidates,chosen=action,reason=reason);i=0
        else:plan=deepcopy(rows[-1]['decision']['plan']);i=rows[-1]['decision']['offset']+1
        actual=deepcopy(request);actual['requested']=plan['candidates'][plan['chosen']]['series'][i]['requested']
        self._prepared=dict(index=len(rows),before_goal_sha=self.goal.checkpoint()['sha256'],before=initial,
            base_request=request,request=actual,plan=plan,offset=i)
        return self._prepared

    def request(self):
        if self._prepared is None:self.prepare()
        return deepcopy(self._prepared['request'])

    def step(self):
        request=self.request();d=deepcopy(self._prepared);learning=self.derived()
        receipt=base.advance_motion(self.goal,request)
        row=dict(decision=d,receipt=deepcopy(receipt),after=base.state(self.goal),after_goal_sha=self.goal.checkpoint()['sha256'])
        row['feedback']=base.feedback(row,learning,self.session['records']);self.session['records'].append(row)
        if self.task['status']!='running':self.session['status']='goal_finished'
        elif len(self.session['records'])==self.session['max_ticks']:self.session['status']='budget_exhausted'
        self._prepared=None;self.validate();return receipt

    def prepare_receipt_replay(self,after,request):
        restored=type(self).restore(after);d=restored.session['records'][-1]['decision']
        if d['before_goal_sha']!=self.goal.checkpoint()['sha256'] or d['base_request']!=self.goal.request() or d['request']!=request:
            raise ValueError('route trial outcome predecessor')
        self._prepared=deepcopy(d)


class TrialJournal(base.MotionJournal):
    goal_type=RouteTrial
