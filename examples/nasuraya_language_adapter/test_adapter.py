"""Masking, split integrity and real attention-weight optimization checks."""
from copy import deepcopy
import unittest

import torch
from transformers import LlamaConfig, LlamaForCausalLM
from peft import LoraConfig, TaskType, get_peft_model

from .data import row_from_episode, validate_rows
from .train import batch, effective_hashes, frozen_hash, train_batches


class ByteTokenizer:
    eos_token_id = pad_token_id = 0
    def encode(self, text, **kwargs):
        return [b+1 for b in text.encode()]


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_prompt_and_padding_are_excluded_from_training_loss(self):
        tok = ByteTokenizer()
        rows = [dict(prompt='long prompt:',label='ADMIT'),dict(prompt='p:',label='DEFER')]
        result = batch(tok,rows,100)
        for i,row in enumerate(rows):
            prefix = len(row['prompt'].encode())
            target = tok.encode(' '+row['label'])+[tok.eos_token_id]
            self.assertEqual(result['labels'][i,:prefix].tolist(),[-100]*prefix)
            self.assertEqual(result['labels'][i,prefix:prefix+len(target)].tolist(),target)
            self.assertTrue(bool((result['labels'][i,prefix+len(target):]==-100).all()))

    def test_overlong_example_is_rejected_without_truncating_label(self):
        with self.assertRaises(ValueError):
            batch(ByteTokenizer(),[dict(prompt='x'*100,label='ADMIT')],50)

    def test_optimizer_refuses_held_out_rows_before_accessing_model(self):
        with self.assertRaises(ValueError):
            train_batches(None,None,[dict(split='held_out')],{})

    def test_gradient_updates_attention_adapter_and_preserves_base(self):
        torch.manual_seed(7)
        config = LlamaConfig(vocab_size=257,hidden_size=32,intermediate_size=48,
                            num_hidden_layers=2,num_attention_heads=4,num_key_value_heads=2)
        base = LlamaForCausalLM(config)
        base.config.use_cache = False
        model = get_peft_model(base,LoraConfig(task_type=TaskType.CAUSAL_LM,r=2,
            lora_alpha=4,lora_dropout=0.,target_modules=['q_proj','v_proj'],bias='none'))
        frozen = frozen_hash(model); effective = effective_hashes(model)
        rows = [dict(id='train-a',split='train',prompt='body normal:',label='ADMIT'),
                dict(id='train-b',split='train',prompt='body restricted:',label='DEFER')]
        log = train_batches(model,ByteTokenizer(),rows,
            dict(seed=1,epochs=2,batch_size=2,learning_rate=.01,max_length=100))
        self.assertEqual(len(log),2)
        self.assertEqual(frozen_hash(model),frozen)
        self.assertNotEqual(effective_hashes(model),effective)
        self.assertEqual({i for r in log for i in r['example_ids']},{'train-a','train-b'})

    def episode(self):
        obs = dict(minimum=dict(sleep_pressure=.2),audit=dict(walking_restrictions=[]),
                   native_sha='body-sha',observation_sha256='obs-sha')
        intent = dict(before=obs,request=dict(requested='walk',duration_s=.1,
                                            external={},event_id='event'))
        result = dict(admitted=True,receipt=dict(owner=dict(selected_action='walk',physical_model_valid=True)))
        return intent,result

    def test_label_cannot_be_changed_independently_of_receipt(self):
        intent,result = self.episode()
        row = row_from_episode('a','train',intent,result,'test fixture')
        row['label'] = 'DEFER'
        with self.assertRaises(ValueError):
            validate_rows([row],{'event':(intent,result)})

    def test_same_body_or_prompt_cannot_cross_train_and_test(self):
        intent,result = self.episode()
        a = row_from_episode('a','train',intent,result,'test fixture')
        b = row_from_episode('b','held_out',intent,result,'test fixture')
        with self.assertRaises(ValueError):
            validate_rows([a,b],{'event':(intent,result)})


if __name__=='__main__':
    unittest.main()
