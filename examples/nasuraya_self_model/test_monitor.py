"""Native-receipt, chronology and uncertainty contracts for metacognition."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from .monitor import SelfModel,snapshot,context,digest
from .evaluate import fixture,request,prepare_defaults


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'self.sqlite';self.model=SelfModel.create(self.path)

    def episode(self,event,pressure=.3,learn=True):
        b=fixture(pressure);q=request(b,event);pred=self.model.begin(b,q)
        receipt=b.cycle(**q);result=self.model.finish(event,b,receipt,learn=learn)
        return b,q,pred,receipt,result

    def test_unseen_context_is_explicit_and_abstains(self):
        b=fixture(.3);report=self.model.inspect(snapshot(b),request(b,'new'))
        self.assertEqual(report['inferred']['probability'],.5)
        self.assertTrue(report['inferred']['unseen_context'])
        self.assertEqual(report['recommendation'],'pause_and_observe')
        self.assertIn('subjective_experience',report['unknown'])

    def test_requested_action_is_separate_from_verified_native_effect(self):
        b,q,p,r,result=self.episode('veto',.95)
        self.assertFalse(result['admitted'])
        state=self.model.verify();self.assertEqual(state['last']['requested'],'walk')
        self.assertNotEqual(state['last']['actual'],'walk')
        self.assertEqual(sum(sum(v) for v in state['counts'].values()),1)

    def test_experience_changes_self_efficacy_and_recommendation(self):
        for i in range(3):self.episode('learn-'+str(i),.2+i*.03)
        b=fixture(.4);report=self.model.inspect(snapshot(b),request(b,'future'))
        self.assertEqual(report['inferred']['samples'],3)
        self.assertEqual(report['inferred']['probability'],.8)
        self.assertEqual(report['recommendation'],'continue_with_native_guards')
        high=fixture(.95);unknown=self.model.inspect(snapshot(high),request(high,'novel'))
        self.assertTrue(unknown['inferred']['unseen_context'])
        self.assertEqual(unknown['recommendation'],'pause_and_observe')

    def test_stale_observation_overrides_learned_confidence(self):
        for i in range(3):self.episode('learn-'+str(i))
        b=fixture(.4);obs=snapshot(b)
        report=self.model.inspect(obs,request(b,'old'),at_simulated_s=obs['time_s']+6)
        self.assertEqual(report['recommendation'],'pause_and_observe')
        self.assertIn('current_body_state',report['unknown'])

    def test_report_and_forecast_do_not_change_the_body(self):
        b=fixture(.3);before=b.checkpoint();obs=snapshot(b)
        self.model.inspect(obs,request(b,'read'))
        self.assertEqual(before,b.checkpoint())

    def test_context_separates_duration_and_external_intervention(self):
        b=fixture(.3);obs=snapshot(b);q=request(b,'context')
        changed=deepcopy(q);changed['duration_s']=1.
        self.assertNotEqual(context(obs,q),context(obs,changed))
        changed=deepcopy(q);changed['external']['native']={'friction':{'L':0.,'R':0.}}
        self.assertNotEqual(context(obs,q),context(obs,changed))
        changed=deepcopy(q);changed['external']['sensors']['vision']['value']=.9
        self.assertNotEqual(context(obs,q),context(obs,changed))
        changed=deepcopy(q);changed['external']['sensors']={}
        self.assertNotEqual(context(obs,q),context(obs,changed))
        changed=deepcopy(q);changed['external']['sensors']['vision']['sampled_at_s']-=6
        self.assertNotEqual(context(obs,q),context(obs,changed))

    def test_unknown_pending_result_blocks_learning_past_it(self):
        b=fixture(.3);self.model.begin(b,request(b,'pending'))
        other=fixture(.4)
        with self.assertRaises(ValueError):self.model.begin(other,request(other,'next'))
        self.assertEqual(SelfModel(self.path).verify()['pending'],['pending'])

    def test_result_without_prior_prediction_is_rejected(self):
        b=fixture(.3);q=request(b,'late');r=b.cycle(**q)
        with self.assertRaises(ValueError):self.model.finish('late',b,r)
        self.assertEqual(self.model.verify()['episodes'],0)

    def test_unrelated_receipt_rejected_without_model_update(self):
        b=fixture(.3);q=request(b,'real');self.model.begin(b,q);r=b.cycle(**q)
        bad=deepcopy(r);bad['owner']['selected_action']='protect'
        with self.assertRaises(ValueError):self.model.finish('real',b,bad)
        self.assertEqual(self.model.verify()['counts'],{})
        self.assertEqual(self.model.verify()['pending'],['real'])

    def test_duplicate_finish_is_idempotent(self):
        b,q,p,r,result=self.episode('once');before=self.model.verify()
        self.assertEqual(self.model.finish('once',b,r),result)
        self.assertEqual(self.model.verify(),before)

    def test_held_out_receipts_do_not_train_model(self):
        self.episode('train');before=self.model.verify()['counts']
        self.episode('held-out',.4,learn=False)
        self.assertEqual(self.model.verify()['counts'],before)

    def test_tampered_observation_or_model_history_rejected(self):
        b=fixture(.3);obs=snapshot(b);obs['minimum']['energy']=0.
        with self.assertRaises(ValueError):self.model.inspect(obs,request(b,'false'))
        self.episode('stored')
        with sqlite3.connect(self.path) as db:
            result=json.loads(db.execute('SELECT result FROM episodes').fetchone()[0]);result['admitted']=False
            db.execute('UPDATE episodes SET result=?,result_sha=?',(json.dumps(result),digest(result)))
        with self.assertRaises(ValueError):SelfModel(self.path)

    def test_existing_memory_never_resets_implicitly(self):
        self.episode('keep');before=self.model.verify()
        with self.assertRaises(FileExistsError):SelfModel.create(self.path)
        self.assertEqual(SelfModel(self.path).verify(),before)


if __name__=='__main__':unittest.main()
