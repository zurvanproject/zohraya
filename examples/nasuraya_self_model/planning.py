"""Progress-aware, error-corrected planning on the retained MotionGoal.

Forecasts use the retained owner's physiological/mechanical kernel on private
copies. Outer modules and future arbitration are omitted, deliberately making
these approximate forecasts. Only actual UnifiedBody receipts teach corrections.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

from .monitor import digest, snapshot
from .regulation import (MotionGoal, MotionJournal, advance_motion, report,
                         update_knowledge, NoSafeChoice)
from extension_state import attach,FIELDS

SCHEMA='nasuraya-progress-planning/1'
POLICY=dict(horizon=16,max_observations=3,max_recovery=3,learning_rate=.25,
            fuel_bias_limit_J=500.,eta_bias_limit_s=8.,fuel_seconds_per_J=.001)


def sources():
    here=Path(__file__).parent
    return {n:hashlib.sha256((here/n).read_bytes()).hexdigest()
            for n in ('planning.py','regulation.py','monitor.py')}


def state(goal):
    b=goal.body.owner.body();t=goal.task
    return dict(time_s=goal.body.owner.physical.state.time_s,elapsed=t['elapsed'],
                fuel_J=b['finite_stocks']['fuel_J'],minimum=deepcopy(b['minimum_state']),
                landings=len(t['landings']),last_landing_t_s=t['landings'][-1]['t_s'] if t['landings'] else None,
                goal_phase=t['phase'],goal_status=t['status'])


def empty_learning():
    return dict(fuel_bias_J={},fatigue_bias={},eta_bias_s={},samples={},eta_samples={})


def bounded_mean(old,error,limit):
    value=old+POLICY['learning_rate']*(error-old)
    return max(-limit,min(limit,value))


def feedback(row,learning,prior_rows=()):
    d=row['decision'];p=d['plan'];i=d['offset'];pred=p['candidates'][p['chosen']]['series'][i]
    prior=p['initial'] if i==0 else p['candidates'][p['chosen']]['series'][i-1]
    action=d['request']['requested'];before=d['before'];after=row['after']
    raw=prior['fuel_J']-pred['fuel_J'];used=before['fuel_J']-after['fuel_J']
    raw_fatigue=pred['minimum']['fatigue']-prior['minimum']['fatigue']
    observed_fatigue=after['minimum']['fatigue']-before['minimum']['fatigue']
    eta=p['candidates'][p['chosen']]['eta_s']
    landed=after['landings']>before['landings']
    settled=[];seen=set()
    if landed:
        for earlier in [*prior_rows,row]:
            old=earlier['decision']['plan'];origin=old['origin_goal_sha'];c=old['candidates'][old['chosen']]
            if origin in seen or old['initial']['landings']!=before['landings'] or c['eta_s'] is None:continue
            seen.add(origin);error=after['last_landing_t_s']-old['initial']['time_s']-c['eta_s']
            settled.append(dict(origin_goal_sha=origin,strategy=old['chosen'],error_s=error,
                corrected_error_s=error-old['calibration']['eta_bias_s'].get(old['chosen'],0.)))
    return dict(fuel_error_J=used-raw,
        corrected_fuel_error_J=used-raw-learning['fuel_bias_J'].get(action,0.),
        fatigue_error=observed_fatigue-raw_fatigue,
        corrected_fatigue_error=observed_fatigue-raw_fatigue-learning['fatigue_bias'].get(action,0.),
        landing_count_error=after['landings']-pred['landings'],
        eta_error_s=after['last_landing_t_s']-p['initial']['time_s']-eta if landed and eta is not None else None,
        settled_eta_errors=settled,
        actual_action=row['receipt']['owner']['selected_action'],
        admitted=row['receipt']['owner']['selected_action']==action)


def learn(learning,row):
    new=deepcopy(learning);f=row['feedback'];action=row['decision']['request']['requested']
    new['fuel_bias_J'][action]=bounded_mean(new['fuel_bias_J'].get(action,0.),f['fuel_error_J'],POLICY['fuel_bias_limit_J'])
    new['fatigue_bias'][action]=bounded_mean(new['fatigue_bias'].get(action,0.),f['fatigue_error'],.1)
    new['samples'][action]=new['samples'].get(action,0)+1
    for settled in f['settled_eta_errors']:
        strategy=settled['strategy']
        new['eta_bias_s'][strategy]=bounded_mean(new['eta_bias_s'].get(strategy,0.),settled['error_s'],POLICY['eta_bias_limit_s'])
        new['eta_samples'][strategy]=new['eta_samples'].get(strategy,0)+1
    return new


def counts(rows):
    actions=[r['decision']['request']['requested'] for r in rows]
    return dict(observe=actions.count('observe'),recovery=sum(a in ('rest','sleep') for a in actions))


def score(candidate,learning):
    eta=candidate['eta_s']
    time=(eta if eta is not None else candidate['horizon_s']+8.)+learning['eta_bias_s'].get(candidate['strategy'],0.)
    fuel=candidate['fuel_debit_J']+sum(learning['fuel_bias_J'].get(s['requested'],0.) for s in candidate['series'])
    fatigue=candidate['series'][-1]['minimum']['fatigue']+sum(learning['fatigue_bias'].get(s['requested'],0.) for s in candidate['series'])
    return max(1.,time)+POLICY['fuel_seconds_per_J']*max(0.,fuel)+10.*max(0.,fatigue-.52)


def choose(phase,minimum,candidates,learning,spent):
    if phase!='route':
        if not candidates['slow_breath']['valid']:raise NoSafeChoice('required closure/prelude forecast invalid')
        return 'slow_breath','retain required prelude/closure'
    valid={a:c for a,c in candidates.items() if c['valid']}
    valid={a:c for a,c in valid.items() if
           spent['observe']+sum(s['requested']=='observe' for s in c['series'])<=POLICY['max_observations'] and
           spent['recovery']+sum(s['requested'] in ('rest','sleep') for s in c['series'])<=POLICY['max_recovery']}
    need=minimum['sleep_pressure']>.85 or minimum['fatigue']>.52 or minimum['pain']>.40
    recovery='sleep' if minimum['sleep_pressure']>.85 else 'rest'
    if need and recovery in valid:return recovery,'current body need before route progress'
    if minimum['posture'] not in ('double_support','settle'):valid.pop('observe',None)
    if not valid:raise NoSafeChoice('no valid progress plan inside remaining budgets')
    action=min(valid,key=lambda a:(score(valid[a],learning),a))
    return action,'minimum corrected time and fuel cost to next confirmed landing'


def projection_owner(goal):
    # Match the canonical owner reconstructed by actual cycle(). Transient
    # attributes excluded by persistence must not change a cold forecast.
    original=goal.body.owner
    owner=type(original).restore(original.checkpoint())
    controller={k:deepcopy(getattr(original.physical,k)) for k in FIELDS if hasattr(original.physical,k)}
    return attach(SimpleNamespace(owner=owner),controller).owner


def rollout(goal,first,horizon,prefix=1,owner=None):
    """No owner ticks: approximate native-owner projection, not UnifiedBody replay."""
    owner=deepcopy(projection_owner(goal) if owner is None else owner);p=owner.physical;initial=state(goal)
    before_steps=p.state.walk_steps;series=[];valid=True;eta=None
    external=goal.request()['external']['native']
    for i in range(horizon):
        action=first if i<prefix or goal.task['phase']!='route' else 'walk'
        result=owner._simulate(action,1.,external,actual=False,log=False)
        view=owner.body();new=p.state.walk_steps-before_steps
        series.append(dict(requested=action,time_s=p.state.time_s,fuel_J=view['finite_stocks']['fuel_J'],
                           minimum=deepcopy(view['minimum_state']),landings=initial['landings']+new))
        valid=valid and result['physical_model_valid']
        if new:
            events=[e for f in result['frames'] for e in f['posture']['events_this_frame']
                    if e['name']=='touchdown' and e.get('kind')=='walk']
            eta=min(e['t_s'] for e in events)-initial['time_s'] if events else p.state.time_s-initial['time_s']
        if new or not valid:break
    return dict(strategy=first,valid=valid,series=series,eta_s=eta,horizon_s=len(series),
                fuel_debit_J=initial['fuel_J']-series[-1]['fuel_J'],
                scope='approximate retained owner kernel; outer modules and future action arbitration omitted')


def needs_plan(rows,current):
    if not rows:return True
    last=rows[-1];d=last['decision'];c=d['plan']['candidates'][d['plan']['chosen']]
    m=current['minimum'];need=m['sleep_pressure']>.85 or m['fatigue']>.52 or m['pain']>.40
    fresh_recovery=need and counts(rows)['recovery']<3 and (
        d['offset']+1>=len(c['series']) or c['series'][d['offset']+1]['requested'] not in ('rest','sleep'))
    return (fresh_recovery or d['offset']+1>=len(c['series']) or current['goal_phase']!=d['before']['goal_phase'] or
            current['landings']>d['before']['landings'] or not last['feedback']['admitted'])


class PlanningGoal:
    def __init__(self,goal,session):
        self.goal=goal;self.session=deepcopy(session);self._prepared=None;self.validate()

    @property
    def body(self):return self.goal.body

    @property
    def task(self):return self.goal.task

    @classmethod
    def start(cls,goal,knowledge,*,session_id):
        goal.validate()
        if goal.task['status']!='running' or knowledge['pending']:raise ValueError('running resolved goal required')
        if not isinstance(session_id,str) or not session_id or len(session_id)>60:raise ValueError('bounded session id')
        remaining=sum(limit-goal.task['counts'][p] for p,limit in dict(prelude=6,route=220,closure=4).items())
        return cls(goal,dict(session_id=session_id,goal_id=goal.task['goal_id'],initial_goal_sha=goal.checkpoint()['sha256'],
            initial=state(goal),initial_knowledge=deepcopy(knowledge),max_ticks=remaining,records=[],status='running'))

    def derived(self):
        learning=empty_learning();knowledge=deepcopy(self.session['initial_knowledge'])
        for row in self.session['records']:
            learning=learn(learning,row)
            if row['decision']['offset']==0:
                d=row['decision'];knowledge=update_knowledge(knowledge,dict(observation=d['plan']['observation'],request=d['request']),row['receipt'])
        return learning,knowledge

    def validate(self):
        self.goal.validate();s=self.session;rows=s['records'];previous=s['initial_goal_sha'];before=s['initial']
        if (s['max_ticks']!=230-before['elapsed'] or s['goal_id']!=self.task['goal_id'] or
            len(rows)!=self.task['elapsed']-before['elapsed'] or len(rows)>s['max_ticks']):
            raise ValueError('planning goal clock/lineage')
        learning=empty_learning();knowledge=deepcopy(s['initial_knowledge']);prior=[]
        for index,row in enumerate(rows):
            d=row['decision'];p=d['plan'];offset=d['offset']
            if d['before_goal_sha']!=previous or d['before']!=before or d['index']!=index:
                raise ValueError('planning decision predecessor')
            new=needs_plan(prior,before)
            if new:
                if offset!=0 or p['origin_goal_sha']!=previous or p['initial']!=before or p['calibration']!=learning:
                    raise ValueError('planning origin/calibration')
                if p['self_report']!=report(knowledge,p['observation'],d['base_request']):raise ValueError('planning self-report')
                action,reason=choose(before['goal_phase'],before['minimum'],p['candidates'],learning,counts(prior))
                if p['chosen']!=action or p['reason']!=reason:raise ValueError('planning selection')
            elif p!=prior[-1]['decision']['plan'] or offset!=prior[-1]['decision']['offset']+1:
                raise ValueError('planning sequence continuation')
            expected=deepcopy(d['base_request']);expected['requested']=p['candidates'][p['chosen']]['series'][offset]['requested']
            if d['request']!=expected or row['receipt']['event_id']!=expected['event_id']:
                raise ValueError('planning request/receipt')
            if row['after']['elapsed']!=before['elapsed']+1 or abs(row['after']['time_s']-before['time_s']-1)>1e-8:
                raise ValueError('planning time cost')
            if row['feedback']!=feedback(row,learning,prior):raise ValueError('planning feedback mismatch')
            learning=learn(learning,row)
            if offset==0:knowledge=update_knowledge(knowledge,dict(observation=p['observation'],request=expected),row['receipt'])
            previous=row['after_goal_sha'];before=row['after'];prior.append(row)
        if previous!=self.goal.checkpoint()['sha256'] or before!=state(self.goal):raise ValueError('planning head mismatch')
        spent=counts(rows)
        if spent['observe']>3 or spent['recovery']>3:raise ValueError('planning regulation budget')
        status='goal_finished' if self.task['status']!='running' else 'budget_exhausted' if len(rows)==s['max_ticks'] else 'running'
        if s['status']!=status:raise ValueError('planning status')

    def checkpoint(self):
        self.validate();p=dict(schema=SCHEMA,sources=sources(),policy=POLICY,goal=self.goal.checkpoint(),session=deepcopy(self.session))
        return dict(payload=p,sha256=digest(p))

    @classmethod
    def restore(cls,envelope):
        p=envelope['payload']
        if digest(p)!=envelope['sha256'] or p['schema']!=SCHEMA or p['sources']!=sources() or p['policy']!=POLICY:
            raise ValueError('planning source/checksum')
        return cls(MotionGoal.restore(p['goal']),p['session'])

    def prepare(self):
        self.validate()
        if self.session['status']!='running':raise ValueError('planning already terminal')
        rows=self.session['records'];current=state(self.goal);base=self.goal.request();learning,knowledge=self.derived()
        if needs_plan(rows,current):
            obs=snapshot(self.body);remaining=dict(prelude=6,route=220,closure=4)[self.task['phase']]-self.task['counts'][self.task['phase']]
            horizon=min(POLICY['horizon'],remaining);spent=counts(rows)
            actions=['slow_breath'] if self.task['phase']!='route' else ['walk','observe','sleep' if current['minimum']['sleep_pressure']>.85 else 'rest']
            owner=projection_owner(self.goal)
            candidates={a:rollout(self.goal,a,horizon,min(2,3-spent['recovery']) if a in ('rest','sleep') and spent['recovery']<3 else 1,owner=owner)
                        for a in actions if a!='observe' or spent['observe']<3 if a not in ('rest','sleep') or spent['recovery']<3}
            chosen,reason=choose(self.task['phase'],current['minimum'],candidates,learning,spent)
            plan=dict(origin_goal_sha=self.goal.checkpoint()['sha256'],initial=current,observation=obs,
                      self_report=report(knowledge,obs,base),calibration=learning,candidates=candidates,chosen=chosen,reason=reason)
            offset=0
        else:
            plan=deepcopy(rows[-1]['decision']['plan']);offset=rows[-1]['decision']['offset']+1
        request=deepcopy(base);request['requested']=plan['candidates'][plan['chosen']]['series'][offset]['requested']
        self._prepared=dict(index=len(rows),before_goal_sha=self.goal.checkpoint()['sha256'],before=current,
                            base_request=base,request=request,plan=plan,offset=offset)
        return self._prepared

    def request(self):
        if self._prepared is None:self.prepare()
        return deepcopy(self._prepared['request'])

    def step(self):
        request=self.request();decision=deepcopy(self._prepared);learning,_=self.derived()
        receipt=advance_motion(self.goal,request)
        row=dict(decision=decision,receipt=deepcopy(receipt),after=state(self.goal),after_goal_sha=self.goal.checkpoint()['sha256'])
        row['feedback']=feedback(row,learning,self.session['records']);self.session['records'].append(row)
        if self.task['status']!='running':self.session['status']='goal_finished'
        elif len(self.session['records'])==self.session['max_ticks']:self.session['status']='budget_exhausted'
        self._prepared=None;self.validate();return receipt

    def prepare_receipt_replay(self,after,request):
        restored=type(self).restore(after);d=restored.session['records'][-1]['decision']
        if d['before_goal_sha']!=self.goal.checkpoint()['sha256'] or d['base_request']!=self.goal.request() or d['request']!=request:
            raise ValueError('planning outcome predecessor')
        self._prepared=deepcopy(d)


class PlanningJournal(MotionJournal):
    goal_type=PlanningGoal
