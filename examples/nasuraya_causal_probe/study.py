"""Causal probes of existing mechanisms; never a phenomenal-consciousness score."""
from copy import deepcopy
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
NATIVE=ROOT/'runtimes/tadash_body'
sys.path.insert(0,str(NATIVE))
# The existing retained imports set up the original native dependency tree.
import persistent_embodiment_v1
from persistent_embodiment_v1 import atomic_json,digest
from brain_body_loop_v07 import BrainBodyLoop,BrainEnvironment
from cognitive_workspace_v07 import EnvironmentBrain,Goal,Observation
sys.path.insert(0,str(NATIVE/'retained_extensions'))
from neural_circuit import Circuit,toy_circuit

SCHEMA='nasuraya-causal-access-probe/1'
PROTOCOL=Path(__file__).with_name('protocol.json')
REGISTRATION=Path(__file__).with_name('preregistration.json')


def protocol():
    p=json.loads(PROTOCOL.read_text());r=json.loads(REGISTRATION.read_text())
    if r['protocol_sha256']!=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest():
        raise ValueError('preregistered protocol changed')
    return p


def source_hashes():
    modules=[persistent_embodiment_v1,sys.modules[EnvironmentBrain.__module__],
             sys.modules[BrainBodyLoop.__module__],sys.modules[Circuit.__module__]]
    paths=[Path(m.__file__) for m in modules]+[Path(__file__)]
    return {str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}


def image(label,noise,rng,side):
    # Two neutral pixel patterns, no natural-image recognition claim.
    middle={side//2-1,side//2}
    return [[int((c in middle if label==0 else r in middle) != (rng.random()<noise))
             for c in range(side)] for r in range(side)]


def sensor(pixels):
    side=len(pixels)
    if side<4 or any(len(row)!=side or any(type(x) is not int or x not in (0,1) for x in row) for row in pixels):
        raise ValueError('square binary bitmap required')
    mid={side//2-1,side//2}
    vertical=sum(pixels[r][c] for r in range(side) for c in mid)
    horizontal=sum(pixels[r][c] for r in mid for c in range(side))
    return dict(value=int(horizontal>vertical),feature_margin=horizontal-vertical,
                tie=horizontal==vertical,kind='authored_fixed_pixel_feature_extractor')


def workspace_trial(pixels,ident,arm,p):
    """Actor receives pixels and arm only. Ground-truth class stays in scorer."""
    if arm not in p['arms']:raise ValueError('unknown workspace arm')
    sensed=sensor(pixels)
    loop=BrainBodyLoop(brain=EnvironmentBrain())
    initial=loop.checkpoint();rows=[]
    for i,phase in enumerate(p['phases']):
        restored=i>=2
        # Exactly one config assignment in each condition, on a private owner.
        if arm=='broadcast_cut':loop.brain.config['broadcast']=restored
        elif arm=='offpath_control':loop.brain.config['correlation']=restored
        else:loop.brain.config['broadcast']=True
        now=loop.physical.state.time_s
        observations=() if i%2 else (Observation(id=ident+':observation:'+str(i),topic='neutral_pattern',
            value=sensed['value'],source='visual_probe',source_sequence=i,
            sampled_at_s=now,correlation_id=ident+':acquisition:'+str(i)),)
        # Distinct goal IDs force the existing cognition scheduler each tick.
        goal=Goal(id=ident+':goal:'+str(i),topic='neutral_pattern',desired_command='walk',
            action_duration_s=p['action_duration_s'],deadline_s=now+p['decision_deadline_horizon_s'],
            query_latency_s=p['query_latency_s'])
        event=BrainEnvironment(event_id=ident+':'+str(i),event_sequence=i,goal=goal,observations=observations)
        before=loop.checkpoint()
        f=loop.step(event);c=f['cognition']['current'];receipt=f['cognition']['execution_receipt']
        if c is None:raise AssertionError('missing native cognitive tick')
        rows.append(dict(phase=phase,before_sha256=before['sha256'],cognition=c,
            receipt=receipt,after_sha256=loop.checkpoint()['sha256']))
    if loop.body_steps!=p['body_ticks_per_arm'] or loop.brain.total_ticks!=len(p['phases']):
        raise AssertionError('fixed tick budget changed')
    return dict(sensor=sensed,initial_sha256=initial['sha256'],rows=rows,final=loop.checkpoint(),
                simulated_seconds=loop.physical.state.time_s,source_hashes=source_hashes())


def change_edge(circuit,name,weight):
    """Change only a private fixture's edge; keep pending events/conductance."""
    if name not in circuit.synapses:raise ValueError('unknown intervention edge')
    circuit.synapses[name]=replace(circuit.synapses[name],weight_ns=weight)
    circuit.connections[name]['weight_ns']=weight
    Circuit.restore(circuit.payload())


def circuit_trial(case,arm,p,*,perturb=False):
    if arm not in p['arms']:raise ValueError('unknown circuit arm')
    circuit=toy_circuit(plastic=False,learned_weight_ns=p['learned_forward_weight_ns'],dt_ms=p['dt_ms'])
    original=circuit.payload();edge=None;old=None
    if arm!='intact':
        edge=p['recurrent_edge'] if arm=='recurrent_cut' else p['control_edge'] if arm=='offpath_control' else p['feedforward_edge']
        old=circuit.synapses[edge].weight_ns
        change_edge(circuit,edge,old-p['control_weight_decrement_ns'] if arm=='offpath_control' else 0.)
    rows=[];restored=False
    for i in range(round(p['duration_ms']/p['dt_ms'])):
        t=i*p['dt_ms']
        if edge and not restored and t>=p['restore_ms']:
            change_edge(circuit,edge,old);restored=True
        current=0.
        for onset in (p['first_pulse_start_ms'],p['second_pulse_start_ms']):
            if onset<=t<onset+case['duration_ms']:current=case['current_pa']
        currents={'seat_input':current}
        if perturb and p['perturbation_ms']<=t<p['perturbation_ms']+p['perturbation_duration_ms']:
            currents[p['perturbed_cell']]=p['perturbation_pa']
        row=circuit.step(currents)
        rows.append(dict(time_ms=row['time_ms'],spikes=row['spikes'],voltages_mv=row['voltages_mv']))
    assert len(rows)==round(p['duration_ms']/p['dt_ms'])
    assert {k:v['weight_ns'] for k,v in circuit.connections.items()}=={k:v['weight_ns'] for k,v in original['connections'].items()}
    return dict(initial_sha256=digest(original),rows=rows,final=circuit.payload(),
        update_counts=dict(neuron_updates=len(rows)*len(circuit.cells),synapse_updates=len(rows)*len(circuit.synapses)),
        intervention=dict(edge=edge,original_weight_ns=old,restore_ms=p['restore_ms']),plasticity=False)


def spike_counts(rows,start,end):
    counts={k:0 for k in ('seat_input','arm_input','attention','association','regulation','brake')}
    for row in rows:
        if start<row['time_ms']<=end:
            for k in row['spikes']:counts[k]+=1
    return counts


def circuit_metrics(control,perturbed,p):
    eps=p['voltage_difference_epsilon_mv'];changed=set();l1=0.
    for a,b in zip(control['rows'],perturbed['rows']):
        if p['perturbation_ms']<a['time_ms']<=p['restore_ms']:
            for cell,v in a['voltages_mv'].items():
                difference=abs(v-b['voltages_mv'][cell]);l1+=difference
                if difference>eps:changed.add(cell)
    return dict(first_spikes=spike_counts(control['rows'],0,p['restore_ms']),
        recovery_spikes=spike_counts(control['rows'],p['second_pulse_start_ms'],p['duration_ms']),
        perturbation_changed_cells=sorted(changed),perturbation_voltage_l1_mv=l1,
        update_counts=control['update_counts'])


def paired_interval(values,rng,resamples):
    if not values:return dict(mean=None,interval=None)
    draws=sorted(sum(rng.choice(values) for _ in values)/len(values) for _ in range(resamples))
    return dict(mean=sum(values)/len(values),interval=[draws[int(.025*resamples)],draws[int(.975*resamples)]],
                method='paired case bootstrap; conditional on these designed fixtures')


def summaries(workspace,circuits,p):
    wm={};cm={}
    for arm in p['workspace']['arms']:
        rows=[x for x in workspace if x['arm']==arm];n=len(rows)
        wm[arm]=dict(n=n,sensor_accuracy=sum(x['sensor_correct'] for x in rows)/n,
            delayed_planner_accuracy=sum(x['delayed_correct'] for x in rows)/n,
            delayed_brier=sum(x['delayed_brier'] for x in rows)/n,
            restored_planner_accuracy=sum(x['restored_correct'] for x in rows)/n,
            invalid_physical_receipts=sum(x['invalid_physical_receipts'] for x in rows),
            work_units=sorted({tuple(x['work_units']) for x in rows}))
    for arm in p['circuit']['arms']:
        rows=[x for x in circuits if x['arm']==arm];base={x['id']:x for x in circuits if x['arm']=='intact'}
        target=['attention','association','regulation','brake']
        cm[arm]=dict(n=len(rows),
            cases_changed_downstream_spike_counts=sum(any(x['first_spikes'][k]!=base[x['id']]['first_spikes'][k] for k in target) for x in rows),
            cases_changed_input_spike_counts=sum(x['first_spikes']['seat_input']!=base[x['id']]['first_spikes']['seat_input'] for x in rows),
            cases_recovery_counts_differ=sum(x['recovery_spikes']!=base[x['id']]['recovery_spikes'] for x in rows),
            mean_perturbation_affected_cells=sum(len(x['perturbation_changed_cells']) for x in rows)/len(rows),
            update_counts_equal_to_intact=all(x['update_counts']==base[x['id']]['update_counts'] for x in rows))
    base={x['id']:x for x in workspace if x['arm']=='intact'};rng=random.Random(p['analysis']['bootstrap_seed'])
    effects={a:paired_interval([int(x['delayed_correct'])-int(base[x['id']]['delayed_correct']) for x in workspace if x['arm']==a],rng,p['analysis']['bootstrap_resamples']) for a in p['workspace']['arms'] if a!='intact'}
    return dict(workspace=wm,circuit=cm,workspace_paired_effects=effects)


def record_start(db,kind,ident,arm,plan):
    with db:db.execute('INSERT INTO trials VALUES(?,?,?,?,NULL,NULL)',(kind,ident,arm,json.dumps(plan,sort_keys=True)))


def record_finish(db,kind,ident,arm,result,path):
    encoded=json.dumps(result,sort_keys=True,allow_nan=False).encode()
    with gzip.open(path,'wb') as f:f.write(encoded)
    h=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    with db:db.execute('UPDATE trials SET result_path=?,result_sha256=? WHERE kind=? AND id=? AND arm=?',(Path(path).name,h,kind,ident,arm))


def evaluate(output):
    p=protocol();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/'frozen-protocol.json',p);atomic_json(out/'source-audit.json',source_hashes())
    ws=[];cs=[];cases=[]
    # Plans are all generated and saved before the first native outcome.
    for seed in p['seeds']:
        rng=random.Random(seed)
        for noise in p['workspace']['noise_probabilities']:
            for label in p['workspace']['classes']:
                ident='w-'+hashlib.sha256(f'fixture:{seed}:{noise}:{label}'.encode()).hexdigest()[:20]
                cases.append(dict(id=ident,label=label,noise=noise,seed=seed,pixels=image(label,noise,rng,p['workspace']['image_side'])))
    atomic_json(out/'frozen-cases.json',cases)
    circuit_cases=[]
    for seed in p['seeds']:
        for current in p['circuit']['currents_pa']:
            for duration in p['circuit']['pulse_duration_ms']:
                circuit_cases.append(dict(id=f'n{seed}-{current}-{duration}',seed=seed,current_pa=current,duration_ms=duration))
    # Seeds are identifiers here: circuit inputs are identical across seeds.
    atomic_json(out/'frozen-circuit-cases.json',circuit_cases)
    db=sqlite3.connect(out/'ledger.sqlite');db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE trials(kind TEXT,id TEXT,arm TEXT,plan TEXT,result_path TEXT,result_sha256 TEXT,PRIMARY KEY(kind,id,arm))')
    for case in cases:
        for arm in p['workspace']['arms']:
            record_start(db,'workspace',case['id'],arm,dict(pixels=case['pixels'],arm=arm,source_hashes=source_hashes()))
            result=workspace_trial(case['pixels'],case['id'],arm,p['workspace'])
            record_finish(db,'workspace',case['id'],arm,result,out/(case['id']+'-'+arm+'.json.gz'))
            phases=result['rows'];delayed=phases[1]['cognition'];recovered=phases[3]['cognition']
            expected='act' if case['label'] else 'abstain'
            ws.append(dict(id=case['id'],arm=arm,seed=case['seed'],noise=case['noise'],label=case['label'],
                sensor_correct=result['sensor']['value']==case['label'],
                delayed_correct=delayed['plan']['kind']==expected,
                delayed_plan=delayed['plan']['kind'],delayed_probability=delayed['plan']['environment_probability_safe'],
                delayed_brier=(delayed['plan']['environment_probability_safe']-case['label'])**2,
                restored_correct=recovered['plan']['kind']==expected,
                invalid_physical_receipts=sum(not r['receipt']['body_valid'] for r in phases),
                work_units=[r['cognition']['work_units'] for r in phases],
                final_sha256=result['final']['sha256']))
    for case in circuit_cases:
        for arm in p['circuit']['arms']:
            record_start(db,'circuit',case['id'],arm,dict(case=case,arm=arm,paired_perturbations=[False,True],source_hashes=source_hashes()))
            baseline=circuit_trial(case,arm,p['circuit']);perturbed=circuit_trial(case,arm,p['circuit'],perturb=True)
            result=dict(baseline=baseline,perturbed=perturbed)
            record_finish(db,'circuit',case['id'],arm,result,out/(case['id']+'-'+arm+'.json.gz'))
            cs.append(dict(id=case['id'],arm=arm,seed=case['seed'],**circuit_metrics(baseline,perturbed,p['circuit'])))
    assert db.execute('SELECT count(*) FROM trials WHERE result_path IS NULL').fetchone()[0]==0
    db.close()
    result=dict(schema=SCHEMA,workspace_rows=ws,circuit_rows=cs,summary=summaries(ws,cs,p),
        workspace_trials=len(ws),native_body_ticks=len(ws)*p['workspace']['body_ticks_per_arm'],
        circuit_pair_trials=len(cs),circuit_integrations=len(cs)*2,
        unique_circuit_input_pairs=len(p['circuit']['currents_pa'])*len(p['circuit']['pulse_duration_ms']),
        circuit_seed_replicates_are_identical=True,phenomenal_consciousness_test_validated=False,
        language_model_internal_intervention=False,model_api_calls=0,
        limitations=p['limitations'],protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest())
    atomic_json(out/'results.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('workspace_rows','circuit_rows')},indent=2))
