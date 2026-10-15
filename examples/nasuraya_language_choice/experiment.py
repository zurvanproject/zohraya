"""One fixed ablation, with fresh predictions committed before outcome labels."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess
import sys
import torch
from peft import PeftModel

from examples.nasuraya_language_adapter import train as old
from examples.nasuraya_language_adapter.data import LABELS, load_verified, prompt, row_from_episode, read_episodes, save, sha
from examples.nasuraya_self_model.evaluate import fixture, request, prepare_defaults
from examples.nasuraya_self_model.monitor import SelfModel, snapshot, digest
from unified_body_v2 import UnifiedBody

PROTOCOL = Path(__file__).with_name('protocol.json')


def source_hashes():
    files=list((PROTOCOL.parent.parent/'nasuraya_language_adapter').glob('*.py'))
    files += [Path(__file__),Path(__file__).with_name('__init__.py')]
    files += [PROTOCOL.parent.parent/'nasuraya_self_model'/name for name in ('monitor.py','evaluate.py')]
    return {str(p.relative_to(PROTOCOL.parents[2])):sha(p) for p in files}


def choice_batch(tokenizer, rows, maximum):
    encoded = []
    for row in rows:
        prefix = tokenizer.encode(row['prompt'],add_special_tokens=False)
        answer = tokenizer.encode(' '+row['label'],add_special_tokens=False)
        if not prefix or not answer or len(prefix)+len(answer)>maximum:
            raise ValueError('empty or overlong choice')
        encoded.append((prefix+answer,[-100]*len(prefix)+answer))
    size = max(len(x) for x,y in encoded)
    return dict(input_ids=torch.tensor([x+[tokenizer.pad_token_id]*(size-len(x)) for x,y in encoded]),
        attention_mask=torch.tensor([[1]*len(x)+[0]*(size-len(x)) for x,y in encoded]),
        labels=torch.tensor([y+[-100]*(size-len(y)) for x,y in encoded]))


def scores(model, tokenizer, rows, maximum):
    data = choice_batch(tokenizer,[dict(r,label=l) for r in rows for l in LABELS],maximum)
    logits = model(input_ids=data['input_ids'],attention_mask=data['attention_mask']).logits[:,:-1]
    labels = data['labels'][:,1:]; mask = labels!=-100
    logp = logits.log_softmax(-1).gather(-1,labels.clamp_min(0).unsqueeze(-1)).squeeze(-1)
    return (logp*mask).sum(-1).reshape(len(rows),len(LABELS))


def predict(model, tokenizer, rows, maximum):
    model.eval(); result=[]
    with torch.inference_mode():
        for r in rows:
            s=scores(model,tokenizer,[r],maximum)[0]
            result.append(dict(id=r['id'],scores=s.tolist(),
                admit_probability=float(s.softmax(-1)[0]),prediction=LABELS[int(s.argmax())]))
    return result


def metrics(predictions, rows, threshold=.5):
    lookup={r['id']:r for r in rows}
    if len(predictions)!=len(lookup) or {r['id'] for r in predictions}!=set(lookup):
        raise ValueError('prediction/label set mismatch')
    correct={l:0 for l in LABELS};total={l:0 for l in LABELS}
    for p in predictions:
        label=lookup[p['id']]['label'];total[label]+=1
        correct[label]+=((p['admit_probability']>=threshold)==(label=='ADMIT'))
    recalls={l:correct[l]/total[l] for l in LABELS}
    return dict(accuracy=sum(correct.values())/len(predictions),balanced_accuracy=sum(recalls.values())/2,
        admit_recall=recalls['ADMIT'],defer_recall=recalls['DEFER'],
        brier=sum((p['admit_probability']-int(lookup[p['id']]['label']=='ADMIT'))**2 for p in predictions)/len(predictions),
        predictions={l:sum((p['admit_probability']>=threshold)==(l=='ADMIT') for p in predictions) for l in LABELS})


def threshold_on_train(predictions,rows):
    if any(r['split']!='train' for r in rows):raise ValueError('calibration accepts training rows only')
    values=sorted({p['admit_probability'] for p in predictions})
    thresholds=[0.]+[(a+b)/2 for a,b in zip(values,values[1:])]+[1.]
    return max(thresholds,key=lambda t:(metrics(predictions,rows,t)['balanced_accuracy'],-abs(t-.5)))


def schedule(rows, config, balanced, targets):
    if not rows or any(r['split']!='train' for r in rows):raise ValueError('training rows only')
    rng=random.Random(config['seed']);pools={l:[r for r in rows if targets[r['id']]==l] for l in LABELS}
    if balanced and any(not p for p in pools.values()):raise ValueError('two classes required')
    source={l:[] for l in LABELS};raw=[]
    for _ in range(config['steps']):
        selected=[]
        for label in (['ADMIT','ADMIT','DEFER','DEFER'] if balanced else [None]*4):
            pool=source[label] if label else raw
            if not pool:
                pool.extend(pools[label] if label else rows);rng.shuffle(pool)
            selected.append(pool.pop())
        yield selected


def optimize(model,tokenizer,rows,config,arm):
    targets={r['id']:r['label'] for r in rows}
    if arm=='choice_shuffled':
        perm=list(targets.values());random.Random(config['seed']+1).shuffle(perm)
        targets=dict(zip(targets,perm))
    optim=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=config['learning_rate'],weight_decay=0.)
    log=[]
    for selected in schedule(rows,config,arm.endswith('balanced') or arm=='choice_shuffled',targets):
        model.train();optim.zero_grad(set_to_none=True)
        if arm.startswith('ce_'):
            loss=model(**old.batch(tokenizer,selected,config['max_length'])).loss
        else:
            s=scores(model,tokenizer,selected,config['max_length'])
            loss=torch.nn.functional.cross_entropy(s,torch.tensor([LABELS.index(targets[r['id']]) for r in selected]))
        if not bool(torch.isfinite(loss)):raise ValueError('nonfinite loss')
        loss.backward();norm=torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
        if not bool(torch.isfinite(norm)):raise ValueError('nonfinite gradient')
        optim.step()
        log.append(dict(step=len(log)+1,loss=float(loss.detach()),ids=[r['id'] for r in selected],
                        targets=[targets[r['id']] for r in selected]))
    return log


def prepare(output,parent):
    out=Path(output).resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    config=json.loads(PROTOCOL.read_text());save(out/'frozen-protocol.json',config)
    parent=Path(parent).resolve();rows=load_verified(parent)
    if sha(parent/'dataset.jsonl')!=config['parent_dataset_sha256']:raise ValueError('unexpected parent data')
    save(out/'parent.json',dict(path=str(parent),dataset_sha256=sha(parent/'dataset.jsonl'),
        adapter_sha256=sha(parent/'adapter/adapter_model.safetensors'),results_sha256=sha(parent/'results.json')))
    save(out/'parent-protocol.json',json.loads((parent/'frozen-protocol.json').read_text()))
    prepare_defaults();plans=[]
    for pressure in config['fresh_sleep_pressure']:
        body=fixture(pressure);initial=body.checkpoint();obs=snapshot(body)
        for duration in config['fresh_duration_s']:
            for intervention in config['fresh_interventions']:
                identifier=f'fresh:{pressure}:{duration}:{intervention}'
                q=request(body,identifier,duration)
                if intervention=='zero_friction':q['external']['native']=dict(friction=dict(L=0.,R=0.))
                plans.append(dict(id=identifier,split='fresh',prompt=prompt(obs,q),initial=initial,request=q))
    if ({p['prompt'] for p in plans}&{r['prompt'] for r in rows} or
        {p['initial']['sha256'] for p in plans}&{r['initial_checkpoint_sha256'] for r in rows}):
        raise ValueError('fresh case overlaps previous data')
    save(out/'fresh-plans.json',plans)
    print(json.dumps(dict(stage='prepared',fresh_cases=len(plans),labels_generated=False)),flush=True)


def load_parent(out):
    contract=json.loads((out/'parent.json').read_text());parent=Path(contract['path'])
    if (sha(parent/'adapter/adapter_model.safetensors')!=contract['adapter_sha256'] or
            sha(parent/'dataset.jsonl')!=contract['dataset_sha256'] or
            sha(parent/'results.json')!=contract['results_sha256']):raise ValueError('parent changed')
    return parent


def model_from_parent(out,base,trainable=True):
    parent=load_parent(out);p=json.loads((parent/'frozen-protocol.json').read_text())
    model,tok=old.load_base(base,p)
    return PeftModel.from_pretrained(model,parent/'adapter',local_files_only=True,is_trainable=trainable),tok


def run(output,base):
    out=Path(output).resolve();config=json.loads((out/'frozen-protocol.json').read_text())
    if config!=json.loads(PROTOCOL.read_text()) or (out/'results.json').exists() or (out/'fresh-labels.sqlite').exists():
        raise ValueError('a new frozen experiment is required')
    torch.set_num_threads(config['cpu_threads']);torch.manual_seed(config['seed']);torch.use_deterministic_algorithms(True)
    parent=load_parent(out);rows=load_verified(parent);train=[r for r in rows if r['split']=='train']
    plans=json.loads((out/'fresh-plans.json').read_text());predictions={};weights={}
    model,tok=model_from_parent(out,base)
    train_pred=predict(model,tok,train,config['max_length'])
    threshold=threshold_on_train(train_pred,train)
    predictions['parent']=predict(model,tok,plans,config['max_length'])
    save(out/'parent-predictions.json',dict(train=train_pred,fresh=predictions['parent'],train_only_threshold=threshold))
    del model
    for arm in config['arms']:
        model,tok=model_from_parent(out,base)
        before=old.frozen_hash(model);initial={n:p.detach().clone() for n,p in model.named_parameters() if p.requires_grad}
        log=optimize(model,tok,train,config,arm)
        if old.frozen_hash(model)!=before:raise ValueError('base weights changed')
        directory=out/arm;directory.mkdir()
        model.save_pretrained(directory/'adapter',safe_serialization=True,save_embedding_layers=False)
        predictions[arm]=predict(model,tok,plans,config['max_length'])
        save(directory/'fresh-predictions.json',predictions[arm]);save(directory/'training-log.json',log)
        weights[arm]=dict(base_frozen_sha256=before,effective_hashes=old.effective_hashes(model),
            adapter_sha256=sha(directory/'adapter/adapter_model.safetensors'),
            changed_elements=sum(int(torch.count_nonzero(p-initial[n])) for n,p in model.named_parameters() if p.requires_grad))
        print(json.dumps(dict(stage='trained',arm=arm,steps=len(log))),flush=True)
        del model
    # Commit all model predictions before the first fresh native outcome is generated.
    save(out/'before-fresh-labels.json',dict(predictions=predictions,weights=weights,calibration_threshold=threshold,
        fresh_plans_sha256=sha(out/'fresh-plans.json'),sources=source_hashes()))
    labels=SelfModel.create(out/'fresh-labels.sqlite')
    for plan in plans:
        body=UnifiedBody.restore(plan['initial']);q=plan['request']
        labels.begin(body,q);receipt=body.cycle(**q);labels.finish(q['event_id'],body,receipt,learn=False)
    episodes=read_episodes(labels.path)
    labeled=[row_from_episode(p['id'],'held_out',*episodes[p['id']],'fresh native receipt after prediction commit') for p in plans]
    if [r['prompt'] for r in labeled]!=[p['prompt'] for p in plans]:raise ValueError('label belongs to another input')
    save(out/'fresh-labels.json',labeled)
    measured={name:metrics(pred,labeled) for name,pred in predictions.items()}
    measured['parent_calibrated']=metrics(predictions['parent'],labeled,threshold)
    primary=measured[config['primary_arm']];gate=config['promotion']
    promote=(primary['balanced_accuracy']>=gate['balanced_accuracy_min'] and primary['admit_recall']>=gate['admit_recall_min']
        and primary['defer_recall']>=gate['defer_recall_min'] and
        primary['balanced_accuracy']-measured['parent']['balanced_accuracy']>=gate['gain_over_raw_parent_min'])
    result=dict(schema=config['schema'],metrics=measured,primary_arm=config['primary_arm'],promote_advisory=promote,
        fresh_labels_generated_after_predictions=True,fresh_native_cycles=len(plans),train_rows=len(train),
        native_equations_modified=False,identity_modified=False,weights=weights,
        sources=source_hashes(),before_labels_sha256=sha(out/'before-fresh-labels.json'),
        fresh_label_database_sha256=sha(out/'fresh-labels.sqlite'),
        fresh_labels_sha256=sha(out/'fresh-labels.json'),protocol_sha256=sha(out/'frozen-protocol.json'),
        calibration_threshold=threshold,base_directory=str(Path(base).resolve()))
    save(out/'results.json',result)
    subprocess.run([sys.executable,'-m',__package__+'.experiment','verify','--output',str(out),'--base',str(base)],check=True)
    print(json.dumps(dict(stage='complete',promote_advisory=promote,metrics=measured)),flush=True)


def verify(output,base):
    import socket
    calls=[0]
    def forbidden(*a,**k):calls[0]+=1;raise AssertionError('network forbidden')
    socket.socket.connect=forbidden
    out=Path(output);result=json.loads((out/'results.json').read_text());config=json.loads((out/'frozen-protocol.json').read_text())
    if result['sources']!=source_hashes():raise ValueError('source mismatch')
    torch.set_num_threads(config['cpu_threads']);torch.use_deterministic_algorithms(True)
    model,tok=old.load_base(base,json.loads((out/'parent-protocol.json').read_text()))
    model=PeftModel.from_pretrained(model,out/config['primary_arm']/'adapter',local_files_only=True,is_trainable=False)
    actual=predict(model,tok,json.loads((out/'fresh-plans.json').read_text()),config['max_length'])
    expected=json.loads((out/config['primary_arm']/'fresh-predictions.json').read_text())
    error=max(abs(a-b) for x,y in zip(actual,expected) for a,b in zip(x['scores'],y['scores']))
    if error>1e-5 or len(actual)!=len(expected) or calls[0] or old.effective_hashes(model)!=result['weights'][config['primary_arm']]['effective_hashes']:
        raise ValueError('offline restore mismatch')
    save(out/'cold-restoration.json',dict(new_process=True,network_calls=calls[0],max_score_error=error,
        effective_weights_equal=True,new_optimizer_steps=0,new_body_cycles=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('prepare','train','verify'))
    parser.add_argument('--output',required=True);parser.add_argument('--parent');parser.add_argument('--base')
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.output,args.parent)
    elif args.command=='train':run(args.output,args.base)
    else:verify(args.output,args.base)
