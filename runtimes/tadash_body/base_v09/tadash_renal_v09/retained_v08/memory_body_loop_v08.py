"""Historical lessons influence optional verification, never body physics.

The V07 physical and cognitive sources stay unchanged. A context boundary
quarantines old environmental samples and pending acquisitions while keeping
the one physical owner's resources, damage, fatigue and clock exactly.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from brain_body_loop_v07 import BrainBodyLoop, BrainEnvironment, EnvironmentBrain, Goal, Observation
from cognitive_workspace_v07 import canonical, digest, identity
from durable_memory_v08 import DurableMemory, atomic_save, source_hash, scoped_key

ROOT=Path(__file__).parent
SCHEMA='tadash-memory-body/0.8'


def module_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ExperienceBrain(EnvironmentBrain):
    def _policy(self, e, p, conflict, body, accessible):
        result=super()._policy(e,p,conflict,body,accessible)
        lesson=getattr(self,'remembered_verification_rule',None)
        fresh=[];seen=set();topics={r['id']:r['topic'] for r in self.entries}
        for row in reversed(self.provenance):
            group=row['group_key']
            if (topics.get(row['id'])==e.goal.topic and row['kind']=='simulated_observation'
                and row['used_independently'] and 0.<=e.time_s-row['sampled_at_s']<=6.
                and group not in seen):
                seen.add(group);fresh.append(row)
        ready=len(fresh)>=2 and all(r['value']==1 for r in fresh[:2])
        applied=bool(lesson and result['kind']=='act' and not ready)
        if applied:
            pending=next((q for q in self.pending.values() if q['topic']==e.goal.topic),None)
            can_query=(e.goal.deadline_s-e.time_s>=e.goal.query_latency_s+e.goal.action_duration_s
                and len(self.pending)<8)
            result.update(kind='wait_for_receipt' if pending else ('query' if can_query else 'abstain'),
                command='stand',reason='remembered_report_variability_requires_new_verification')
        result['durable_memory']=dict(lesson_id=lesson['id'] if lesson else None,
            support_ids=list(lesson['support_ids']) if lesson else [],
            historical_samples_used_as_live_evidence=0,
            latest_independent_fresh_values=[r['value'] for r in fresh[:2]],
            two_fresh_positive_samples_ready=ready,optional_action_guard_applied=applied)
        return result


class MemoryBodyLoop:
    def __init__(self, loop=None, memory=None, *, context='continued_route', epoch='live_v08', enabled=True):
        identity(context,'environment context');identity(epoch,'environment epoch')
        if type(enabled) is not bool:raise ValueError('durable policy flag required')
        self.loop=loop or BrainBodyLoop()
        self.memory=memory or DurableMemory()
        self.context=context;self.epoch=epoch;self.enabled=enabled
        self.active_goal_id=None;self.cache={}
        self.loop.brain.__class__=ExperienceBrain
        self.memory.register_source('runtime_v08',module_hash(),'declared_runtime_journal')

    def remember_goal(self, goal, *, target_touchdowns=None, completed_touchdowns=0, source_ref='runtime_v08'):
        self.memory.remember_goal(self.context,self.epoch,goal,source_ref,
            target_touchdowns=target_touchdowns,completed_touchdowns=completed_touchdowns)
        self.active_goal_id=goal.id

    def resume_goal(self):
        if self.active_goal_id is None:raise ValueError('no active goal identity')
        return self.memory.resume_goal(self.context,self.active_goal_id)

    def new_environment_epoch(self, epoch, *, context=None):
        identity(epoch,'new environment epoch');context=context or self.context;identity(context,'new context')
        if (context,epoch)==(self.context,self.epoch):raise ValueError('epoch must change')
        work=deepcopy(self);now=work.loop.physical.state.time_s
        cancelled=[]
        for action,pending in work.loop.brain.pending.items():
            cancelled.append(dict(id='cancel:'+digest([work.context,work.epoch,action])[:30],
                kind='query_status',context=work.context,epoch=work.epoch,topic=pending['topic'],
                sampled_at_s=now,source_ref='runtime_v08',source_record=action,
                payload=dict(status='cancelled_on_epoch_boundary',action_id=action,
                    outcome_observed=False)))
        if cancelled:
            stream=scoped_key(work.context,work.epoch)
            work.memory.record_batch(work.context,work.epoch,work.memory.streams.get(stream,-1)+1,cancelled)
        if context!=work.context:work.active_goal_id=None
        flags=deepcopy(work.loop.brain.config)
        work.loop.brain=ExperienceBrain(**flags)
        work.loop.command='stand';work.loop.next_tick_s=now;work.loop.last_goal_id=None
        work.loop.cache={};work.cache={};work.context=context;work.epoch=epoch
        self.__dict__=work.__dict__
        return dict(cancelled_unconfirmed_queries=len(cancelled),old_sensor_records_are_history=True,
            physical_owner_time_s=now,physical_owner_advanced=False)

    def step(self,e):
        if not isinstance(e,BrainEnvironment):raise ValueError('BrainEnvironment required')
        request=canonical(asdict(e))
        if e.event_id in self.cache:
            if self.cache[e.event_id]['request']!=request:raise ValueError('memory event identity changed')
            return deepcopy(self.cache[e.event_id]['result'])
        work=deepcopy(self)
        if work.active_goal_id is None:work.remember_goal(e.goal)
        goal,goal_record=work.resume_goal()
        if goal!=e.goal:raise ValueError('incoming task differs from remembered active goal')
        recalled=work.memory.recall(work.context,e.goal.topic)
        policy=next((l for l in recalled if l['kind']=='verify_variable_reports'),None) if work.enabled else None
        work.loop.brain.remembered_verification_rule=deepcopy(policy)
        previous_ids={r['id'] for r in work.loop.brain.entries}
        prior_pending=deepcopy(work.loop.brain.pending)
        frame=work.loop.step(e)
        rows=[]
        for r in work.loop.brain.entries:
            if r['id'] in previous_ids:continue
            rows.append(dict(id='sensor:'+digest([work.context,work.epoch,r['id']])[:32],
                kind='sensor_observation',context=work.context,epoch=work.epoch,topic=r['topic'],
                sampled_at_s=r['sampled_at_s'],source_ref='runtime_v08',source_record=r['id'],payload=deepcopy(r)))
        receipt=frame['cognition']['execution_receipt']
        physical_payload=dict(**deepcopy(receipt),
            optional_pause_executed=bool(frame['task']['nonessential_pause_executed']))
        if receipt['executed_walk_touchdowns'] or receipt['query_submitted'] or receipt['body_veto']:
            rows.append(dict(id='physical:'+digest([work.context,work.epoch,e.event_id])[:32],
                kind='physical_receipt',context=work.context,epoch=work.epoch,topic=e.goal.topic,
                sampled_at_s=frame['t_s'],source_ref='runtime_v08',source_record=e.event_id,payload=physical_payload))
        matched={r['action_id'] for r in (frame['cognition']['current'] or {}).get('matched_receipts',[])}
        for action,pending in prior_pending.items():
            if action not in work.loop.brain.pending and action not in matched and frame['t_s']>pending['expires_at_s']:
                rows.append(dict(id='timeout:'+digest([work.context,work.epoch,action])[:32],
                    kind='query_status',context=work.context,epoch=work.epoch,topic=pending['topic'],
                    sampled_at_s=frame['t_s'],source_ref='runtime_v08',source_record=action,
                    payload=dict(status='expired_without_receipt',action_id=action,outcome_observed=False)))
        stream=scoped_key(work.context,work.epoch)
        work.memory.record_batch(work.context,work.epoch,work.memory.streams.get(stream,-1)+1,rows)
        if rows:work.memory.consolidate()
        work.memory.update_goal(work.context,e.goal.id,frame['t_s'],receipt['executed_walk_touchdowns'],receipt['body_valid'])
        frame['durable_memory']=dict(context=work.context,epoch=work.epoch,policy_enabled=work.enabled,
            recalled_lesson_ids=[r['id'] for r in recalled],
            newly_recorded_episode_ids=[r['id'] for r in rows],
            historical_evidence_reinjected_as_sensor_data=0,
            occupancy=dict(episodes=len(work.memory.episodes),lessons=len(work.memory.lessons),goals=len(work.memory.goals)),
            active_goal=deepcopy(work.memory.goals[scoped_key(work.context,e.goal.id)]))
        work.cache[e.event_id]=dict(request=request,result=deepcopy(frame))
        work.cache=dict(list(work.cache.items())[-32:])
        self.__dict__=work.__dict__
        return deepcopy(frame)

    def checkpoint(self):
        payload=canonical(dict(schema=SCHEMA,source_sha256=module_hash(),memory_source_sha256=source_hash(),
            loop=self.loop.checkpoint(),memory=self.memory.checkpoint(),
            wrapper={k:deepcopy(getattr(self,k)) for k in ('context','epoch','enabled','active_goal_id','cache')}))
        return dict(payload=payload,sha256=digest(payload))

    def save(self,path):
        atomic_save(path,self.checkpoint())

    @classmethod
    def restore(cls,checkpoint):
        try:
            p=deepcopy(checkpoint['payload'])
            if (p['schema']!=SCHEMA or checkpoint['sha256']!=digest(p)
                or p['source_sha256']!=module_hash() or p['memory_source_sha256']!=source_hash()):
                raise ValueError('memory/body integrity/source mismatch')
            loop=BrainBodyLoop.restore(p['loop']);memory=DurableMemory.restore(p['memory'])
            w=p['wrapper']
            obj=cls(loop,memory,context=w['context'],epoch=w['epoch'],enabled=w['enabled'])
            obj.active_goal_id=w['active_goal_id'];obj.cache=w['cache']
            if len(obj.cache)>32:raise ValueError('memory event cache capacity exceeded')
            if obj.active_goal_id is not None:
                key=scoped_key(obj.context,obj.active_goal_id)
                if key not in obj.memory.goals:raise ValueError('active goal has no durable record')
            return obj
        except (KeyError,TypeError,AttributeError) as e:raise ValueError('malformed memory/body checkpoint') from e
