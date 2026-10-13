"""Bounded, source-tagged historical memory; never a sensor interface.

Checksums detect accidental corruption. They do not authenticate a sensor or
prove biological memory. Learned records belong to the runtime, not DNA.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from cognitive_workspace_v07 import Goal, EnvironmentBrain, canonical, digest, identity, numeric, SOURCES

SCHEMA = 'tadash-durable-experience/0.8'
LIMITS = dict(episodes=512, lessons=64, goals=32, sources=64, streams=64, receipts=32, recall=4)
KINDS = {'sensor_observation', 'physical_receipt', 'query_status'}


def scoped_key(context, component):
    return json.dumps([context, component], ensure_ascii=False, separators=(',', ':'))


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def atomic_save(path, value):
    """Replace one complete checkpoint, with no partially written result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
    fd, temp = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(temp): os.unlink(temp)


class DurableMemory:
    def __init__(self):
        self.episodes = []
        self.lessons = {}
        self.goals = {}
        self.sources = {}
        self.streams = {}
        self.receipts = {}
        self.revision = 0

    def register_source(self, name, sha256, origin):
        identity(name, 'source reference')
        if not isinstance(sha256, str) or len(sha256)!=64 or any(x not in '0123456789abcdef' for x in sha256):
            raise ValueError('source SHA-256 required')
        if origin not in {'retained_trace', 'declared_runtime_journal', 'test_fixture'}:
            raise ValueError('source origin required')
        row = dict(sha256=sha256, origin=origin)
        if name in self.sources and self.sources[name]!=row:
            raise ValueError('source identity cannot be reassigned')
        if name not in self.sources and len(self.sources)>=LIMITS['sources']:
            raise ValueError('source capacity reached')
        self.sources[name]=row

    def _validate_episode(self, row):
        required={'id','kind','context','epoch','topic','sampled_at_s','source_ref','source_record','payload'}
        if not isinstance(row,dict) or set(row)!=required:
            raise ValueError('historical episode contract mismatch')
        for k in ('id','context','epoch','topic','source_ref','source_record'):
            identity(row[k],k)
        if row['kind'] not in KINDS or row['source_ref'] not in self.sources:
            raise ValueError('unregistered historical source or kind')
        numeric(row['sampled_at_s'],'historical sample time')
        p=row['payload']
        if not isinstance(p,dict):raise ValueError('episode payload required')
        canonical(p)
        if row['kind']=='sensor_observation':
            if p.get('kind') not in {'simulated_observation','imagined'} or p.get('source') not in SOURCES:
                raise ValueError('historical sensor origin invalid')
            if type(p.get('value')) is not int or p['value'] not in (0,1):
                raise ValueError('historical binary value required')
            identity(p.get('correlation_id'),'historical acquisition')
            if p.get('topic')!=row['topic'] or abs(p.get('sampled_at_s',-1)-row['sampled_at_s'])>1e-9:
                raise ValueError('historical sensor tags mismatch')
        elif row['kind']=='physical_receipt':
            for k in ('body_valid','body_veto','optional_pause_executed'):
                if type(p.get(k)) is not bool:raise ValueError('physical receipt flags invalid')
            n=p.get('executed_walk_touchdowns')
            if type(n) is not int or n<0:raise ValueError('actual touchdown count required')
            numeric(p.get('fuel_used_J'),'actual paid fuel')
            numeric(p.get('reserve_used_J'),'actual paid reserve')
        elif p.get('status') not in {'expired_without_receipt','cancelled_on_epoch_boundary'}:
            raise ValueError('query status is not an acquisition')

    def record_batch(self, context, epoch, sequence, rows):
        """Commit a whole acquired batch or reject it without changing memory."""
        identity(context,'context');identity(epoch,'epoch')
        if type(sequence) is not int or sequence<0:raise ValueError('memory sequence required')
        if not isinstance(rows,list) or len(rows)>32:raise ValueError('batch capacity exceeded')
        stream=scoped_key(context,epoch)
        request=digest(dict(context=context,epoch=epoch,sequence=sequence,rows=rows))
        key=stream+'|'+str(sequence)
        if key in self.receipts:
            if self.receipts[key]!=request:raise ValueError('batch identity reused with altered data')
            return False
        if sequence<=self.streams.get(stream,-1):raise ValueError('historical batch replay')
        if stream not in self.streams and len(self.streams)>=LIMITS['streams']:
            raise ValueError('context/epoch capacity reached')
        work=deepcopy(self);existing={r['id']:r for r in work.episodes};ids=set()
        for r in rows:
            work._validate_episode(r)
            if r['context']!=context or r['epoch']!=epoch:raise ValueError('cross-context episode insertion')
            if r['id'] in ids or r['id'] in existing:raise ValueError('historical episode replay')
            ids.add(r['id'])
        work.episodes.extend(deepcopy(rows));work.episodes=work.episodes[-LIMITS['episodes']:]
        work.streams[stream]=sequence;work.receipts[key]=request
        work.receipts=dict(list(work.receipts.items())[-LIMITS['receipts']:])
        retained={r['id'] for r in work.episodes}
        work.lessons={k:v for k,v in work.lessons.items() if all(s in retained for s in v['support_ids'])}
        work.revision+=1;work.validate_state()
        self.__dict__=work.__dict__
        return True

    def consolidate(self):
        """Finite deterministic lessons with explicit evidence, scope and limits."""
        work=deepcopy(self);grouped={}
        for row in work.episodes:
            grouped.setdefault((row['context'],row['topic']),[]).append(row)
        lessons={}
        for (context,topic),rows in grouped.items():
            real=[r for r in rows if r['kind']=='sensor_observation' and
                  r['payload']['kind']=='simulated_observation']
            # Variation in reports is not proof that a physical surface changed.
            pair=None
            for a in reversed(real):
                b=next((b for b in reversed(real) if b['payload']['value']!=a['payload']['value']),None)
                if b is not None:pair=(b,a);break
            if pair:
                key='variation:'+digest([context,topic])[:20]
                lessons[key]=dict(id=key,kind='verify_variable_reports',context=context,topic=topic,
                    support_ids=[r['id'] for r in pair],
                    rule='two_latest_independent_fresh_positive_samples_before_optional_action',
                    derived_from='different historical report values, not verified ground truth',
                    current_observation=False,body_dynamics_learned=False)
            for kind,predicate,text in (
                ('paid_motion',lambda p:p['body_valid'] and p['executed_walk_touchdowns']>0,
                 'An actual touchdown was recorded with a valid paid body tick; this is not a forecast.'),
                ('paid_pause',lambda p:p['body_valid'] and p['body_veto'] and not p.get('voluntary_command_delivered',False),
                 'Optional delivery was vetoed while the actual valid body tick paid for support; the receipt does not establish a universal causal rule.')):
                support=[r for r in rows if r['kind']=='physical_receipt' and predicate(r['payload'])]
                if support:
                    key=kind+':'+digest([context,topic])[:20]
                    lessons[key]=dict(id=key,kind=kind,context=context,topic=topic,
                        support_ids=[support[-1]['id']],rule='historical_explanation_only',
                        derived_from=text,current_observation=False,body_dynamics_learned=False)
        work.lessons=dict(list(sorted(lessons.items()))[-LIMITS['lessons']:])
        work.revision+=1;work.validate_state();self.__dict__=work.__dict__
        return deepcopy(self.lessons)

    def recall(self, context, topic, limit=4):
        identity(context,'recall context');identity(topic,'recall topic')
        if type(limit) is not int or not 1<=limit<=LIMITS['recall']:raise ValueError('recall quota exceeded')
        lessons=[deepcopy(v) for v in self.lessons.values() if v['context']==context and v['topic']==topic]
        lessons.sort(key=lambda r:(r['kind']!='verify_variable_reports',r['id']))
        retained={r['id']:r for r in self.episodes}
        return [dict(**l,historical=True,evidence=[deepcopy(retained[s]) for s in l['support_ids']])
                for l in lessons[:limit]]

    def remember_goal(self, context, epoch, goal, source_ref, *, completed_touchdowns=0, target_touchdowns=None):
        EnvironmentBrain.validate_goal(goal);identity(context,'goal context');identity(epoch,'goal epoch')
        if source_ref not in self.sources:raise ValueError('goal source must be registered')
        if type(completed_touchdowns) is not int or completed_touchdowns<0:raise ValueError('goal progress invalid')
        if target_touchdowns is not None and (type(target_touchdowns) is not int or target_touchdowns<=0):
            raise ValueError('target must be a positive actual touchdown count')
        key=scoped_key(context,goal.id)
        row=dict(context=context,origin_epoch=epoch,goal=asdict(goal),source_ref=source_ref,
            completed_touchdowns=completed_touchdowns,target_touchdowns=target_touchdowns,status='active')
        if key in self.goals:
            if self.goals[key]['goal']!=row['goal']:raise ValueError('goal identity changed without revision')
            return key
        if len(self.goals)>=LIMITS['goals']:raise ValueError('durable goal capacity reached')
        self.goals[key]=row;self.revision+=1
        return key

    def update_goal(self, context, goal_id, time_s, actual_touchdowns, body_valid):
        key=scoped_key(context,goal_id)
        if key not in self.goals:raise ValueError('goal not remembered')
        numeric(time_s,'goal clock')
        if type(actual_touchdowns) is not int or actual_touchdowns<0 or type(body_valid) is not bool:
            raise ValueError('realized goal receipt invalid')
        row=deepcopy(self.goals[key])
        if row['status']=='active':
            row['completed_touchdowns']+=actual_touchdowns
            if not body_valid:row['status']='blocked_by_body_failure'
            elif row['target_touchdowns'] is not None and row['completed_touchdowns']>=row['target_touchdowns']:
                row['status']='completed'
            elif time_s>=row['goal']['deadline_s']:row['status']='deadline_reached'
        self.goals[key]=row

    def resume_goal(self, context, goal_id):
        row=self.goals.get(scoped_key(context,goal_id))
        if row is None or row['status']!='active':raise ValueError('no active goal to resume')
        return Goal(**deepcopy(row['goal'])),deepcopy(row)

    def validate_state(self):
        for k,limit in LIMITS.items():
            if k=='recall':continue
            if len(getattr(self,k))>limit:raise ValueError('memory bound exceeded: '+k)
        ids=set()
        for r in self.episodes:
            self._validate_episode(r)
            if r['id'] in ids:raise ValueError('duplicate historical id')
            ids.add(r['id'])
        for l in self.lessons.values():
            if l['current_observation'] is not False or l['body_dynamics_learned'] is not False:
                raise ValueError('history cannot become live sensor data or body model')
            if not l['support_ids'] or any(s not in ids for s in l['support_ids']):
                raise ValueError('lesson has missing evidence')
            for s in l['support_ids']:
                r=next(r for r in self.episodes if r['id']==s)
                if r['context']!=l['context'] or r['topic']!=l['topic']:raise ValueError('lesson scope mismatch')
        for row in self.goals.values():
            EnvironmentBrain.validate_goal(Goal(**row['goal']))
            if row['source_ref'] not in self.sources:raise ValueError('goal provenance missing')
            if row['status'] not in {'active','completed','deadline_reached','blocked_by_body_failure'}:
                raise ValueError('unknown goal status')
        canonical(self.__dict__)

    def checkpoint(self):
        self.validate_state()
        payload=canonical(dict(schema=SCHEMA,source_sha256=source_hash(),state=deepcopy(self.__dict__)))
        return dict(payload=payload,sha256=digest(payload))

    @classmethod
    def restore(cls, checkpoint):
        try:
            p=deepcopy(checkpoint['payload'])
            if p['schema']!=SCHEMA or checkpoint['sha256']!=digest(p) or p['source_sha256']!=source_hash():
                raise ValueError('durable memory integrity/source mismatch')
            obj=cls()
            if set(p['state'])!=set(obj.__dict__):raise ValueError('durable state fields mismatch')
            obj.__dict__.update(p['state']);obj.validate_state();return obj
        except (KeyError,TypeError,AttributeError) as e:raise ValueError('malformed durable memory') from e
