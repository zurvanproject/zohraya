"""Pre-action feature fidelity, data isolation and native receipt contracts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from .data import PROTOCOL,cases,features,enriched_prompt,initialize,numeric,validate_splits,rows_from_receipts
from .experiment import optimize_checked,should_promote
from examples.nasuraya_self_model.evaluate import fixture,request,prepare_defaults
from examples.nasuraya_self_model.monitor import snapshot,SelfModel
from examples.nasuraya_language_adapter.data import prompt as legacy_prompt


class BodyLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults();cls.base=fixture(.29).checkpoint();cls.config=json.loads(PROTOCOL.read_text())

    def make_plan(self,case=None):
        b=initialize(self.base,case or {},'forefoot_L');q=request(b,'v04:unit',.2);obs=snapshot(b)
        f=features(b,q,obs,self.config['regional_features']);cp=b.checkpoint()
        return b,dict(id=q['event_id'],split='train',family='unit',initial=cp,initial_sha256=cp['sha256'],
            request=q,features=f,prompt=enriched_prompt(f),legacy_prompt=legacy_prompt(obs,q))

    def test_declared_budgets_and_unseen_durations(self):
        train=cases(self.config,'train');held=cases(self.config,'held_out')
        self.assertEqual((len(train),len(held)),(48,40))
        self.assertFalse({r['id'] for r in train}&{r['id'] for r in held})
        self.assertFalse({r['duration_s'] for r in train}&{r['duration_s'] for r in held})

    def test_features_read_real_initial_native_stocks_without_advancing(self):
        b,p=self.make_plan(dict(fatigue=.54,left_pain=.58));before=b.checkpoint()
        f=features(b,p['request'],snapshot(b),self.config['regional_features'])
        self.assertEqual(f['fatigue'],.54);self.assertEqual(f['left_leg_fatigue'],.54)
        self.assertEqual(f['regional_slow_pain']['forefoot_L'],.58)
        self.assertNotEqual(f['regional_slow_pain']['forefoot_R'],.58)
        self.assertEqual(b.checkpoint(),before)
        self.assertNotIn('label',f);self.assertNotIn('actual_action',f)

    def test_nonzero_friction_and_asymmetry_no_longer_alias(self):
        b,p=self.make_plan();q=p['request'];obs=snapshot(b)
        q['external']['native']=dict(friction=dict(L=.12,R=.48))
        a=enriched_prompt(features(b,q,obs,self.config['regional_features']))
        q['external']['native']['friction']=dict(L=.48,R=.12)
        z=enriched_prompt(features(b,q,obs,self.config['regional_features']))
        self.assertNotEqual(a,z);self.assertIn('L=0.1200; R=0.4800',a)

    def test_region_name_and_value_affect_enriched_input(self):
        _,p=self.make_plan();f=deepcopy(p['features']);original=enriched_prompt(f)
        f['regional_slow_pain']['forefoot_L']=.58;left=enriched_prompt(f)
        f=deepcopy(p['features']);f['regional_slow_pain']['forefoot_R']=.58;right=enriched_prompt(f)
        self.assertNotEqual(original,left);self.assertNotEqual(left,right)

    def test_bad_numeric_features_are_rejected(self):
        for value in [float('nan'),float('inf'),-.1,1.1,True,'0.5']:
            with self.assertRaises(ValueError):numeric(value)

    def test_one_foot_friction_is_rejected(self):
        b,p=self.make_plan();p['request']['external']['native']=dict(friction=dict(L=.2))
        with self.assertRaises(ValueError):features(b,p['request'],snapshot(b),self.config['regional_features'])

    def test_held_out_rows_rejected_before_model_access(self):
        with self.assertRaisesRegex(ValueError,'training rows only'):
            optimize_checked(None,None,[dict(id='held',split='held_out')],self.config)

    def test_overlap_of_each_declared_boundary_is_rejected(self):
        a=dict(id='a',split='train',prompt='train',legacy_prompt='oldtrain',initial_sha256='trainsha')
        b=dict(id='b',split='held_out',prompt='held',legacy_prompt='oldheld',initial_sha256='heldsha')
        validate_splits([a,b])
        for key in ('prompt','legacy_prompt','initial_sha256'):
            other=dict(b);other[key]=a[key]
            with self.assertRaisesRegex(ValueError,'overlap'):validate_splits([a,other])

    def test_native_receipt_rows_reject_fabricated_preaction_features(self):
        b,p=self.make_plan(dict(fatigue=.26,left_pain=.22))
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ledger=SelfModel.create(out/'train-labels.sqlite');q=p['request']
            ledger.begin(b,q);receipt=b.cycle(**q);ledger.finish(p['id'],b,receipt,learn=False)
            rows=rows_from_receipts(out,'train',self.config,[p]);self.assertEqual(rows[0]['prompt'],p['prompt'])
            damaged=deepcopy(p);damaged['features']['fatigue']=.99
            with self.assertRaisesRegex(ValueError,'features or native receipt differ'):
                rows_from_receipts(out,'train',self.config,[damaged])

    def test_promotion_requires_gain_and_both_recalls_without_false_admission(self):
        best=dict(overall=dict(false_admit=0,admit_recall=1.,defer_recall=1.,accuracy=1.))
        lesser=dict(overall=dict(false_admit=2,admit_recall=1.,defer_recall=.8,accuracy=.9))
        metrics=dict(trained_enriched=best,parent_calibrated_legacy=lesser,choice_frozen_enriched=lesser)
        self.assertTrue(should_promote(metrics,self.config))
        metrics['parent_calibrated_legacy']=best;self.assertFalse(should_promote(metrics,self.config))
        metrics['parent_calibrated_legacy']=lesser
        metrics['trained_enriched']=deepcopy(best);metrics['trained_enriched']['overall']['false_admit']=1
        self.assertFalse(should_promote(metrics,self.config))


if __name__=='__main__':unittest.main()
