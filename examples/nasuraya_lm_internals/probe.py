"""Capture real internals and apply temporary activation interventions on CPU.

python -m examples.nasuraya_lm_internals.probe --base DIR --output NEW_DIR
python -m examples.nasuraya_lm_internals.probe --base DIR --output NEW_DIR --compare OLD_DIR
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import platform
from pathlib import Path
import socket
import time
from unittest.mock import patch

import numpy as np
import torch
import transformers

from examples.nasuraya_language_adapter.train import load_base, frozen_hash

HERE = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


@contextmanager
def offline():
    """Fail on Python socket connects, including local connects; not an OS sandbox."""
    def deny(*args, **kwargs):
        raise RuntimeError('network disabled during internal-access probe')
    with patch.object(socket.socket, 'connect', deny), \
         patch.object(socket.socket, 'connect_ex', deny), \
         patch.object(socket, 'create_connection', deny):
        yield


@contextmanager
def head_gate(model, layer, head=None):
    """Clone the input; zero one head only when supplied; always remove hook."""
    if not 0 <= layer < model.config.num_hidden_layers:
        raise ValueError('layer outside model')
    heads = model.config.num_attention_heads
    width = model.config.hidden_size // heads
    if head is not None and not 0 <= head < heads:
        raise ValueError('head outside model')
    receipt = dict(calls=0, first=None, removed=False)

    def hook(module, args):
        original = args[0]
        value = original.clone()
        if head is not None:
            value[:, -1, head*width:(head+1)*width] = 0
        delta = value[:, -1] - original[:, -1]
        receipt['calls'] += 1
        if receipt['first'] is None:
            receipt['first'] = dict(changed_scalars=int(torch.count_nonzero(delta)),
                                   delta_l2=float(delta.norm()),
                                   before_l2=float(original[:, -1].norm()))
        return (value,) + args[1:]

    handle = model.model.layers[layer].self_attn.o_proj.register_forward_pre_hook(hook)
    try:
        yield receipt
    finally:
        handle.remove()
        receipt['removed'] = True


def signature(array):
    array = np.ascontiguousarray(array)
    if not np.isfinite(array).all():
        raise ValueError('nonfinite captured tensor')
    return dict(shape=list(array.shape), dtype=str(array.dtype),
                sha256=hashlib.sha256(array.tobytes()).hexdigest(),
                l2=float(np.linalg.norm(array.astype(np.float64))))


def generate(model, tokenizer, ids, budget, capture):
    current = ids.clone()
    arrays = {}
    first_logits = None
    tokens = []
    with torch.inference_mode():
        for step in range(budget):
            output = model(input_ids=current, attention_mask=torch.ones_like(current),
                           use_cache=False, output_hidden_states=capture and step == 0,
                           output_attentions=capture and step == 0, return_dict=True)
            logits = output.logits[0, -1].detach().cpu().numpy().copy()
            if step == 0:
                first_logits = logits
                arrays['logits'] = logits
                if capture:
                    arrays['input_ids'] = ids.cpu().numpy().copy()
                    for i, state in enumerate(output.hidden_states):
                        arrays[f'hidden_{i:02d}'] = state.cpu().numpy().copy()
                    for i, attention in enumerate(output.attentions):
                        if attention is None:
                            raise ValueError('attention unavailable; eager implementation required')
                        value = attention.cpu().numpy().copy()
                        if not np.allclose(value.sum(-1), 1., atol=2e-6, rtol=0):
                            raise ValueError('attention rows not normalized')
                        if np.max(np.abs(np.triu(value, k=1))) > 1e-7:
                            raise ValueError('causal mask violated')
                        arrays[f'attention_{i:02d}'] = value
            token = int(np.argmax(logits))
            tokens.append(token)
            current = torch.cat((current, torch.tensor([[token]], dtype=torch.long)), dim=1)
            if token == tokenizer.eos_token_id:
                break
    return dict(token_ids=tokens, text=tokenizer.decode(tokens, skip_special_tokens=False)), first_logits, arrays


def difference(reference, actual):
    # Float64 comparison avoids spurious negative KL from float32 cancellation.
    def logp(x):
        x = x.astype(np.float64)
        x = x - x.max()
        return x - np.log(np.exp(x).sum())
    a, b = logp(reference), logp(actual)
    return dict(exact_equal=bool(np.array_equal(reference, actual)),
                max_abs_logit_change=float(np.max(np.abs(reference-actual))),
                probability_l1=float(np.abs(np.exp(a)-np.exp(b)).sum()),
                kl_baseline_to_condition=float((np.exp(a)*(a-b)).sum()),
                top_token_changed=bool(reference.argmax() != actual.argmax()))


def run(base, output, compare=None):
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE/'protocol.json').read_text())
    save(out/'frozen-protocol.json', protocol)  # Persist before loading/inference.
    torch.set_num_threads(protocol['cpu_threads'])
    torch.manual_seed(protocol['seed'])
    torch.use_deterministic_algorithms(True)
    started = time.monotonic()
    with offline():
        model, tokenizer = load_base(base, protocol)
        model.requires_grad_(False)
        model.eval()
        before = frozen_hash(model)
        results = dict(protocol_sha256=hashlib.sha256((HERE/'protocol.json').read_bytes()).hexdigest(),
                       environment=dict(python=platform.python_version(), torch=torch.__version__,
                                        transformers=transformers.__version__, numpy=np.__version__,
                                        machine=platform.machine(), cpu_threads=protocol['cpu_threads']),
                       architecture=dict(layers=model.config.num_hidden_layers,
                           attention_heads=model.config.num_attention_heads,
                           kv_heads=model.config.num_key_value_heads, hidden_size=model.config.hidden_size,
                           head_dim=model.config.hidden_size//model.config.num_attention_heads,
                           parameters=sum(p.numel() for p in model.parameters()),
                           dtype=str(next(model.parameters()).dtype)),
                       weights_before=before, prompts=[], forward_passes=0)
        for prompt in protocol['prompts']:
            ids = tokenizer(prompt['text'], add_special_tokens=False, return_tensors='pt')['input_ids']
            if not 0 < ids.shape[1] <= protocol['max_input_tokens']:
                raise ValueError('input budget violated')
            row = dict(id=prompt['id'], input_token_ids=ids[0].tolist(), conditions={})
            baseline_logits = None
            for condition in protocol['conditions']:
                receipt = None
                if condition in ('sham', 'target', 'control'):
                    head = dict(sham=None, target=protocol['target_head'], control=protocol['control_head'])[condition]
                    with head_gate(model, protocol['layer_index'], head) as receipt:
                        generated, logits, arrays = generate(model, tokenizer, ids, protocol['max_new_tokens'], False)
                else:
                    generated, logits, arrays = generate(model, tokenizer, ids, protocol['max_new_tokens'], condition == 'baseline')
                results['forward_passes'] += len(generated['token_ids'])
                if baseline_logits is None:
                    baseline_logits = logits
                delta = difference(baseline_logits, logits)
                traces = {name: signature(value) for name, value in arrays.items()}
                np.savez_compressed(out/f"{prompt['id']}-{condition}.npz", **arrays)
                top = np.argsort(logits)[-5:][::-1]
                row['conditions'][condition] = dict(**generated, hook=receipt, traces=traces,
                    comparison=delta, top5=[dict(id=int(t), text=tokenizer.decode([int(t)]), logit=float(logits[t])) for t in top])
                if condition in ('sham', 'restored'):
                    assert delta['exact_equal'], 'non-invasive/restoration check failed'
                    assert generated == {k: row['conditions']['baseline'][k] for k in ('token_ids', 'text')}
                if receipt is not None:
                    assert receipt['removed'] and receipt['calls'] == len(generated['token_ids'])
                    assert receipt['first']['changed_scalars'] == (0 if condition == 'sham' else results['architecture']['head_dim'])
                print(json.dumps(dict(prompt=prompt['id'], condition=condition, **delta)), flush=True)
            results['prompts'].append(row)
        results['weights_after'] = frozen_hash(model)
        assert results['weights_after'] == before, 'model weights changed'
        assert results['forward_passes'] <= len(protocol['prompts'])*len(protocol['conditions'])*protocol['max_new_tokens']
        assert not any(p.requires_grad or p.grad is not None for p in model.parameters())
        assert all(not layer.self_attn.o_proj._forward_pre_hooks for layer in model.model.layers)
        results['elapsed_seconds'] = time.monotonic()-started
        results['checks_passed'] = True
        if compare is not None:
            previous = json.loads((Path(compare)/'results.json').read_text())
            comparable = ('protocol_sha256', 'architecture', 'weights_before', 'weights_after', 'prompts', 'forward_passes')
            for key in comparable:
                if results[key] != previous[key]:
                    raise ValueError('fresh-process replay differs: '+key)
            results['fresh_process_exact_replay'] = True
        save(out/'results.json', results)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--compare')
    args = parser.parse_args()
    run(args.base, args.output, args.compare)
