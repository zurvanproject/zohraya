"""Offline audit and optional full deterministic replay of the frozen experiment."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from .study import (protocol,source_hashes,summaries,sensor,circuit_metrics,
                    BrainBodyLoop,Circuit,digest)


def read_raw(root,name,sha):
    path=root/name
    if Path(name).name!=name or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
        raise ValueError('retained result checksum/path mismatch')
    return json.loads(gzip.decompress(path.read_bytes()))


def verify(directory):
    root=Path(directory);p=protocol();results=json.loads((root/'results.json').read_text())
    if json.loads((root/'frozen-protocol.json').read_text())!=p:
        raise ValueError('protocol mismatch')
    if json.loads((root/'source-audit.json').read_text())!=source_hashes():
        raise ValueError('source mismatch')
    cases={x['id']:x for x in json.loads((root/'frozen-cases.json').read_text())}
    circuit_cases={x['id']:x for x in json.loads((root/'frozen-circuit-cases.json').read_text())}
    workspace=[];circuits=[];owner_heads={};updates={}
    db=sqlite3.connect((root/'ledger.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    stored=list(db.execute('SELECT * FROM trials ORDER BY kind,id,arm'));db.close()
    if len(stored)!=results['workspace_trials']+results['circuit_pair_trials']:
        raise ValueError('trial count mismatch')
    with patch.object(BrainBodyLoop,'step',side_effect=AssertionError('offline verification cannot step body')),\
         patch.object(Circuit,'step',side_effect=AssertionError('offline verification cannot step neurons')):
        for kind,ident,arm,raw_plan,name,sha in stored:
            if name is None:raise ValueError('unresolved trial outcome')
            plan=json.loads(raw_plan);r=read_raw(root,name,sha)
            if plan['arm']!=arm or plan['source_hashes']!=source_hashes():raise ValueError('intent mismatch')
            if kind=='workspace':
                case=cases[ident]
                if plan['pixels']!=case['pixels'] or 'label' in plan:
                    raise ValueError('actor input mismatch/label leakage')
                if r['sensor']!=sensor(case['pixels']):raise ValueError('sensor differs from pixels')
                loop=BrainBodyLoop.restore(r['final'])
                if loop.checkpoint()!=r['final'] or loop.body_steps!=4:raise ValueError('owner restore mismatch')
                owner_heads.setdefault(ident,set()).add(r['initial_sha256'])
                for i,row in enumerate(r['rows']):
                    cached=loop.cache[ident+':'+str(i)]['result']['cognition']
                    if row['cognition']!=cached['current'] or row['receipt']!=cached['execution_receipt']:
                        raise ValueError('native cached receipt mismatch')
                    if row['receipt']['body_tick']!=i+1:raise ValueError('body tick mismatch')
                delay=r['rows'][1]['cognition'];recover=r['rows'][3]['cognition']
                expected='act' if case['label'] else 'abstain'
                workspace.append(dict(id=ident,arm=arm,seed=case['seed'],noise=case['noise'],label=case['label'],
                    sensor_correct=r['sensor']['value']==case['label'],
                    delayed_correct=delay['plan']['kind']==expected,delayed_plan=delay['plan']['kind'],
                    delayed_probability=delay['plan']['environment_probability_safe'],
                    delayed_brier=(delay['plan']['environment_probability_safe']-case['label'])**2,
                    restored_correct=recover['plan']['kind']==expected,
                    invalid_physical_receipts=sum(not x['receipt']['body_valid'] for x in r['rows']),
                    work_units=[x['cognition']['work_units'] for x in r['rows']],final_sha256=r['final']['sha256']))
            elif kind=='circuit':
                if plan['case']!=circuit_cases[ident]:raise ValueError('circuit plan mismatch')
                for branch in ('baseline','perturbed'):
                    c=r[branch];restored=Circuit.restore(c['final'])
                    if restored.payload()!=c['final'] or restored.tick!=640:raise ValueError('circuit restore/clock')
                    for cell in restored.cells:
                        count=sum(cell in row['spikes'] for row in c['rows'])
                        if count!=restored.neurons[cell]['spike_count']:raise ValueError('spike trace mismatch')
                    if c['rows'][-1]['voltages_mv']!={k:s['voltage_mv'] for k,s in restored.neurons.items()}:
                        raise ValueError('terminal voltage mismatch')
                    if any(s.plastic for s in restored.synapses.values()):raise ValueError('unexpected learning')
                updates.setdefault(ident,set()).add(json.dumps(r['baseline']['update_counts'],sort_keys=True))
                circuits.append(dict(id=ident,arm=arm,seed=circuit_cases[ident]['seed'],
                                     **circuit_metrics(r['baseline'],r['perturbed'],p['circuit'])))
            else:raise ValueError('unknown retained trial kind')
    key=lambda x:(x['id'],x['arm'])
    if sorted(workspace,key=key)!=sorted(results['workspace_rows'],key=key):raise ValueError('workspace score mismatch')
    if sorted(circuits,key=key)!=sorted(results['circuit_rows'],key=key):raise ValueError('circuit score mismatch')
    if digest(summaries(workspace,circuits,p))!=digest(results['summary']):raise ValueError('summary mismatch')
    if not all(len(x)==1 for x in owner_heads.values()) or not all(len(x)==1 for x in updates.values()):
        raise ValueError('paired start/update budgets differ')
    return dict(verified_workspace_trials=len(workspace),verified_circuit_pairs=len(circuits),
        metrics_equal=True,paired_initial_owner_hashes_equal=True,circuit_update_counts_equal=True,
        body_steps_executed=0,neural_steps_executed=0,network_calls=0)


def compare(first,second):
    first,second=Path(first),Path(second)
    if json.loads((first/'results.json').read_text())!=json.loads((second/'results.json').read_text()):
        raise ValueError('fresh process results differ')
    a=sqlite3.connect(first/'ledger.sqlite');b=sqlite3.connect(second/'ledger.sqlite')
    query='SELECT kind,id,arm,result_path FROM trials ORDER BY kind,id,arm'
    aa=a.execute(query).fetchall();bb=b.execute(query).fetchall();a.close();b.close()
    if aa!=bb:raise ValueError('replica trial identities differ')
    for row in aa:
        name=row[-1]
        if gzip.decompress((first/name).read_bytes())!=gzip.decompress((second/name).read_bytes()):
            raise ValueError('fresh process raw trace/checkpoint differs')
    return dict(equal_result_sets=True,equal_raw_trial_payloads=len(aa),
                note='deterministic repeat on the same designed fixtures; not independent scientific replication')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--compare')
    a=p.parse_args();r=compare(a.directory,a.compare) if a.compare else verify(a.directory)
    print(json.dumps(r,indent=2))
