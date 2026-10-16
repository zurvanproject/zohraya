"""Small actual transformer tests; no downloads or 135M weights required."""
import socket
import unittest

import numpy as np
import torch
from transformers import LlamaConfig, LlamaForCausalLM

from .probe import difference, head_gate, offline, signature
from examples.nasuraya_language_adapter.train import frozen_hash


class ProbeTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(17)
        self.model = LlamaForCausalLM(LlamaConfig(vocab_size=32, hidden_size=16,
            intermediate_size=32, num_hidden_layers=2, num_attention_heads=4,
            num_key_value_heads=2, attention_dropout=0.))
        self.model.config._attn_implementation = 'eager'
        self.model.requires_grad_(False)
        self.model.eval()
        self.ids = torch.tensor([[1, 4, 8]])

    def forward(self):
        with torch.inference_mode():
            return self.model(self.ids).logits.clone()

    def test_sham_and_restore_exact_with_frozen_weights(self):
        before_hash = frozen_hash(self.model)
        baseline = self.forward()
        with head_gate(self.model, 1) as sham:
            self.assertTrue(torch.equal(baseline, self.forward()))
        self.assertEqual(sham['first']['changed_scalars'], 0)
        with head_gate(self.model, 1, 0) as intervention:
            changed = self.forward()
        self.assertFalse(torch.equal(baseline, changed))
        self.assertEqual(intervention['first']['changed_scalars'], 4)
        self.assertTrue(intervention['removed'])
        self.assertTrue(torch.equal(baseline, self.forward()))
        self.assertEqual(before_hash, frozen_hash(self.model))

    def test_hook_removed_after_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'deliberate'):
            with head_gate(self.model, 0, 1) as receipt:
                raise RuntimeError('deliberate')
        self.assertTrue(receipt['removed'])
        self.assertFalse(self.model.model.layers[0].self_attn.o_proj._forward_pre_hooks)

    def test_head_and_layer_bounds(self):
        for layer, head in [(-1, 0), (2, 0), (0, -1), (0, 4)]:
            with self.assertRaises(ValueError):
                with head_gate(self.model, layer, head):
                    pass

    def test_hook_does_not_mutate_caller_activation(self):
        value = torch.randn(1, 3, 16)
        original = value.clone()
        module = self.model.model.layers[0].self_attn.o_proj
        with head_gate(self.model, 0, 1):
            with torch.inference_mode():
                module(value)
        self.assertTrue(torch.equal(value, original))

    def test_attention_and_hidden_capture(self):
        with torch.inference_mode():
            result = self.model(self.ids, output_hidden_states=True, output_attentions=True)
        self.assertEqual(len(result.hidden_states), 3)
        self.assertEqual(len(result.attentions), 2)
        self.assertEqual(tuple(result.attentions[0].shape), (1, 4, 3, 3))
        self.assertTrue(torch.allclose(result.attentions[0].sum(-1), torch.ones(1, 4, 3)))
        self.assertEqual(int(torch.count_nonzero(torch.triu(result.attentions[0], diagonal=1))), 0)

    def test_distribution_comparison(self):
        x = np.array([1., 2., 3.], dtype=np.float32)
        self.assertTrue(difference(x, x.copy())['exact_equal'])
        self.assertGreater(difference(x, -x)['kl_baseline_to_condition'], 0)
        with self.assertRaises(ValueError):
            signature(np.array([np.nan]))

    def test_network_is_denied_and_restored(self):
        previous = socket.create_connection
        with offline():
            with self.assertRaisesRegex(RuntimeError, 'network disabled'):
                socket.create_connection(('127.0.0.1', 80))
        self.assertIs(socket.create_connection, previous)


if __name__ == '__main__':
    unittest.main()
