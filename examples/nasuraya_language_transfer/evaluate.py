"""Record both frozen model predictions before any target native walk outcome."""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import torch
from peft import PeftModel

from examples.nasuraya_language_adapter import train as old
from examples.nasuraya_language_adapter.data import prompt,sha,save,read_episodes,row_from_episode
from examples.nasuraya_language_choice.experiment import predict
from examples.nasuraya_language_choice.advisor import bundle
from examples.nasuraya_self_model.evaluate import fixture,request,prepare_defaults
from examples.nasuraya_self_model.monitor import SelfModel,snapshot,digest
from unified_body_v2 import UnifiedBody

PROTOCOL=Path(__file__).with_name('protocol.json')
LABELS=('ADMIT','DEFER')


def sources():
    root=PROTOCOL.parents[2]
    files=list(PROTOCOL.parent.glob('*.py'))
    files += list((root/'examples/nasuraya_language_adapter').glob('*.py'))
    files += [root/'examples/nasuraya_language_choice'/n for n in ('experiment.py','advisor.py')]
    files += [root/'examples/nasuraya_self_model'/n for n in ('monitor.py','evaluate.py')]
    return {str(p.relative_to(root)):sha(p) for p in files}


def case_specs(config):
    cases=[dict(family='control',name='ordinary'),dict(family='control',name='zero_friction',friction=[0.,0.]),
           dict(family='control',name='sleep',sleep_pressure=config['control_sleep_pressure'])]
    cases += [dict(family='fatigue',name=str(v),fatigue=v) for v in config['fatigue_levels']]
    cases += [dict(family='left_pain',name=str(v),left_pain=v) for v in config['left_pain_levels']]
    cases += [dict(family='friction',name=str(i),friction=v) for i,v in enumerate(config['friction_pairs'])]
    cases += [dict(family='mixed',name=str(i),**v) for i,v in enumerate(config['mixed'])]
    return [dict(c,id=f'{c["family"]}:{c["name"]}:{d}',duration_s=d) for c in cases for d in config['durations_s']]


def initialize(base,case,region):
    body=UnifiedBody.restore(base);before=body.owner.body()
    if 'fatigue' in case:
        value=case['fatigue']
        if not 0<=value<=1:raise ValueError('invalid declared initial fatigue')
        body.owner.owner.body.state.fatigue={k:float(value) for k in body.owner.owner.body.state.fatigue}
    if 'left_pain' in case:
        value=case['left_pain']
        if not region.endswith('_L') or region not in body.owner.owner.body.pain.regions or not 0<=value<=1:
            raise ValueError('valid left region and initial proxy required')
        body.owner.owner.body.pain.slow[region]=float(value)
    if 'fatigue' in case or 'left_pain' in case:
        loop=body.owner.owner.memory.loop
        # Authored initial conditions are not a realized sensor frame. Obtain
        # the native constructor's current readout, retain the warmed filters,
        # clocks and frame count, and clear the stale last-frame claim.
        loop.sensory.raw=type(loop.sensory)(loop.physical).raw
        loop.sensory.last=None
    body.owner._record(before,body.owner.body(),'external_input',
        'declared synthetic initial fatigue/left-region slow pain proxy; synchronized initial sensory raw readout, stale last frame cleared; filters, clocks and frame count retained; no accumulated work, healing or user-state reset',0.)
    # Validate the complete initialization before a model sees it.
    return UnifiedBody.restore(body.checkpoint())


def confusion(predictions,labels,threshold):
    lookup={r['id']:r['label'] for r in labels}
    if len(predictions)!=len(lookup) or {p['id'] for p in predictions}!=set(lookup):raise ValueError('unpaired predictions')
    c=dict(true_admit=0,true_defer=0,false_admit=0,false_defer=0)
    for p in predictions:
        admitted=p['admit_probability']>=threshold;actual=lookup[p['id']]=='ADMIT'
        key=('true_admit' if admitted else 'false_defer') if actual else ('false_admit' if admitted else 'true_defer')
        c[key]+=1
    n=len(predictions);a=c['true_admit']+c['false_defer'];d=c['true_defer']+c['false_admit']
    ra=c['true_admit']/a if a else None;rd=c['true_defer']/d if d else None
    return dict(n=n,**c,accuracy=(c['true_admit']+c['true_defer'])/n,
        admit_recall=ra,defer_recall=rd,balanced_accuracy=(ra+rd)/2 if a and d else None,
        two_choice_brier=sum((p['admit_probability']-int(lookup[p['id']]=='ADMIT'))**2 for p in predictions)/n)


def aliases(plans,labels=None):
    groups=defaultdict(list)
    for p in plans:groups[p['prompt']].append(p['id'])
    lookup={r['id']:r['label'] for r in labels} if labels is not None else None
    rows=[];minimum_errors=0
    for text,ids in groups.items():
        row=dict(prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),ids=ids)
        if lookup is not None:
            counts={label:sum(lookup[i]==label for i in ids) for label in LABELS}
            row['labels']=counts;row['minimum_errors']=min(counts.values());minimum_errors+=row['minimum_errors']
        rows.append(row)
    result=dict(distinct_prompts=len(groups),cases=len(plans),groups=rows)
    if lookup is not None:
        result.update(minimum_deterministic_prompt_errors=minimum_errors,
                      empirical_prompt_accuracy_ceiling=1-minimum_errors/len(plans))
    return result


def prepare(output,primary,parent):
    out=Path(output).resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    config=json.loads(PROTOCOL.read_text());save(out/'frozen-protocol.json',config)
    primary=Path(primary).resolve();parent=Path(parent).resolve()
    _,previous,primary_directory=bundle(primary)
    if previous['calibration_threshold']!=config['models']['parent_calibrated']['threshold']:
        raise ValueError('parent threshold differs from the previously frozen value')
    locations=dict(parent_calibrated=parent/'adapter',choice_balanced=primary_directory)
    for name,path in locations.items():
        if sha(path/'adapter_model.safetensors')!=config['models'][name]['adapter_sha256']:
            raise ValueError('unexpected frozen model')
        shutil.copytree(path,out/'models'/name)
    save(out/'base-protocol.json',json.loads((primary/'parent-protocol.json').read_text()))
    save(out/'ancestry.json',dict(primary_results_sha256=sha(primary/'results.json'),
        parent_results_sha256=sha(parent/'results.json'),primary_result=previous,
        parent_effective_hashes=json.loads((parent/'results.json').read_text())['effective_attention_after']))
    prepare_defaults();cases=case_specs(config)
    if len(cases)!=config['cases']:raise ValueError('unexpected transfer budget')
    bases={p:fixture(p).checkpoint() for p in {c.get('sleep_pressure',config['ordinary_sleep_pressure']) for c in cases}}
    plans=[]
    for case in cases:
        body=initialize(bases[case.get('sleep_pressure',config['ordinary_sleep_pressure'])],case,config['left_pain_region'])
        q=request(body,case['id'],case['duration_s'])
        if 'friction' in case:q['external']['native']=dict(friction=dict(zip(('L','R'),case['friction'])))
        obs=snapshot(body)
        plans.append(dict(id=case['id'],family=case['family'],spec=case,initial=body.checkpoint(),request=q,
            prompt=prompt(obs,q),input_minimum=obs['minimum'],walking_restrictions=obs['audit']['walking_restrictions'],
            declared_friction=q['external'].get('native',{}).get('friction',dict(L=.6,R=.6))))
    save(out/'plans.json',plans);save(out/'input-aliases-before-labels.json',aliases(plans))
    save(out/'plan-manifest.json',dict(sources=sources(),plans_sha256=sha(out/'plans.json'),
        protocol_sha256=sha(out/'frozen-protocol.json'),model_weights={n:sha(out/'models'/n/'adapter_model.safetensors') for n in locations},
        exposed_features=['sleep pressure','duration','zero versus nonzero friction category','current audit restriction words'],
        omitted_features=['numeric fatigue','numeric regional pain','pain location','nonzero friction magnitude/asymmetry'],
        labels_generated=False))
    print(json.dumps(dict(stage='prepared',cases=len(plans),distinct_prompts=len({p['prompt'] for p in plans}))),flush=True)


def check_inputs(out):
    config=json.loads((out/'frozen-protocol.json').read_text());manifest=json.loads((out/'plan-manifest.json').read_text())
    if config!=json.loads(PROTOCOL.read_text()) or manifest['sources']!=sources() or sha(out/'plans.json')!=manifest['plans_sha256']:
        raise ValueError('frozen transfer inputs/source changed')
    for n,h in manifest['model_weights'].items():
        if sha(out/'models'/n/'adapter_model.safetensors')!=h:raise ValueError('frozen weights changed')
    return config,json.loads((out/'plans.json').read_text())


def load_model(out,base,name):
    model,tok=old.load_base(base,json.loads((out/'base-protocol.json').read_text()))
    model=PeftModel.from_pretrained(model,out/'models'/name,local_files_only=True,is_trainable=False)
    ancestry=json.loads((out/'ancestry.json').read_text())
    expected=(ancestry['parent_effective_hashes'] if name=='parent_calibrated' else
              ancestry['primary_result']['weights']['choice_balanced']['effective_hashes'])
    if old.effective_hashes(model)!=expected:raise ValueError('frozen effective weights mismatch')
    return model,tok


def run(output,base):
    out=Path(output).resolve();config,plans=check_inputs(out)
    if (out/'results.json').exists() or (out/'labels.sqlite').exists():raise ValueError('new frozen run required; no automatic retry')
    torch.set_num_threads(config['cpu_threads']);torch.use_deterministic_algorithms(True)
    predictions={};before={}
    for name in config['models']:
        model,tok=load_model(out,base,name)
        before[name]=old.tensors_hash(model.named_parameters())
        predictions[name]=predict(model,tok,plans,config['max_length'])
        for p in predictions[name]:
            p['raw_argmax_prediction']=p['prediction']
            p['prediction']=LABELS[0] if p['admit_probability']>=config['models'][name]['threshold'] else LABELS[1]
        if old.tensors_hash(model.named_parameters())!=before[name]:raise ValueError('inference changed weights')
        del model
    predictions['audit_preflight']=[dict(id=p['id'],admit_probability=float(not p['walking_restrictions'])) for p in plans]
    for name,value in [('always_admit',1.),('always_defer',0.)]:
        predictions[name]=[dict(id=p['id'],admit_probability=value) for p in plans]
    save(out/'predictions-before-outcomes.json',dict(predictions=predictions,parameter_hashes=before,
         model_weights=config['models'],plans_sha256=sha(out/'plans.json'),sources=sources()))
    print(json.dumps(dict(stage='predictions_committed',cases=len(plans),target_walks_executed=0)),flush=True)
    labels=SelfModel.create(out/'labels.sqlite')
    for index,plan in enumerate(plans):
        body=UnifiedBody.restore(plan['initial']);q=plan['request']
        labels.begin(body,q);receipt=body.cycle(**q);labels.finish(q['event_id'],body,receipt,learn=False)
        print(json.dumps(dict(stage='native_label',completed=index+1,total=len(plans))),flush=True)
    episodes=read_episodes(labels.path)
    labeled=[dict(row_from_episode(p['id'],'held_out',*episodes[p['id']],'frozen transfer native receipt'),family=p['family']) for p in plans]
    if [r['prompt'] for r in labeled]!=[p['prompt'] for p in plans]:raise ValueError('outcome/input mismatch')
    save(out/'labels.json',labeled)
    measured={}
    for name,values in predictions.items():
        threshold=config['models'][name]['threshold'] if name in config['models'] else .5
        measured[name]=dict(overall=confusion(values,labeled,threshold),families={
            family:confusion([r for r in values if r['id'] in {p['id'] for p in plans if p['family']==family}],
                [r for r in labeled if r['family']==family],threshold) for family in sorted({p['family'] for p in plans})})
    after=check_inputs(out);alias=aliases(plans,labeled);save(out/'input-aliases-after-labels.json',alias)
    result=dict(schema=config['schema'],cases=len(plans),metrics=measured,
        predictions_saved_before_target_walks=True,optimizer_steps=0,thresholds_unchanged=True,prompt_unchanged=True,
        weights_unchanged=True,source_hashes=sources(),labels_learned_by_old_self_model=False,
        label_database_sha256=sha(out/'labels.sqlite'),labels_sha256=sha(out/'labels.json'),
        predictions_sha256=sha(out/'predictions-before-outcomes.json'),plans_sha256=sha(out/'plans.json'),
        alias_diagnostic=dict(distinct_prompts=alias['distinct_prompts'],
            conflicting_prompt_groups=sum(r['minimum_errors']>0 for r in alias['groups']),
            minimum_deterministic_prompt_errors=alias['minimum_deterministic_prompt_errors'],
            empirical_prompt_accuracy_ceiling=alias['empirical_prompt_accuracy_ceiling']),
        native_equations_modified=False,live_api_calls=0,existing_advisor_binding_changed=False)
    save(out/'results.json',result)
    subprocess.run([sys.executable,'-m',__package__+'.evaluate','verify','--output',str(out),'--base',str(base)],check=True)
    print(json.dumps(dict(stage='completed',models={n:measured[n]['overall'] for n in config['models']},alias=result['alias_diagnostic'])),flush=True)


def verify(output,base):
    import socket
    calls=[0]
    def forbidden(*a,**k):calls[0]+=1;raise AssertionError('network forbidden')
    socket.socket.connect=forbidden
    out=Path(output);config,plans=check_inputs(out);result=json.loads((out/'results.json').read_text())
    if sha(out/'labels.sqlite')!=result['label_database_sha256'] or sha(out/'labels.json')!=result['labels_sha256']:
        raise ValueError('label evidence changed')
    episodes=read_episodes(out/'labels.sqlite')
    expected_labels=[dict(row_from_episode(p['id'],'held_out',*episodes[p['id']],'frozen transfer native receipt'),family=p['family']) for p in plans]
    if expected_labels!=json.loads((out/'labels.json').read_text()):raise ValueError('receipt label mismatch')
    raw=json.loads((out/'predictions-before-outcomes.json').read_text())
    if sha(out/'predictions-before-outcomes.json')!=result['predictions_sha256']:raise ValueError('prediction evidence changed')
    torch.set_num_threads(config['cpu_threads']);torch.use_deterministic_algorithms(True);errors={}
    for name in config['models']:
        model,tok=load_model(out,base,name);current=predict(model,tok,plans,config['max_length'])
        error=max(abs(a-b) for x,y in zip(current,raw['predictions'][name]) for a,b in zip(x['scores'],y['scores']))
        if error>1e-5 or len(current)!=len(plans) or old.tensors_hash(model.named_parameters())!=raw['parameter_hashes'][name]:
            raise ValueError('frozen prediction restoration mismatch')
        decisions=[LABELS[0] if p['admit_probability']>=config['models'][name]['threshold'] else LABELS[1] for p in current]
        if decisions!=[p['prediction'] for p in raw['predictions'][name]]:raise ValueError('frozen threshold decisions differ')
        errors[name]=error;del model
    save(out/'cold-restoration.json',dict(new_process=True,network_calls=calls[0],score_errors=errors,
        parameter_hashes_equal=True,new_body_cycles=0,optimizer_steps=0,new_learning=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('prepare','evaluate','verify'))
    parser.add_argument('--output',required=True);parser.add_argument('--primary');parser.add_argument('--parent');parser.add_argument('--base')
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.output,args.primary,args.parent)
    elif args.command=='evaluate':run(args.output,args.base)
    else:verify(args.output,args.base)
