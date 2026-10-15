"""Fixed-budget enriched-input LoRA training; test outcomes follow predictions."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import torch
from peft import PeftModel
from examples.nasuraya_language_adapter import train as old
from examples.nasuraya_language_adapter.data import save,sha
from examples.nasuraya_language_choice.experiment import predict,optimize,choice_batch
from examples.nasuraya_language_transfer.evaluate import confusion
from examples.nasuraya_self_model.evaluate import fixture,request,prepare_defaults
from examples.nasuraya_self_model.monitor import snapshot,SelfModel
from .data import PROTOCOL,sources,cases,initialize,features,enriched_prompt,legacy_prompt,validate_splits,rows_from_receipts
from unified_body_v2 import UnifiedBody


MODELS=('parent_calibrated_legacy','choice_frozen_legacy','choice_frozen_enriched','trained_enriched')


def prepare(output,previous):
    out=Path(output).resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    config=json.loads(PROTOCOL.read_text());save(out/'frozen-protocol.json',config)
    previous=Path(previous).resolve();ancestry=json.loads((previous/'ancestry.json').read_text())
    for local,prior,key in [('parent','parent_calibrated','parent_adapter_sha256'),('choice','choice_balanced','choice_adapter_sha256')]:
        path=previous/'models'/prior
        if sha(path/'adapter_model.safetensors')!=config[key]:raise ValueError('unexpected frozen ancestor')
        shutil.copytree(path,out/'models'/local)
    shutil.copyfile(previous/'base-protocol.json',out/'base-protocol.json')
    save(out/'ancestry.json',dict(parent_effective=ancestry['parent_effective_hashes'],
        choice_effective=ancestry['primary_result']['weights']['choice_balanced']['effective_hashes'],
        prior_transfer_results_sha256=sha(previous/'results.json')))
    prepare_defaults();allcases=cases(config,'train')+cases(config,'held_out')
    pressures={c.get('sleep',config['training_sleep_pressure' if c['split']=='train' else 'held_out_sleep_pressure']) for c in allcases}
    bases={p:fixture(p).checkpoint() for p in pressures};plans=[]
    for i,c in enumerate(allcases):
        pressure=c.get('sleep',config['training_sleep_pressure' if c['split']=='train' else 'held_out_sleep_pressure'])
        b=initialize(bases[pressure],c,config['pain_region']);q=request(b,c['id'],c['duration_s'])
        if 'friction' in c:q['external']['native']=dict(friction=dict(zip(('L','R'),c['friction'])))
        b.validate_input(q['external'],__import__('datetime').datetime.fromisoformat(q['at_utc']),q['duration_s'])
        obs=snapshot(b);f=features(b,q,obs,config['regional_features']);initial=b.checkpoint()
        plans.append(dict(id=c['id'],split=c['split'],family=c['family'],spec=c,initial=initial,
            initial_sha256=initial['sha256'],request=q,features=f,prompt=enriched_prompt(f),legacy_prompt=legacy_prompt(obs,q)))
        if (i+1)%16==0:print(json.dumps(dict(stage='plan',completed=i+1,total=len(allcases))),flush=True)
    validate_splits(plans)
    if any(sum(p['split']==s for p in plans)!=config[k] for s,k in [('train','training_cases'),('held_out','held_out_cases')]):
        raise ValueError('case budget differs')
    save(out/'plans.json',plans)
    save(out/'manifest.json',dict(sources=sources(),protocol_sha256=sha(out/'frozen-protocol.json'),
        plans_sha256=sha(out/'plans.json'),base_protocol_sha256=sha(out/'base-protocol.json'),ancestry_sha256=sha(out/'ancestry.json'),
        models={n:sha(out/'models'/n/'adapter_model.safetensors') for n in ('parent','choice')},labels_generated=False))
    print(json.dumps(dict(stage='prepared',training=config['training_cases'],held_out=config['held_out_cases'])),flush=True)


def inputs(out):
    config=json.loads((out/'frozen-protocol.json').read_text());m=json.loads((out/'manifest.json').read_text())
    if config!=json.loads(PROTOCOL.read_text()) or m['sources']!=sources():raise ValueError('frozen protocol/source mismatch')
    for file,key in [('plans.json','plans_sha256'),('base-protocol.json','base_protocol_sha256'),('ancestry.json','ancestry_sha256'),('frozen-protocol.json','protocol_sha256')]:
        if sha(out/file)!=m[key]:raise ValueError('frozen input changed: '+file)
    for n,h in m['models'].items():
        if sha(out/'models'/n/'adapter_model.safetensors')!=h:raise ValueError('frozen ancestor changed')
    plans=json.loads((out/'plans.json').read_text());validate_splits(plans)
    return config,plans


def load_model(out,base,name,trainable=False):
    model,tok=old.load_base(base,json.loads((out/'base-protocol.json').read_text()))
    directory=out/('adapter' if name=='trained' else 'models/'+name)
    model=PeftModel.from_pretrained(model,directory,local_files_only=True,is_trainable=trainable)
    expected=(json.loads((out/'weights.json').read_text())['effective_after'] if name=='trained' else
              json.loads((out/'ancestry.json').read_text())[name+'_effective'])
    if old.effective_hashes(model)!=expected:raise ValueError('effective model weights differ')
    return model,tok


def label_split(out,config,plans,split):
    ledger=SelfModel.create(out/(split+'-labels.sqlite'))
    selected=[p for p in plans if p['split']==split]
    for i,p in enumerate(selected):
        b=UnifiedBody.restore(p['initial']);q=p['request']
        ledger.begin(b,q);receipt=b.cycle(**q);ledger.finish(p['id'],b,receipt,learn=False)
        print(json.dumps(dict(stage='native_'+split,completed=i+1,total=len(selected))),flush=True)
    rows=rows_from_receipts(out,split,config,plans);save(out/(split+'-rows.json'),rows)
    return rows


def checked_training(rows):
    if not rows or any(r['split']!='train' for r in rows) or len({r['id'] for r in rows})!=len(rows):
        raise ValueError('unique training rows only; no held-out optimizer access')
    return rows


def optimize_checked(model,tok,rows,config):
    checked_training(rows)  # precedes optimizer creation or model access
    return optimize(model,tok,rows,config,'choice_balanced')


def should_promote(metrics,config):
    m=metrics['trained_enriched']['overall'];gate=config['promotion']
    return (m['false_admit']<=gate['max_false_admits'] and m['admit_recall'] is not None and m['defer_recall'] is not None
        and m['admit_recall']>=gate['minimum_admit_recall'] and m['defer_recall']>=gate['minimum_defer_recall']
        and (not gate['require_strict_accuracy_gain_over_parent'] or m['accuracy']>metrics['parent_calibrated_legacy']['overall']['accuracy'])
        and (not gate['require_strict_accuracy_gain_over_frozen_enriched'] or m['accuracy']>metrics['choice_frozen_enriched']['overall']['accuracy']))


def threshold(name,config):return config['parent_threshold'] if name=='parent_calibrated_legacy' else config['primary_threshold']


def measure(predictions,gold,held,config):
    return {name:dict(overall=confusion(values,gold,threshold(name,config)),families={
        family:confusion([r for r in values if r['id'] in {p['id'] for p in held if p['family']==family}],
            [r for r in gold if r['family']==family],threshold(name,config)) for family in sorted({p['family'] for p in held})})
        for name,values in predictions.items()}


def run(output,base):
    out=Path(output).resolve();config,plans=inputs(out)
    with (out/'run-started.json').open('x') as f:json.dump(dict(no_automatic_retry=True),f)
    torch.set_num_threads(config['cpu_threads']);torch.manual_seed(config['seed']);torch.use_deterministic_algorithms(True)
    held=[p for p in plans if p['split']=='held_out'];predictions={};initial_parameters={}
    for local,names in [('parent',['parent_calibrated_legacy']),('choice',['choice_frozen_legacy','choice_frozen_enriched'])]:
        model,tok=load_model(out,base,local);initial_parameters[local]=old.tensors_hash(model.named_parameters())
        # Validate every enriched input against tokenizer limits before native labels.
        for p in plans:choice_batch(tok,[dict(p,label='ADMIT')],config['max_length'])
        for name in names:
            rows=[dict(p,prompt=p['legacy_prompt']) if name.endswith('legacy') else p for p in held]
            predictions[name]=predict(model,tok,rows,config['max_length'])
        if old.tensors_hash(model.named_parameters())!=initial_parameters[local]:raise ValueError('baseline inference changed weights')
        del model
    save(out/'frozen-baselines-before-training.json',dict(predictions=predictions,parameter_hashes=initial_parameters))
    train=label_split(out,config,plans,'train');checked_training(train)
    save(out/'training-data-lock.json',dict(rows_sha256=sha(out/'train-rows.json'),ledger_sha256=sha(out/'train-labels.sqlite'),ids=[r['id'] for r in train]))
    model,tok=load_model(out,base,'choice',True)
    initial={n:p.detach().clone() for n,p in model.named_parameters() if p.requires_grad}
    frozen_before=old.frozen_hash(model);effective_before=old.effective_hashes(model)
    print(json.dumps(dict(stage='optimizer_started',steps=config['steps'],training_rows=len(train),held_out_outcomes=0)),flush=True)
    log=optimize_checked(model,tok,train,config);save(out/'training-log.json',log)
    if old.frozen_hash(model)!=frozen_before:raise ValueError('base parameters changed')
    after={n:p for n,p in model.named_parameters() if p.requires_grad}
    changes=[dict(name=n,elements=p.numel(),changed_elements=int(torch.count_nonzero(p-initial[n])),
        l2_change=float(torch.linalg.vector_norm(p.detach()-initial[n]))) for n,p in after.items()]
    if not sum(c['changed_elements'] for c in changes) or not all(bool(torch.isfinite(p).all()) for p in after.values()):
        raise ValueError('finite actual adapter change required')
    if any(set(step['ids'])-set(r['id'] for r in train) for step in log):raise ValueError('optimizer accessed non-training rows')
    model.save_pretrained(out/'adapter',safe_serialization=True,save_embedding_layers=False)
    effective_after=old.effective_hashes(model)
    weights=dict(adapter_sha256=sha(out/'adapter/adapter_model.safetensors'),frozen_before=frozen_before,frozen_after=old.frozen_hash(model),
        trainable_before=old.tensors_hash(initial.items()),trainable_after=old.tensors_hash(after.items()),
        effective_before=effective_before,effective_after=effective_after,tensor_changes=changes,
        changed_effective_matrices=sum(effective_before[n]!=h for n,h in effective_after.items()),
        optimizer_steps=len(log),trainable_parameters=sum(p.numel() for p in after.values()),
        all_parameters_after=old.tensors_hash(model.named_parameters()))
    save(out/'weights.json',weights)
    predictions['trained_enriched']=predict(model,tok,held,config['max_length'])
    if old.tensors_hash(model.named_parameters())!=weights['all_parameters_after']:raise ValueError('trained inference changed weights')
    del model
    predictions['audit_preflight']=[dict(id=p['id'],admit_probability=float(not p['features']['walking_restrictions'])) for p in held]
    for name,value in [('always_admit',1.),('always_defer',0.)]:predictions[name]=[dict(id=p['id'],admit_probability=value) for p in held]
    for name,values in predictions.items():
        for p in values:p['prediction']='ADMIT' if p['admit_probability']>=threshold(name,config) else 'DEFER'
    inputs(out)
    save(out/'predictions-before-test-outcomes.json',dict(predictions=predictions,weights=weights,
        plans_sha256=sha(out/'plans.json'),train_rows_sha256=sha(out/'train-rows.json'),sources=sources(),held_out_outcomes_generated=0))
    print(json.dumps(dict(stage='test_predictions_committed',held_out_outcomes_generated=0)),flush=True)
    gold=label_split(out,config,plans,'held_out');metrics=measure(predictions,gold,held,config)
    lock=json.loads((out/'training-data-lock.json').read_text())
    if sha(out/'train-rows.json')!=lock['rows_sha256'] or sha(out/'train-labels.sqlite')!=lock['ledger_sha256']:raise ValueError('training evidence changed')
    result=dict(schema=config['schema'],metrics=metrics,training_rows=len(train),held_out_rows=len(gold),weights=weights,
        promotion_eligible=should_promote(metrics,config),automatic_advisor_binding_changed=False,
        predictions_saved_before_test_outcomes=True,held_out_used_for_optimization=False,
        thresholds_tuned=False,prompt_tuned_on_test=False,source_hashes=sources(),native_equations_modified=False,
        identity_modified=False,chatgpt_weights_modified=False,live_api_calls=0,
        files_sha256={n:sha(out/n) for n in ['train-rows.json','held_out-rows.json','train-labels.sqlite','held_out-labels.sqlite',
            'predictions-before-test-outcomes.json','training-log.json','weights.json','training-data-lock.json']})
    save(out/'results.json',result)
    subprocess.run([sys.executable,'-m',__package__+'.experiment','verify','--output',str(out),'--base',str(base)],check=True)
    print(json.dumps(dict(stage='complete',promotion_eligible=result['promotion_eligible'],metrics={n:m['overall'] for n,m in metrics.items()})),flush=True)


def verify(output,base):
    import socket
    calls=[0]
    def forbidden(*a,**k):calls[0]+=1;raise AssertionError('network forbidden')
    socket.socket.connect=forbidden
    out=Path(output);config,plans=inputs(out);r=json.loads((out/'results.json').read_text())
    for name,h in r['files_sha256'].items():
        if sha(out/name)!=h:raise ValueError('saved evidence changed: '+name)
    for split in ('train','held_out'):
        if rows_from_receipts(out,split,config,plans)!=json.loads((out/(split+'-rows.json')).read_text()):raise ValueError('native row restoration mismatch')
    log=json.loads((out/'training-log.json').read_text());train=json.loads((out/'train-rows.json').read_text())
    if len(log)!=config['steps'] or any(set(step['ids'])-set(x['id'] for x in train) for step in log):raise ValueError('optimizer evidence mismatch')
    weights=r['weights']
    if (weights!=json.loads((out/'weights.json').read_text()) or
        sha(out/'adapter/adapter_model.safetensors')!=weights['adapter_sha256'] or weights['frozen_before']!=weights['frozen_after']):
        raise ValueError('saved trained weights differ')
    expected=json.loads((out/'predictions-before-test-outcomes.json').read_text())['predictions'];held=[p for p in plans if p['split']=='held_out']
    metrics=measure(expected,json.loads((out/'held_out-rows.json').read_text()),held,config)
    if metrics!=r['metrics'] or should_promote(metrics,config)!=r['promotion_eligible']:
        raise ValueError('saved metrics or promotion decision differ')
    torch.set_num_threads(config['cpu_threads']);torch.use_deterministic_algorithms(True);errors={}
    for local,names in [('parent',['parent_calibrated_legacy']),('choice',['choice_frozen_legacy','choice_frozen_enriched']),('trained',['trained_enriched'])]:
        model,tok=load_model(out,base,local)
        required=(weights['all_parameters_after'] if local=='trained' else json.loads((out/'frozen-baselines-before-training.json').read_text())['parameter_hashes'][local])
        if old.tensors_hash(model.named_parameters())!=required:raise ValueError('parameter restoration mismatch')
        for name in names:
            current=predict(model,tok,[dict(p,prompt=p['legacy_prompt']) if name.endswith('legacy') else p for p in held],config['max_length'])
            if [p['id'] for p in current]!=[p['id'] for p in expected[name]]:raise ValueError('prediction pairing mismatch')
            error=max(abs(a-b) for x,y in zip(current,expected[name]) for a,b in zip(x['scores'],y['scores']))
            if error>1e-5 or ['ADMIT' if p['admit_probability']>=threshold(name,config) else 'DEFER' for p in current]!=[p['prediction'] for p in expected[name]]:
                raise ValueError('prediction restoration mismatch')
            errors[name]=error
        del model
    save(out/'cold-restoration.json',dict(new_process=True,network_calls=calls[0],max_score_errors=errors,
        parameter_hashes_equal=True,native_receipts_verified=len(plans),new_optimizer_steps=0,new_body_cycles=0,new_learning=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','train','verify'));p.add_argument('--output',required=True)
    p.add_argument('--previous');p.add_argument('--base');a=p.parse_args()
    if a.command=='prepare':prepare(a.output,a.previous)
    elif a.command=='train':run(a.output,a.base)
    else:verify(a.output,a.base)
