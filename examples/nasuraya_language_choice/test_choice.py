"""Choice-loss separation, balanced sampling and nonbinding API advice."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import torch
from transformers import LlamaConfig,LlamaForCausalLM
from peft import LoraConfig,TaskType,get_peft_model
from examples.nasuraya_language_adapter.test_adapter import ByteTokenizer
from examples.nasuraya_language_adapter.train import frozen_hash,effective_hashes
from .experiment import choice_batch,schedule,threshold_on_train,metrics,optimize


class ChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)

    def rows(self):
        return [dict(id=str(i),split='train',prompt=f'body {i}:',label='ADMIT' if i<2 else 'DEFER') for i in range(8)]

    def test_choice_loss_excludes_eos_prompt_and_padding(self):
        tok=ByteTokenizer();rows=self.rows()[:2];rows[1]['prompt']='p:'
        b=choice_batch(tok,rows,100)
        for i,r in enumerate(rows):
            target=b['labels'][i];labels=target[target!=-100].tolist()
            self.assertEqual(labels,tok.encode(' '+r['label']))
            self.assertNotIn(tok.eos_token_id,labels)
            self.assertTrue(bool((target[:len(r['prompt'])]==-100).all()))

    def test_balanced_batches_have_two_each_and_only_training_ids(self):
        rows=self.rows();targets={r['id']:r['label'] for r in rows}
        for batch in schedule(rows,dict(seed=3,steps=10),True,targets):
            self.assertEqual([r['label'] for r in batch].count('ADMIT'),2)
            self.assertTrue({r['id'] for r in batch}<={r['id'] for r in rows})
        with self.assertRaises(ValueError):list(schedule([dict(rows[0],split='fresh')],dict(seed=3,steps=1),True,targets))

    def test_calibration_rejects_nontraining_labels(self):
        r=dict(self.rows()[0],split='held_out')
        with self.assertRaises(ValueError):threshold_on_train([dict(id=r['id'],admit_probability=.4)],[r])

    def test_all_defer_accuracy_cannot_hide_missing_admissible_actions(self):
        rows=self.rows()[:3]
        rows[0]['label']='ADMIT';rows[1]['label']=rows[2]['label']='DEFER'
        m=metrics([dict(id=r['id'],admit_probability=.2) for r in rows],rows)
        self.assertEqual((m['accuracy'],m['balanced_accuracy'],m['admit_recall']),(2/3,.5,0.))

    def test_choice_gradient_changes_attention_without_unfreezing_base(self):
        torch.manual_seed(3)
        base=LlamaForCausalLM(LlamaConfig(vocab_size=257,hidden_size=32,intermediate_size=48,
            num_hidden_layers=2,num_attention_heads=4,num_key_value_heads=2))
        base.config.use_cache=False
        model=get_peft_model(base,LoraConfig(task_type=TaskType.CAUSAL_LM,r=2,lora_alpha=4,
            lora_dropout=0.,target_modules=['q_proj','v_proj'],bias='none'))
        h=frozen_hash(model);effective=effective_hashes(model)
        log=optimize(model,ByteTokenizer(),self.rows(),dict(seed=3,steps=2,max_length=100,learning_rate=.01),'choice_balanced')
        self.assertEqual(len(log),2);self.assertEqual(frozen_hash(model),h)
        self.assertNotEqual(effective_hashes(model),effective)

    def test_admit_advice_cannot_override_existing_gate(self):
        from examples.nasuraya_body_loop.host import BodyLoop
        from examples.nasuraya_body_loop.metacognition import configure
        from examples.nasuraya_agent_loop.tests.test_agents_api import call
        from . import advisor
        from examples.nasuraya_language_adapter.data import sha
        class Fake:
            weights_sha='a'*64
            def __init__(self,*a):pass
            def assess(self,*a):return dict(prediction='ADMIT',authority='advisory_only',native_authorization=False)
        with tempfile.TemporaryDirectory() as td,BodyLoop.start(Path(td)/'body.sqlite',max_actions=1) as loop:
            configure(loop,memory_path=Path(td)/'memory.sqlite',mode='enforce',
                      expected_checkpoint=loop.body().checkpoint()['sha256'],create_memory=True)
            (Path(td)/'results.json').write_text('{}')
            contract=dict(schema=advisor.KEY,run=td,base=td,weights_sha256=Fake.weights_sha,
                results_sha256=sha(Path(td)/'results.json'),sources=advisor.advisor_source(),authority='advisory_only')
            loop.engine.db.execute('INSERT INTO meta VALUES(?,?)',(advisor.KEY,json.dumps(contract)))
            with patch.object(advisor,'LanguageAdvisor',Fake):
                host=advisor.AdvisedBodyAPIHost(loop,mode='bounded',target_cycles=1)
            before=loop.body().checkpoint()
            obs=json.loads(host.handle_required('session',call('observe_body',{},'read','turn'))['output'])
            args=dict(action='walk',duration_s=.1,observed_checkpoint_sha256=obs['checkpoint_sha256'])
            a=json.loads(host.handle_required('session',call('assess_body_action',args,'advice','turn'))['output'])
            self.assertEqual(a['language_advisor']['prediction'],'ADMIT')
            result=json.loads(host.handle_required('session',call('request_body_action',args,'request','turn'))['output'])
            self.assertEqual(result['status'],'deferred');self.assertFalse(result['native_executed'])
            self.assertEqual(loop.body().checkpoint(),before)
            self.assertEqual(loop.metacognition.model.verify()['episodes'],0)

    def test_legacy_factory_stays_opt_in(self):
        from examples.nasuraya_body_loop.host import BodyLoop
        from examples.nasuraya_body_loop.api_host import BodyAPIHost
        from examples.nasuraya_body_loop.language_advisor import host_type
        with tempfile.TemporaryDirectory() as td,BodyLoop.start(Path(td)/'body.sqlite') as loop:
            self.assertIs(host_type(loop),BodyAPIHost)


if __name__=='__main__':unittest.main()
