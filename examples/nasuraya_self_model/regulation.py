"""Bounded goal-directed choice on the accumulated body, with durable effects.

Observation/recovery consume the existing route time budget. Only a veto of an
intended walk counts toward the three-walk-veto closure. No native guard changes.
Counterfactuals are full UnifiedBody cycles on private copies, not owner actions.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import sys

from .monitor import ROOT,SelfModel,snapshot,context,digest,source as monitor_source
sys.path.insert(0,str(ROOT/'examples/nasuraya_star_motion'))
from motion_goal import MotionGoal,LIMITS
from motion_journal import MotionJournal

SCHEMA='nasuraya-goal-directed-regulation/1'
POLICY=dict(max_observations=3,max_recovery=3)


def sources():
    return dict(regulation=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),monitor=monitor_source())


class NoSafeChoice(ValueError):pass


class KnowledgeView:
    def __init__(self,state):self.state=state
    def verify(self):return deepcopy(self.state)


def report(state,observation,request):
    return SelfModel.inspect(KnowledgeView(state),observation,request)


def select(phase,self_report,candidates,counts,assessed):
    """Fixed inspectable policy; native forecasts and owner guards retain veto."""
    if phase!='route':return 'slow_breath','retain required prelude/closure'
    valid={k:v for k,v in candidates.items() if v['valid']}
    m=self_report['observed']['minimum'];key=self_report['inferred']['context']
    recovery='sleep' if m['sleep_pressure']>.85 else 'rest'
    needs_recovery=m['sleep_pressure']>.85 or m['fatigue']>.52 or m['pain']>.40
    if needs_recovery and recovery in valid and counts['recovery']<POLICY['max_recovery']:
        return recovery,'current body need favors bounded recovery'
    uncertain=self_report['recommendation']=='pause_and_observe'
    if uncertain and key not in assessed and 'observe' in valid and counts['observe']<POLICY['max_observations']:
        return 'observe','replace passive pause with one paid observation for this context'
    if 'walk' in valid and valid['walk']['actual']=='walk':
        return 'walk','fresh whole-body counterfactual admits a bounded goal-directed move'
    if recovery in valid and counts['recovery']<POLICY['max_recovery'] and valid[recovery]['recovery_gain']>1e-8:
        return recovery,'movement not admitted; forecast favors bounded recovery'
    if 'observe' in valid and counts['observe']<POLICY['max_observations']:
        return 'observe','refresh body evidence while the requested move is not admitted'
    if 'walk' in valid:
        return 'walk','bounded native arbitration; retain actual walk-veto closure'
    raise NoSafeChoice('no valid candidate within remaining observation/recovery budgets')


def update_knowledge(state,decision,receipt):
    state=deepcopy(state);key=context(decision['observation'],decision['request'])
    matched=receipt['owner']['selected_action']==decision['request']['requested'] and receipt['owner']['physical_model_valid']
    s,f=state['counts'].get(key,(0,0));state['counts'][key]=[s+int(matched),f+int(not matched)]
    state['episodes']+=1
    state['last']=dict(requested=decision['request']['requested'],actual=receipt['owner']['selected_action'],
        admitted=matched,receipt_sha256=digest(receipt),native_prediction_error=receipt['owner']['prediction']['mean_scaled_absolute_error'])
    return state


def advance_motion(goal,request):
    """Shared one-tick bookkeeping; all native guards remain authoritative."""
    q=request;t=goal.task;p=goal.body.owner.physical
    phase=t['phase'];before_time=p.state.time_s;cursor=deepcopy(p.star_started)
    receipt=goal.body.cycle(**q);p=goal.body.owner.physical
    new=[deepcopy(e) for e in p.state.events if e['name']=='touchdown' and e.get('kind')=='walk' and e['t_s']>before_time+1e-8]
    if len(new)!=sum(p.star_started[s]-cursor[s] for s in ('L','R')):raise ValueError('native landing mismatch')
    t['landings'].extend(new);t['counts'][phase]+=1;t['elapsed']+=1
    if not receipt['owner']['physical_model_valid']:
        t.update(phase='done',status='physical_failure',stop_reason=p.state.failed_reason);p.star_enabled=False
    elif phase=='prelude' and t['counts']['prelude']==LIMITS['prelude']:
        t['phase']='route';p.star_enabled=True
    elif phase=='route':
        # Intentional observation/recovery preserves the native walk-veto
        # streak; only an admitted walk clears it. No three-veto bypass.
        if q['requested']=='walk':t['vetoes']=t['vetoes']+1 if receipt['owner']['selected_action']!='walk' else 0
        complete=all(p.star_started[s]==len(t['plan'][s]) for s in ('L','R'))
        if complete or t['vetoes']>=3 or t['counts']['route']==LIMITS['route']:
            t['phase']='closure';p.star_enabled=False
            if not complete:t['stop_reason']='three consecutive native vetoes' if t['vetoes']>=3 else 'movement budget exhausted'
    elif phase=='closure' and t['counts']['closure']==LIMITS['closure']:
        complete=all(p.star_started[s]==len(t['plan'][s]) for s in ('L','R'))
        home=max(math.dist(p.state.feet_m[s],t['home'][s]) for s in ('L','R'))
        ok=complete and home<1e-9 and p.state.phase=='double_support'
        t.update(phase='done',status='completed' if ok else 'incomplete')
        if not ok and t['stop_reason'] is None:t['stop_reason']='home or closure contract'
    goal.validate()
    return receipt


class RegulatedGoal:
    def __init__(self,goal,session):
        self.goal=goal;self.session=deepcopy(session);self._prepared=None;self.validate()

    @property
    def body(self):return self.goal.body

    @property
    def task(self):return self.goal.task

    @classmethod
    def start(cls,goal,knowledge,*,session_id,max_ticks=8,target_new_landings=1):
        if not isinstance(session_id,str) or not session_id or len(session_id)>60:raise ValueError('bounded session id')
        if type(max_ticks) is not int or not 1<=max_ticks<=12:raise ValueError('session budget 1..12 ticks')
        if knowledge['pending']:raise ValueError('reconcile self-model result before regulation')
        goal.validate()
        if goal.task['status']!='running':raise ValueError('existing running goal required')
        if type(target_new_landings) is not int or not 0<=target_new_landings<=14-len(goal.task['landings']):
            raise ValueError('bounded confirmed-landing session target')
        state=dict(session_id=session_id,goal_id=goal.task['goal_id'],max_ticks=max_ticks,
            target_new_landings=target_new_landings,initial_landings=len(goal.task['landings']),
            initial_elapsed=goal.task['elapsed'],initial_goal_sha=goal.checkpoint()['sha256'],
            initial_knowledge=deepcopy(knowledge),records=[],status='running')
        return cls(goal,state)

    def derived(self):
        knowledge=deepcopy(self.session['initial_knowledge']);counts=dict(observe=0,recovery=0,walk=0,required=0);assessed=[]
        for row in self.session['records']:
            d=row['decision'];a=d['request']['requested']
            if d['phase']!='route':counts['required']+=1
            elif a=='observe':
                counts['observe']+=1
                if d['self_report']['inferred']['context'] not in assessed:assessed.append(d['self_report']['inferred']['context'])
            elif a in ('rest','sleep'):counts['recovery']+=1
            else:counts['walk']+=1
            knowledge=update_knowledge(knowledge,d,row['receipt'])
        return knowledge,counts,assessed

    def validate(self):
        self.goal.validate();s=self.session
        if s['goal_id']!=self.task['goal_id'] or type(s['max_ticks']) is not int or not 1<=s['max_ticks']<=12:
            raise ValueError('session goal/budget changed')
        if len(s['records'])!=self.task['elapsed']-s['initial_elapsed'] or len(s['records'])>s['max_ticks']:
            raise ValueError('session/native clock mismatch')
        previous=s['initial_goal_sha'];knowledge=deepcopy(s['initial_knowledge']);counts=dict(observe=0,recovery=0,walk=0,required=0);assessed=[]
        for index,row in enumerate(s['records']):
            d=row['decision'];r=row['receipt']
            if d['before_goal_sha']!=previous or d['goal_id']!=s['goal_id'] or d['index']!=index:
                raise ValueError('decision lineage mismatch')
            if d['self_report']!=report(knowledge,d['observation'],d['base_request']):raise ValueError('decision knowledge mismatch')
            action,reason=select(d['phase'],d['self_report'],d['candidates'],counts,assessed)
            expected=deepcopy(d['base_request']);expected['requested']=action
            if d['request']!=expected or d['reason']!=reason or r['event_id']!=expected['event_id']:
                raise ValueError('decision/action mismatch')
            if d['phase']!='route':counts['required']+=1
            elif action=='observe':counts['observe']+=1;assessed.append(d['self_report']['inferred']['context'])
            elif action in ('rest','sleep'):counts['recovery']+=1
            else:counts['walk']+=1
            knowledge=update_knowledge(knowledge,d,r);previous=row['after_goal_sha']
        if previous!=self.goal.checkpoint()['sha256']:raise ValueError('goal advanced outside this session')
        target_met=s['target_new_landings']>0 and len(self.task['landings'])-s['initial_landings']>=s['target_new_landings']
        expected_status='goal_finished' if self.task['status']!='running' else 'target_reached' if target_met else 'budget_exhausted' if len(s['records'])==s['max_ticks'] else 'running'
        if s['status']!=expected_status:raise ValueError('session terminal state mismatch')
        if counts['observe']>POLICY['max_observations'] or counts['recovery']>POLICY['max_recovery']:
            raise ValueError('regulation budget exhausted')

    def checkpoint(self):
        self.validate()
        p=dict(schema=SCHEMA,sources=sources(),policy=POLICY,goal=self.goal.checkpoint(),session=deepcopy(self.session))
        return dict(payload=p,sha256=digest(p))

    @classmethod
    def restore(cls,envelope):
        if set(envelope)!={'payload','sha256'} or digest(envelope['payload'])!=envelope['sha256']:
            raise ValueError('regulated goal checksum')
        p=envelope['payload']
        if p['schema']!=SCHEMA or p['sources']!=sources() or p['policy']!=POLICY:raise ValueError('regulated source/policy')
        return cls(MotionGoal.restore(p['goal']),p['session'])

    def _preview(self,base,action):
        clone=deepcopy(self.body);q=deepcopy(base);q['requested']=action
        before=clone.owner.body()['minimum_state'];fuel=clone.owner.owner.body.state.fuel_J
        steps=clone.owner.physical.state.walk_steps
        r=clone.cycle(**q);after=clone.owner.body()['minimum_state']
        return dict(valid=r['owner']['physical_model_valid'],actual=r['owner']['selected_action'],
            receipt_sha256=digest(r),fuel_debit_J=fuel-clone.owner.owner.body.state.fuel_J,
            confirmed_landings=clone.owner.physical.state.walk_steps-steps,
            recovery_gain=sum(before[k]-after[k] for k in ('sleep_pressure','fatigue','pain')),
            balance=after['balance'],scope='full same-model private counterfactual; zero owner ticks')

    def prepare(self):
        self.validate()
        if self.session['status']!='running':raise ValueError('regulated session already terminal')
        base=self.goal.request();knowledge,counts,assessed=self.derived();obs=snapshot(self.body)
        self_report=report(knowledge,obs,base)
        choices=['slow_breath'] if self.task['phase']!='route' else ['walk','observe','sleep' if obs['minimum']['sleep_pressure']>.85 else 'rest']
        before=self.body.checkpoint()['sha256']
        candidates={a:self._preview(base,a) for a in choices}
        if self.body.checkpoint()['sha256']!=before:raise ValueError('counterfactual mutated owner')
        action,reason=select(self.task['phase'],self_report,candidates,counts,assessed)
        q=deepcopy(base);q['requested']=action
        self._prepared=dict(index=len(self.session['records']),goal_id=self.task['goal_id'],phase=self.task['phase'],
            before_goal_sha=self.goal.checkpoint()['sha256'],base_request=base,request=q,observation=obs,
            self_report=self_report,candidates=candidates,reason=reason)
        return self._prepared

    def request(self):
        if self._prepared is None:self.prepare()
        return deepcopy(self._prepared['request'])

    def prepare_receipt_replay(self,after,request):
        """Reuse persisted counterfactual evidence during receipt reconciliation."""
        restored=type(self).restore(after)
        d=restored.session['records'][-1]['decision']
        knowledge,counts,assessed=self.derived()
        if d['before_goal_sha']!=self.goal.checkpoint()['sha256'] or d['base_request']!=self.goal.request():
            raise ValueError('recorded decision predecessor')
        if d['observation']!=snapshot(self.body) or d['self_report']!=report(knowledge,d['observation'],d['base_request']):
            raise ValueError('recorded decision observation')
        action,reason=select(d['phase'],d['self_report'],d['candidates'],counts,assessed)
        if d['request']!=request or action!=request['requested'] or reason!=d['reason']:
            raise ValueError('recorded choice mismatch')
        self._prepared=deepcopy(d)

    def step(self):
        q=self.request();d=deepcopy(self._prepared);t=self.task;p=self.body.owner.physical
        receipt=advance_motion(self.goal,q)
        if digest(receipt)!=d['candidates'][q['requested']]['receipt_sha256']:
            raise ValueError('owner result differs from selected counterfactual')
        self.session['records'].append(dict(decision=d,receipt=deepcopy(receipt),after_goal_sha=self.goal.checkpoint()['sha256']))
        if t['status']!='running':self.session['status']='goal_finished'
        elif self.session['target_new_landings']>0 and len(t['landings'])-self.session['initial_landings']>=self.session['target_new_landings']:
            self.session['status']='target_reached'
        elif len(self.session['records'])==self.session['max_ticks']:self.session['status']='budget_exhausted'
        self._prepared=None;self.validate();return receipt


class RegulationJournal(MotionJournal):
    goal_type=RegulatedGoal
