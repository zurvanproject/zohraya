"""Bounded CPU LoRA training of a real pretrained causal language model."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

import torch
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

from .data import LABELS, PROTOCOL, load_verified, prepare, save, sha


def tensors_hash(tensors):
    h = hashlib.sha256()
    for name, value in sorted(tensors):
        value = value.detach().cpu().contiguous()
        h.update(name.encode()); h.update(str(tuple(value.shape)).encode())
        h.update(str(value.dtype).encode()); h.update(value.numpy().tobytes())
    return h.hexdigest()


def frozen_hash(model):
    return tensors_hash((n,p) for n,p in model.named_parameters() if not p.requires_grad)


def effective_hashes(model):
    return {name: tensors_hash([(name, module.base_layer.weight + module.get_delta_weight('default'))])
            for name,module in model.named_modules() if hasattr(module, 'get_delta_weight')}


def encode_row(tokenizer, row, max_length):
    prefix = tokenizer.encode(row['prompt'], add_special_tokens=False)
    answer = tokenizer.encode(' '+row['label'], add_special_tokens=False) + [tokenizer.eos_token_id]
    if not prefix or not answer or len(prefix)+len(answer) > max_length:
        raise ValueError('empty or overlong training example; no silent truncation')
    return prefix+answer, [-100]*len(prefix)+answer


def batch(tokenizer, rows, max_length):
    encoded = [encode_row(tokenizer,r,max_length) for r in rows]
    size = max(len(x[0]) for x in encoded)
    return dict(input_ids=torch.tensor([x+[tokenizer.pad_token_id]*(size-len(x)) for x,y in encoded]),
        attention_mask=torch.tensor([[1]*len(x)+[0]*(size-len(x)) for x,y in encoded]),
        labels=torch.tensor([y+[-100]*(size-len(y)) for x,y in encoded]))


def evaluate(model, tokenizer, rows, max_length):
    model.eval()
    predictions = []
    with torch.inference_mode():
        for row in rows:
            data = batch(tokenizer, [dict(row,label=label) for label in LABELS], max_length)
            logits = model(input_ids=data['input_ids'], attention_mask=data['attention_mask']).logits[:,:-1]
            labels = data['labels'][:,1:]
            mask = labels != -100
            token_logp = logits.log_softmax(-1).gather(-1,labels.clamp_min(0).unsqueeze(-1)).squeeze(-1)
            scores = (token_logp*mask).sum(-1)
            probs = scores.softmax(-1)
            actual = LABELS.index(row['label'])
            predictions.append(dict(id=row['id'], label=row['label'], prediction=LABELS[int(scores.argmax())],
                admit_two_choice_probability=float(probs[0]), scores=[float(x) for x in scores],
                answer_token_nll=float(-scores[actual]/mask[actual].sum())))
    n = len(predictions)
    recalls = [sum(r['label']==label and r['prediction']==label for r in predictions)/
               sum(r['label']==label for r in predictions) for label in LABELS]
    return dict(rows=predictions, metrics=dict(accuracy=sum(r['label']==r['prediction'] for r in predictions)/n,
        balanced_accuracy=sum(recalls)/len(recalls),
        two_choice_brier=sum((r['admit_two_choice_probability']-int(r['label']=='ADMIT'))**2 for r in predictions)/n,
        answer_token_nll=sum(r['answer_token_nll'] for r in predictions)/n))


def train_batches(model, tokenizer, rows, config):
    if not rows or any(r['split']!='train' for r in rows):
        raise ValueError('optimizer accepts training rows only')
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),
                                 lr=config['learning_rate'], weight_decay=0.)
    generator = torch.Generator().manual_seed(config['seed'])
    log = []
    for epoch in range(config['epochs']):
        model.train()
        order = torch.randperm(len(rows), generator=generator).tolist()
        for offset in range(0,len(order),config['batch_size']):
            selected = [rows[i] for i in order[offset:offset+config['batch_size']]]
            optimizer.zero_grad(set_to_none=True)
            loss = model(**batch(tokenizer,selected,config['max_length'])).loss
            if not bool(torch.isfinite(loss)):
                raise ValueError('nonfinite training loss')
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
            if not bool(torch.isfinite(norm)):
                raise ValueError('nonfinite gradient')
            optimizer.step()
            row = dict(step=len(log)+1,epoch=epoch+1,loss=float(loss.detach()),gradient_norm=float(norm),
                       example_ids=[r['id'] for r in selected])
            log.append(row)
            print(json.dumps(dict(stage='training',step=row['step'],epoch=row['epoch'],loss=row['loss'])),flush=True)
    return log


def load_base(directory, protocol):
    directory = Path(directory).resolve()
    source = json.loads(Path(__file__).with_name('model-source.json').read_text())
    if source['revision'] != protocol['base_revision'] or source['model'] != protocol['base_model']:
        raise ValueError('unexpected base model source contract')
    for name, expected in source['files_sha256'].items():
        if sha(directory/name) != expected:
            raise ValueError('unexpected pretrained base file: '+name)
    tokenizer = AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(directory,local_files_only=True,
        trust_remote_code=False,use_safetensors=True,torch_dtype=torch.float32,attn_implementation='eager')
    model.config.use_cache = False
    model.config._name_or_path = protocol['base_model']
    return model,tokenizer


def run(output, base_directory):
    out = Path(output).resolve()
    protocol = json.loads((out/'frozen-protocol.json').read_text())
    if protocol != json.loads(PROTOCOL.read_text()) or (out/'results.json').exists():
        raise ValueError('new frozen run required; completed results cannot be overwritten')
    rows = load_verified(out)
    torch.set_num_threads(protocol['cpu_threads']); torch.manual_seed(protocol['seed'])
    torch.use_deterministic_algorithms(True)
    started = time.monotonic()
    model,tokenizer = load_base(base_directory,protocol)
    base_count = sum(p.numel() for p in model.parameters())
    lora = protocol['lora']
    layers = list(range(model.config.num_hidden_layers-lora['last_layers'],model.config.num_hidden_layers))
    model = get_peft_model(model,LoraConfig(task_type=TaskType.CAUSAL_LM,r=lora['rank'],
        lora_alpha=lora['alpha'],lora_dropout=lora['dropout'],target_modules=lora['targets'],
        layers_to_transform=layers,bias='none'))
    initial = {n:p.detach().clone() for n,p in model.named_parameters() if p.requires_grad}
    before_hash = tensors_hash(initial.items()); base_before = frozen_hash(model)
    effective_before = effective_hashes(model)
    model.save_pretrained(out/'initial-adapter',safe_serialization=True,save_embedding_layers=False)
    held = [r for r in rows if r['split']=='held_out']
    baseline = evaluate(model,tokenizer,held,protocol['max_length'])
    save(out/'baseline.json',baseline)
    print(json.dumps(dict(stage='baseline',metrics=baseline['metrics'])),flush=True)
    training = train_batches(model,tokenizer,[r for r in rows if r['split']=='train'],protocol)
    save(out/'training-log.json',training)
    final = evaluate(model,tokenizer,held,protocol['max_length'])
    save(out/'final.json',final)
    after = {n:p.detach() for n,p in model.named_parameters() if p.requires_grad}
    changes = [dict(name=n,elements=p.numel(),changed_elements=int(torch.count_nonzero(p-initial[n])),
                    l2_change=float(torch.linalg.vector_norm(p-initial[n]))) for n,p in after.items()]
    base_after = frozen_hash(model)
    effective_after = effective_hashes(model)
    if base_before != base_after or before_hash == tensors_hash(after.items()):
        raise ValueError('expected changed adapter weights and unchanged base weights')
    model.save_pretrained(out/'adapter',safe_serialization=True,save_embedding_layers=False)
    tokenizer.save_pretrained(out/'tokenizer')
    result = dict(schema=protocol['schema'],base_model=protocol['base_model'],base_revision=protocol['base_revision'],
        base_weights_sha256=protocol['base_weights_sha256'],base_parameters=base_count,
        adapter_parameters=sum(p.numel() for p in after.values()),optimizer_steps=len(training),
        trained_example_ids=sorted({i for step in training for i in step['example_ids']}),
        held_out_used_for_optimization=False,protocol_sha256=sha(out/'frozen-protocol.json'),
        dataset_sha256=sha(out/'dataset.jsonl'),
        code_sha256={p.name:sha(p) for p in Path(__file__).parent.glob('*.py')},
        model_source_sha256=sha(Path(__file__).with_name('model-source.json')),
        initial_trainable_tensors_sha256=before_hash,final_trainable_tensors_sha256=tensors_hash(after.items()),
        frozen_tensors_before_sha256=base_before,frozen_tensors_after_sha256=base_after,
        effective_attention_before=effective_before,effective_attention_after=effective_after,
        changed_effective_attention_matrices=sum(effective_before[n]!=v for n,v in effective_after.items()),
        tensor_changes=changes,all_trainable_weights_finite=all(bool(torch.isfinite(p).all()) for p in after.values()),
        baseline=baseline['metrics'],final=final['metrics'],
        metric_scope='two fixed completions on one authored fixture family; not free generation or general intelligence',
        native_mechanics_modified=False,live_api_model_replaced=False,chatgpt_weights_modified=False,
        execution_authority='none',elapsed_seconds=time.monotonic()-started)
    save(out/'results.json',result)
    # Persist before a separate process tests the actual saved weights.
    subprocess.run([sys.executable,'-m',__package__+'.train','verify','--output',str(out),
                    '--base',str(Path(base_directory).resolve())],check=True)
    print(json.dumps(dict(stage='complete',adapter_parameters=result['adapter_parameters'],
        effective_matrices_changed=result['changed_effective_attention_matrices'],baseline=result['baseline'],
        final=result['final'])),flush=True)


def verify(output,base_directory):
    import socket
    calls = [0]
    def forbidden(*args,**kwargs):
        calls[0] += 1
        raise AssertionError('restoration must not use network')
    socket.socket.connect = forbidden
    out = Path(output)
    protocol = json.loads((out/'frozen-protocol.json').read_text())
    result = json.loads((out/'results.json').read_text())
    if (result['code_sha256'] != {p.name:sha(p) for p in Path(__file__).parent.glob('*.py')} or
            result['model_source_sha256'] != sha(Path(__file__).with_name('model-source.json'))):
        raise ValueError('training code/source changed since the checkpoint')
    torch.set_num_threads(protocol['cpu_threads']); torch.use_deterministic_algorithms(True)
    model,tokenizer = load_base(base_directory,protocol)
    model = PeftModel.from_pretrained(model,out/'adapter',local_files_only=True,is_trainable=False)
    held = [r for r in load_verified(out) if r['split']=='held_out']
    actual = evaluate(model,tokenizer,held,protocol['max_length'])
    expected = json.loads((out/'final.json').read_text())
    error = max(abs(a-b) for arow,brow in zip(actual['rows'],expected['rows'])
                for a,b in zip(arow['scores'],brow['scores']))
    if len(actual['rows']) != len(expected['rows']) or error > 1e-5 or calls[0]:
        raise ValueError('saved model does not reproduce final logits offline')
    if effective_hashes(model) != result['effective_attention_after']:
        raise ValueError('restored effective attention weights differ')
    save(out/'cold-restoration.json',dict(new_process=True,network_calls=calls[0],
        max_sequence_log_likelihood_error=error,effective_weights_equal=True,
        predictions_equal=[r['prediction'] for r in actual['rows']]==[r['prediction'] for r in expected['rows']],
        new_optimizer_steps=0,new_body_cycles=0))


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=('prepare','train','verify'))
    parser.add_argument('--output',required=True)
    parser.add_argument('--base')
    parser.add_argument('--live-memory')
    args = parser.parse_args()
    if args.command=='prepare': prepare(args.output,args.live_memory)
    elif args.command=='train': run(args.output,args.base)
    else: verify(args.output,args.base)
