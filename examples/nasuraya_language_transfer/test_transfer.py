"""Fixture fidelity, omitted inputs, frozen weights and nonmisleading metrics."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .evaluate import PROTOCOL,case_specs,initialize,confusion,aliases,check_inputs,sources
from examples.nasuraya_self_model.evaluate import fixture,request,prepare_defaults
from examples.nasuraya_self_model.monitor import snapshot
from examples.nasuraya_language_adapter.data import prompt,sha,save


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults();cls.base=fixture(.31).checkpoint()

    def test_fixed_budget_has_five_declared_families(self):
        config=json.loads(PROTOCOL.read_text());cases=case_specs(config)
        self.assertEqual(len(cases),42);self.assertEqual(len({c['id'] for c in cases}),42)
        self.assertEqual({f:sum(c['family']==f for c in cases) for f in {c['family'] for c in cases}},
                         dict(control=6,fatigue=10,left_pain=8,friction=12,mixed=6))

    def test_synthetic_fatigue_and_only_declared_left_pain_restore(self):
        from unified_body_v2 import UnifiedBody
        original=UnifiedBody.restore(self.base)
        before=deepcopy(original.owner.owner.body.pain.slow)
        changed=initialize(self.base,dict(fatigue=.56,left_pain=.55),'forefoot_L')
        self.assertTrue(all(v==.56 for v in changed.owner.owner.body.state.fatigue.values()))
        self.assertEqual(changed.owner.owner.body.pain.slow['forefoot_L'],.55)
        self.assertEqual({k:v for k,v in changed.owner.owner.body.pain.slow.items() if k!='forefoot_L'},
                         {k:v for k,v in before.items() if k!='forefoot_L'})
        self.assertEqual(original.checkpoint(),self.base)
        sensor=changed.owner.owner.memory.loop.sensory
        prior=original.owner.owner.memory.loop.sensory
        self.assertEqual(sensor.frames,prior.frames)
        self.assertEqual(sensor.time_s,prior.time_s)
        self.assertEqual(sensor.lowpass,prior.lowpass)
        self.assertIsNone(sensor.last)
        self.assertEqual(sensor.raw['max_leg_fatigue'],.56)
        self.assertEqual(UnifiedBody.restore(changed.checkpoint()).checkpoint(),changed.checkpoint())

    def test_existing_prompt_aliases_different_nonzero_friction(self):
        body=initialize(self.base,{},'forefoot_L');obs=snapshot(body);q=request(body,'unit',.5)
        q['external']['native']=dict(friction=dict(L=.05,R=.05));first=prompt(obs,q)
        q['external']['native']['friction']=dict(L=.45,R=.45)
        self.assertEqual(first,prompt(obs,q))
        self.assertNotIn('0.45',first)

    def test_missing_class_does_not_invent_balanced_accuracy(self):
        labels=[dict(id='a',label='ADMIT'),dict(id='b',label='ADMIT')]
        result=confusion([dict(id='a',admit_probability=.8),dict(id='b',admit_probability=.1)],labels,.5)
        self.assertEqual(result['admit_recall'],.5)
        self.assertIsNone(result['defer_recall']);self.assertIsNone(result['balanced_accuracy'])

    def test_parent_threshold_is_applied_without_recalibration(self):
        labels=[dict(id='a',label='ADMIT'),dict(id='b',label='DEFER')]
        p=[dict(id='a',admit_probability=.4),dict(id='b',admit_probability=.2)]
        self.assertEqual(confusion(p,labels,.5)['false_defer'],1)
        self.assertEqual(confusion(p,labels,.3299630433320999)['accuracy'],1.)

    def test_conflicting_identical_inputs_have_empirical_error_floor(self):
        plans=[dict(id=str(i),prompt='same') for i in range(3)]
        labels=[dict(id=str(i),label='ADMIT' if i<2 else 'DEFER') for i in range(3)]
        result=aliases(plans,labels)
        self.assertEqual(result['minimum_deterministic_prompt_errors'],1)
        self.assertAlmostEqual(result['empirical_prompt_accuracy_ceiling'],2/3)

    def test_changed_frozen_weight_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);save(out/'frozen-protocol.json',json.loads(PROTOCOL.read_text()));save(out/'plans.json',[])
            file=out/'models/choice_balanced/adapter_model.safetensors';file.parent.mkdir(parents=True);file.write_bytes(b'original')
            save(out/'plan-manifest.json',dict(sources=sources(),plans_sha256=sha(out/'plans.json'),
                                             model_weights=dict(choice_balanced=sha(file))))
            file.write_bytes(b'changed')
            with self.assertRaises(ValueError):check_inputs(out)


if __name__=='__main__':unittest.main()
