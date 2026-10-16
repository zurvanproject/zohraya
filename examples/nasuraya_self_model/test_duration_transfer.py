import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .monitor import SelfModel, snapshot, digest
from .evaluate import fixture, request, prepare_defaults
from .duration_transfer import DurationMemory
from unified_body_v2 import UnifiedBody


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'model.sqlite'
        self.model=SelfModel.create(self.path)

    def train(self, pressures=(.3,.4,.5), durations=(.1,.4,.1)):
        for i,(pressure,duration) in enumerate(zip(pressures,durations)):
            b=fixture(pressure);q=dict(request(b,'train'+str(i),duration),external={})
            self.model.begin(b,q);r=b.cycle(**q);self.model.finish(q['event_id'],b,r)

    def query(self, pressure=.61, duration=.2):
        b=fixture(pressure)
        return snapshot(b),dict(request(b,'query',duration),external={})

    def test_transfer_changes_unseen_duration_advice_without_exact_retrieval(self):
        self.train();obs,q=self.query();m=DurationMemory(self.model)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('read only')):
            self.assertEqual(m.predict(obs,q,pool=False)['probability'],.5)
            self.assertEqual(m.predict(obs,q)['probability'],.8)
            self.assertEqual(m.advise(obs,q)['action'],'walk')
            self.assertEqual(m.advise(obs,q,pool=False)['action'],'observe')
        self.assertEqual(self.model.verify()['episodes'],3)

    def test_never_extrapolates_or_pools_sensory_and_action_contexts(self):
        self.train();m=DurationMemory(self.model)
        for duration in (.5,1.):
            obs,q=self.query(duration=duration)
            self.assertEqual(m.predict(obs,q)['probability'],.5)
        obs,q=self.query();q['external']={'light':.5}
        self.assertEqual(m.predict(obs,q)['evidence'],'unseen_family')
        q['external']={};q['requested']='rest'
        self.assertEqual(m.predict(obs,q)['evidence'],'exact_context')
        with self.assertRaises(ValueError):m.advise(obs,q)

    def test_safety_regime_and_source_identity_never_share_counts(self):
        self.train();m=DurationMemory(self.model)
        obs,q=self.query(pressure=.98)
        self.assertEqual(m.predict(obs,q)['probability'],.5)
        self.assertNotEqual(m.advise(obs,q)['action'],'walk')
        obs,q=self.query();obs['source_identity']='changed-controller'
        obs['observation_sha256']=digest({k:v for k,v in obs.items() if k!='observation_sha256'})
        self.assertEqual(m.predict(obs,q)['evidence'],'unseen_family')

    def test_pending_and_invalid_duration_fail_closed(self):
        obs,q=self.query();m=DurationMemory(self.model)
        for d in (True,float('nan'),float('inf'),0,1.1):
            with self.subTest(d=d),self.assertRaises(ValueError):m.predict(obs,dict(q,duration_s=d))
        b=fixture(.3);r=dict(request(b,'unresolved',.1),external={});self.model.begin(b,r)
        with self.assertRaises(ValueError):m.predict(obs,q)

    def test_frozen_and_reopened_ledgers_predict_identically_with_no_actions(self):
        self.train();obs,q=self.query();m=DurationMemory(self.model)
        original=self.path.read_bytes();expected=m.predict(obs,q)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('no action')):
            self.assertEqual(DurationMemory(SelfModel(self.path)).predict(obs,q),expected)
        self.assertEqual(self.path.read_bytes(),original)

    def test_only_completed_learned_receipts_can_supply_transfer_evidence(self):
        self.train(pressures=(.3,.4),durations=(.1,.4))
        b=fixture(.5);q=dict(request(b,'not-learned',.1),external={})
        self.model.begin(b,q);r=b.cycle(**q);self.model.finish(q['event_id'],b,r,learn=False)
        obs,q=self.query();m=DurationMemory(self.model)
        self.assertEqual(m.predict(obs,q)['probability'],.5)
        with self.model.connection() as db:
            db.execute("UPDATE episodes SET result=? WHERE id='train0'",(json.dumps({'admitted':True}),))
        with self.assertRaises(ValueError):m.predict(obs,q)

    def test_invalid_physical_label_rejects_even_with_repaired_ledger_hash(self):
        self.train(pressures=(.3,),durations=(.1,))
        with self.model.connection() as db:
            (text,)=db.execute("SELECT result FROM episodes WHERE id='train0'").fetchone()
            r=json.loads(text);r['receipt']['owner']['physical_model_valid']=False
            r['admitted']=False;r['brier']=.25
            db.execute("UPDATE episodes SET result=?,result_sha=? WHERE id='train0'",
                       (json.dumps(r),digest(r)))
        # The new layer rejects unsafe labels even when the older ledger accepts them.
        obs,q=self.query()
        with self.assertRaisesRegex(ValueError,'invalid physical'):
            DurationMemory(self.model).predict(obs,q)


if __name__=='__main__':
    unittest.main()
