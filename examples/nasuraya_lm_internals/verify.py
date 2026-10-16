"""Verify saved arrays against receipts without loading pretrained weights."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .probe import HERE, difference, signature


def verify(directory):
    root = Path(directory)
    protocol = json.loads((root/'frozen-protocol.json').read_text())
    if protocol != json.loads((HERE/'protocol.json').read_text()):
        raise ValueError('protocol mismatch')
    result = json.loads((root/'results.json').read_text())
    assert result['protocol_sha256'] == hashlib.sha256((HERE/'protocol.json').read_bytes()).hexdigest()
    assert result['checks_passed'] and result['weights_before'] == result['weights_after']
    assert [r['id'] for r in result['prompts']] == [r['id'] for r in protocol['prompts']]
    count, forwards = 0, 0
    arch = result['architecture']
    for row in result['prompts']:
        baseline = None
        for condition in protocol['conditions']:
            receipt = row['conditions'][condition]
            with np.load(root/f"{row['id']}-{condition}.npz", allow_pickle=False) as arrays:
                assert set(arrays.files) == set(receipt['traces'])
                for name in arrays.files:
                    assert signature(arrays[name]) == receipt['traces'][name], (row['id'], condition, name)
                    count += 1
                logits = arrays['logits']
                if condition == 'baseline':
                    baseline = logits.copy()
                    length = len(row['input_token_ids'])
                    assert np.array_equal(arrays['input_ids'], [row['input_token_ids']])
                    assert len(arrays.files) == 2 + (arch['layers']+1) + arch['layers']
                    for layer in range(arch['layers']+1):
                        assert arrays[f'hidden_{layer:02d}'].shape == (1, length, arch['hidden_size'])
                    for layer in range(arch['layers']):
                        attention = arrays[f'attention_{layer:02d}']
                        assert attention.shape == (1, arch['attention_heads'], length, length)
                        assert np.allclose(attention.sum(-1), 1., atol=2e-6, rtol=0)
                        assert np.max(np.abs(np.triu(attention, k=1))) <= 1e-7
                assert difference(baseline, logits) == receipt['comparison']
                if condition in ('sham', 'restored'):
                    assert receipt['comparison']['exact_equal']
                    assert receipt['token_ids'] == row['conditions']['baseline']['token_ids']
            forwards += len(receipt['token_ids'])
            assert 0 < len(receipt['token_ids']) <= protocol['max_new_tokens']
            if condition in ('target', 'control', 'sham'):
                assert receipt['hook']['removed']
                assert receipt['hook']['calls'] == len(receipt['token_ids'])
    assert forwards == result['forward_passes'] <= 120
    return dict(verified_arrays=count, forward_passes=forwards, prompts=len(result['prompts']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('directory')
    print(json.dumps(verify(parser.parse_args().directory)))
