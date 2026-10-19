"""Versioned six-hour admission; conservative rolling reservations, no refunds."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import re

SCHEMA = 'nasuraya-cadence-ledger/2'
DAY = timedelta(hours=24)
INTERVAL = timedelta(hours=6)
CAPS = dict(seconds=1200, files=6, lines=300)
SLOT = dict(seconds=300, files=1, lines=75)


def fingerprint(ledger):
    return hashlib.sha256(json.dumps(ledger,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def entry(at, run_id, kind, budget):
    return dict(at=at,run_id=run_id,kind=kind,**budget)


def migrate(gate, state, now):
    """Explicit deployment operation only. Missing runtime ledger never migrates."""
    gate.validate(state,now)
    if state['inflight_run_id'] is not None: raise ValueError('host reconciliation required')
    if 'cadence_sha256' in state: raise ValueError('existing cadence must not be reinitialized')
    at = state['last_claimed_at']
    rows = [] if at is None else [entry(at,'legacy-migration','legacy',CAPS)]
    ledger=dict(schema=SCHEMA,observed_claim_at=at,entries=rows)
    control=deepcopy(state);control['cadence_sha256']=fingerprint(ledger)
    return control,ledger


def synchronize(gate, state, ledger, now):
    current, _, claimed = gate.validate(state,now)
    if not isinstance(ledger,dict) or set(ledger) != {'schema','observed_claim_at','entries'}:
        raise ValueError('existing cadence ledger required')
    if state.get('cadence_sha256') != fingerprint(ledger): raise ValueError('ledger/control hash mismatch')
    if ledger['schema'] != SCHEMA or not isinstance(ledger['entries'],list) or len(ledger['entries'])>128:
        raise ValueError('cadence ledger schema/capacity')
    previous = gate.timestamp(ledger['observed_claim_at']) if ledger['observed_claim_at'] else None
    ids = set(); times = []
    for row in ledger['entries']:
        if not isinstance(row,dict) or set(row) != {'at','run_id','kind',*CAPS}:
            raise ValueError('reservation schema')
        if not isinstance(row['run_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',row['run_id']):
            raise ValueError('reservation identity')
        if row['run_id'] in ids: raise ValueError('duplicate reservation')
        ids.add(row['run_id']); at = gate.timestamp(row['at']); times.append(at)
        if at>current or (previous is not None and at>previous): raise ValueError('reservation clock')
        if row['kind'] not in ('legacy','slot'): raise ValueError('reservation kind')
        maximum = CAPS if row['kind']=='legacy' else SLOT
        for key in CAPS:
            if type(row[key]) is not int or not 0<=row[key]<=maximum[key]: raise ValueError('reservation budget')
        if row['seconds'] != maximum['seconds'] or (row['kind']=='legacy' and any(row[k]!=CAPS[k] for k in CAPS)):
            raise ValueError('reservation cannot refund time')
    if times != sorted(times): raise ValueError('reservation order')
    if previous is not None and (claimed is None or claimed<previous): raise ValueError('control/ledger regression')
    if previous is None and times: raise ValueError('missing observed claim')
    result = deepcopy(ledger)
    if claimed is not None and (previous is None or claimed>previous):
        # Any old/unknown writer consumes the FULL legacy allowance, never 5 min.
        result['entries'].append(entry(state['last_claimed_at'],'legacy-'+claimed.strftime('%Y%m%d%H%M%S%f'),'legacy',CAPS))
        result['observed_claim_at'] = state['last_claimed_at']
    result['entries'] = [r for r in result['entries'] if current-gate.timestamp(r['at'])<DAY]
    # A recent observed claim may not silently disappear from a supplied ledger.
    if claimed is not None and current-claimed<DAY and not any(gate.timestamp(r['at'])==claimed for r in result['entries']):
        raise ValueError('missing recent reservation')
    return result


def evaluate(gate, state, ledger, now):
    try:
        updated = synchronize(gate,state,ledger,now)
        current,contact,claimed = gate.validate(state,now)
    except (ValueError,TypeError,KeyError): return dict(eligible=False,reason='invalid_cadence_state')
    if not state['enabled']: return dict(eligible=False,reason='paused')
    if state['inflight_run_id'] is not None: return dict(eligible=False,reason='unresolved_previous_run')
    if current-contact<DAY: return dict(eligible=False,reason='recent_contact')
    if claimed is not None and current-claimed<INTERVAL: return dict(eligible=False,reason='interval_not_elapsed')
    remaining = {k:CAPS[k]-sum(r[k] for r in updated['entries']) for k in CAPS}
    if remaining['seconds']<SLOT['seconds']: return dict(eligible=False,reason='rolling_budget_used')
    if any(v<0 for v in remaining.values()): return dict(eligible=False,reason='invalid_cadence_state')
    return dict(eligible=True,reason='six_hour_slot_available',remaining=remaining)


def claim(gate, state, ledger, now, run_id, *, source_work=False):
    decision = evaluate(gate,state,ledger,now)
    if not decision['eligible']: raise ValueError(decision['reason'])
    updated = synchronize(gate,state,ledger,now)
    if not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id): raise ValueError('run id')
    if run_id==state['last_completed_run_id'] or any(r['run_id']==run_id for r in updated['entries']):
        raise ValueError('reused run id')
    budget = dict(seconds=300,files=1 if source_work else 0,lines=75 if source_work else 0)
    if any(budget[k]>decision['remaining'][k] for k in CAPS): raise ValueError('source budget used')
    at = gate.timestamp(now).isoformat()
    updated['observed_claim_at']=at; updated['entries'].append(entry(at,run_id,'slot',budget))
    control=deepcopy(state);control.update(last_claimed_at=at,inflight_run_id=run_id,cadence_sha256=fingerprint(updated))
    return control,updated,budget
