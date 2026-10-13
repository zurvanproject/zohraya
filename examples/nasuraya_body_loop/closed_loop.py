"""Offline frozen-policy evaluation harness, not a new production actuator.

Uses existing native external-input contracts only for precommitted fixtures.
The mutable adaptive runtime and its learning/safety constants are unchanged.
"""
from copy import deepcopy
import json
import math
import re

from .adaptive_memory import state, forecast, errors, choose_action, validate_model
from .host import executed_body
from .self_maintenance import IdentityContinuity, MaintenanceBlocked, canonical, digest, plan

SCHEMA = 'nasuraya-frozen-closed-loop/1'


def validate_perturbation(external):
    if not isinstance(external,dict) or set(external)-{'native'}:
        raise ValueError('only precommitted synthetic native perturbations')
    native = external.get('native',{})
    if not isinstance(native,dict) or set(native)-{'pain','unexpected_impulse_N_s','friction'}:
        raise ValueError('unsupported test perturbation')
    # Native validation supplies the numeric and descriptor contracts.
    from unified_body_v2 import PersistentEmbodiment
    PersistentEmbodiment.validate_external(native,'2026-01-01T00:00:00+00:00')
    canonical(external)
    return deepcopy(external)


class FrozenClosedLoop:
    """Three-step test-only controller with immutable model and durable intents."""
    def __init__(self,loop,*,model=None,sources=None,scenario=None):
        self.loop,self.db=loop,loop.engine.db
        self.identity=IdentityContinuity(self.db)
        self.db.execute('''CREATE TABLE IF NOT EXISTS nasu_frozen_contract (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), record TEXT NOT NULL, hash TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS nasu_frozen_steps (
            ordinal INTEGER PRIMARY KEY, intent TEXT NOT NULL, hash TEXT NOT NULL,
            result TEXT, result_hash TEXT)''')
        row=self.db.execute('SELECT record,hash FROM nasu_frozen_contract WHERE singleton=1').fetchone()
        if row:
            self.contract=json.loads(row[0])
            if digest(self.contract)!=row[1]: raise MaintenanceBlocked('corrupt frozen contract')
            if model is not None and (model!=self.contract['model'] or sources!=self.contract['sources'] or scenario!=self.contract['scenario']):
                raise MaintenanceBlocked('conflicting frozen contract')
        else:
            if model is None or not isinstance(sources,list) or not sources or scenario is None:
                raise MaintenanceBlocked('explicit verified training sources and scenario required')
            if loop.status()['actions_reserved']!=0 or loop.config['max_actions']!=3 or loop.config['mode']!='bounded':
                raise MaintenanceBlocked('fresh three-action fixture session required')
            if not re.fullmatch(r'[a-z-]{1,45}',scenario.get('id','')):
                raise ValueError('bounded scenario id required')
            perturbations=scenario.get('perturbations',{})
            if not isinstance(perturbations,dict) or set(perturbations)-{'1','2','3'}:
                raise ValueError('bounded precommitted perturbation schedule required')
            for value in perturbations.values(): validate_perturbation(value)
            self.contract={'schema':SCHEMA,'model':validate_model(deepcopy(model)),'sources':deepcopy(sources),
                           'scenario':deepcopy(scenario),'cycles':3,'duration_s':.1,
                           'initial_sha':loop.observe()['checkpoint_sha256']}
            self.db.execute('INSERT INTO nasu_frozen_contract VALUES (1,?,?)',(canonical(self.contract),digest(self.contract)))
        self.verify()

    def verify(self):
        self.identity.verify()
        row=self.db.execute('SELECT record,hash FROM nasu_frozen_contract WHERE singleton=1').fetchone()
        if row is None or json.loads(row[0])!=self.contract or digest(self.contract)!=row[1]:
            raise MaintenanceBlocked('frozen contract missing or changed')
        if self.contract['schema']!=SCHEMA or self.contract['cycles']!=3 or self.contract['duration_s']!=.1:
            raise MaintenanceBlocked('frozen scope changed')
        validate_model(self.contract['model'])
        prior=self.contract['initial_sha']
        expected=1
        for ordinal,raw,h,result,rh in self.db.execute('SELECT * FROM nasu_frozen_steps ORDER BY ordinal'):
            intent=json.loads(raw)
            if ordinal!=expected or ordinal>3 or digest(intent)!=h or intent['ordinal']!=ordinal or intent['before']['checkpoint_sha256']!=prior:
                raise MaintenanceBlocked('corrupt or discontinuous frozen intent')
            before=intent['before'];state(before)
            preferred=choose_action(self.contract['model'],before,1)
            if intent['action']!=preferred or intent['prediction']!=forecast(self.contract['model'],before,preferred,1):
                raise MaintenanceBlocked('prediction/decision conflicts with frozen model')
            if intent['external']!=self.contract['scenario']['perturbations'].get(str(ordinal),{}):
                raise MaintenanceBlocked('perturbation changed')
            if result is None:
                if ordinal!=self.db.execute('SELECT MAX(ordinal) FROM nasu_frozen_steps').fetchone()[0]:
                    raise MaintenanceBlocked('pending effect before later intent')
            else:
                saved=json.loads(result)
                receipt=self._receipt(intent)
                if digest(saved)!=rh or saved!=self._result(intent,receipt):
                    raise MaintenanceBlocked('recorded result conflicts with native receipt')
                prior=receipt['self_model_after']['checkpoint_sha256']
            expected+=1
        return expected-1

    def _receipt(self,intent):
        record=self.loop.engine.get(intent['id'])
        if record is None or not executed_body(record):
            raise MaintenanceBlocked('unknown frozen outcome; never replay automatically')
        request=record['request']
        evidence=next((e for e in request['evidence'] if e['id']=='body'),None)
        pref=max(request['actions'],key=lambda c:c['score']['respect'])['id']
        if (evidence is None or evidence['source_sha256']!=intent['before']['checkpoint_sha256'] or pref!=intent['action'] or
                request['execution']['external']!=intent['external'] or request['execution']['duration_s']!=.1):
            raise MaintenanceBlocked('native frozen provenance mismatch')
        receipt=self.loop.receipt(record,replayed=False)
        a=receipt['body_audit']
        if (not a or not a.get('same_owner_ticks') or any(
                type(a.get(k)) not in (float,int) or not math.isfinite(a[k]) or abs(a[k])>limit
                for k,limit in [('energy_error_J',1e-6),('water_error_L',1e-9),('light_error_J',1e-6)])):
            raise MaintenanceBlocked('native audit failed')
        state(receipt['self_model_after'])
        return receipt

    def _result(self,intent,receipt):
        native=self.loop.engine.get(intent['id'])['actual_outcome']['body_receipt']['owner']
        return {'receipt':receipt,'error':errors(intent['prediction'],receipt['self_model_after']),
                'contract_action':plan(intent['before'])['requested_action'],
                'correct_preference':intent['action']==plan(intent['before'])['requested_action'],
                'chosen_action':intent['action'],'before':intent['before'],'prediction':intent['prediction'],
                'external':intent['external'],'unseen':intent['prediction']['uncertainty']['unseen_context'],
                'physical_model_valid':native['physical_model_valid'],
                'envelope_exceeded':any(errors(intent['prediction'],receipt['self_model_after'])['absolute'][f]>
                                        intent['prediction']['uncertainty']['bounds'][f]
                                        for f in intent['prediction']['next_state'])}

    def _finish(self,ordinal):
        row=self.db.execute('SELECT intent,result FROM nasu_frozen_steps WHERE ordinal=?',(ordinal,)).fetchone()
        intent=json.loads(row[0])
        if row[1]: return json.loads(row[1])
        receipt=self._receipt(intent)
        result=self._result(intent,receipt)
        self.identity.verify()
        self.db.execute('UPDATE nasu_frozen_steps SET result=?,result_hash=? WHERE ordinal=? AND result IS NULL',
                        (canonical(result),digest(result),ordinal))
        return result

    def advance(self,*,fault=None):
        self.verify()
        pending=self.db.execute('SELECT ordinal FROM nasu_frozen_steps WHERE result IS NULL').fetchall()
        for ordinal, in pending: self._finish(ordinal)
        n=self.verify()
        if any(not row['physical_model_valid'] for row in self.history()):
            return {'status':'blocked_physical_model','history':self.history()}
        if n==3: return {'status':'completed','history':self.history()}
        status=self.loop.status()
        if status['unresolved_running'] or status['actions_remaining']<=0 or status['mode']!='bounded':
            raise MaintenanceBlocked('native budget/authorization/pending blocks evaluation')
        before=self.loop.observe()
        last=self.history()
        prior=last[-1]['receipt']['self_model_after']['checkpoint_sha256'] if last else self.contract['initial_sha']
        if before['checkpoint_sha256']!=prior: raise MaintenanceBlocked('uncontracted body change')
        ordinal=n+1
        action=choose_action(self.contract['model'],before,1)
        external=validate_perturbation(self.contract['scenario']['perturbations'].get(str(ordinal),{}))
        intent={'id':'closed-'+self.contract['scenario']['id']+'-'+str(ordinal),'ordinal':ordinal,
                'before':before,'action':action,'external':external,
                'prediction':forecast(self.contract['model'],before,action,1)}
        if self.loop.engine.get(intent['id']) is not None: raise MaintenanceBlocked('native id conflict')
        self.db.execute('INSERT INTO nasu_frozen_steps VALUES (?,?,?,NULL,NULL)',(ordinal,canonical(intent),digest(intent)))
        if fault: fault('after_intent')
        request=self.loop.make_request(intent['id'],before,.1,action)
        # Only this evaluation harness exercises the existing external fixture contract.
        self.db.execute('DELETE FROM meta WHERE key=?',('body-loop-observation',))
        record=self.loop.adapter.cycle(request,at_utc=request['at_utc'],duration_s=.1,external=external)
        if fault: fault('after_native_commit')
        self._finish(ordinal)
        self.verify()
        history=self.history()
        return {'status':'blocked_physical_model' if not history[-1]['physical_model_valid'] else
                'completed' if ordinal==3 else 'incomplete','history':history}

    def history(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT result FROM nasu_frozen_steps WHERE result IS NOT NULL ORDER BY ordinal')]
