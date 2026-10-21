from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .energy import EnergyCalibration, features, example, score, POLICY
from .monitor import digest
from .monitor import ROOT
from .planning import empty_learning, score as original_score


def states(posture='shift',offset=0):
    m=dict(posture=posture,sleep_pressure=.3,fatigue=.1,pain=.1)
    before=dict(fuel_J=1000.,minimum=m)
    predicted=dict(fuel_J=900.,minimum=deepcopy(m),requested='walk')
    return before,predicted,features(before,predicted,offset)


def ready(residual=40.,validation=40.):
    model=EnergyCalibration();b,p,f=states()
    for i in range(3):model.add('train:'+str(i),dict(features=f,raw_J=100.,actual_J=100.+residual))
    model.begin_validation()
    for i in range(2):model.add('validate:'+str(i),dict(features=f,raw_J=100.,actual_J=100.+validation))
    model.freeze()
    return model,f


class EnergyTests(unittest.TestCase):
    def test_known_bias_is_shrunk_and_unseen_context_falls_back(self):
        m,f=ready();self.assertEqual(m.predict(f,100.),120.)
        other={**f,'posture':'walk_swing'};self.assertEqual(m.predict(other,100.),100.)

    def test_validation_rejects_harmful_training_correction(self):
        m,f=ready(validation=-40.);self.assertEqual(m.predict(f,100.),100.)

    def test_insufficient_evidence_and_unfrozen_model_use_raw(self):
        m=EnergyCalibration();b,p,f=states()
        for i in range(2):m.add(str(i),dict(features=f,raw_J=100.,actual_J=140.))
        self.assertEqual(m.predict(f,100.),100.)
        m.begin_validation()
        for i in range(2):m.add('v'+str(i),dict(features=f,raw_J=100.,actual_J=140.))
        m.freeze();self.assertEqual(m.predict(f,100.),100.)

    def test_actual_action_and_actual_result_never_enter_features(self):
        b,p,f=states();plan=dict(initial=b,chosen='walk',candidates=dict(walk=dict(series=[p])))
        row=dict(decision=dict(before=b,plan=plan,offset=0),after=dict(fuel_J=860.),
                 receipt=dict(owner=dict(selected_action='walk')))
        x=example(row);row['after']['fuel_J']=999.;row['receipt']['owner']['selected_action']='slow_breath'
        y=example(row)
        self.assertEqual(x['features'],y['features']);self.assertNotEqual(x['actual_J'],y['actual_J'])
        # All outcomes (including vetoes) teach the same pre-action context.
        a=EnergyCalibration();c=EnergyCalibration()
        a.add('same',x);c.add('same',{**x,'actual_action':'slow_breath'})
        self.assertEqual(a.checkpoint(),c.checkpoint())

    def test_forecast_age_and_posture_separate_contexts(self):
        b,p,f=states()
        self.assertNotEqual(f,features(b,p,1));self.assertNotEqual(features(b,p,1),features(b,p,4))
        self.assertNotEqual(f,states(posture='walk_swing')[2])

    def test_train_validate_freeze_and_duplicate_events_are_irreversible(self):
        m=EnergyCalibration();b,p,f=states();item=dict(features=f,raw_J=100.,actual_J=140.)
        m.add('one',item);before=m.checkpoint()
        with self.assertRaises(ValueError):m.add('one',item)
        self.assertEqual(m.checkpoint(),before)
        with self.assertRaises(ValueError):m.freeze()
        m.begin_validation()
        with self.assertRaises(ValueError):m.begin_validation()
        m.freeze();before=m.checkpoint()
        with self.assertRaises(ValueError):m.add('held',item)
        self.assertEqual(m.checkpoint(),before)

    def test_restore_at_every_stage_preserves_learning_and_predictions(self):
        m=EnergyCalibration();b,p,f=states();item=dict(features=f,raw_J=100.,actual_J=140.)
        for i in range(3):m.add(str(i),item)
        m=EnergyCalibration.restore(json.loads(json.dumps(m.checkpoint())))
        m.begin_validation();m.add('v1',item)
        m=EnergyCalibration.restore(json.loads(json.dumps(m.checkpoint())))
        m.add('v2',item);m.freeze()
        cold=EnergyCalibration.restore(json.loads(json.dumps(m.checkpoint())))
        self.assertEqual(m.checkpoint(),cold.checkpoint());self.assertEqual(cold.predict(f,100.),120.)

    def test_training_finishes_identically_in_a_fresh_process(self):
        m=EnergyCalibration();b,p,f=states();item=dict(features=f,raw_J=100.,actual_J=140.)
        for i in range(3):m.add(str(i),item)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'handoff.json';output=Path(tmp)/'resumed.json'
            path.write_text(json.dumps(dict(model=m.checkpoint(),item=item)))
            code='''import json,sys
from pathlib import Path
from examples.nasuraya_self_model.energy import EnergyCalibration
d=json.loads(Path(sys.argv[1]).read_text());m=EnergyCalibration.restore(d['model'])
m.begin_validation()
for i in range(2):m.add('v'+str(i),d['item'])
m.freeze();Path(sys.argv[2]).write_text(json.dumps(m.checkpoint()))
'''
            subprocess.run([sys.executable,'-c',code,str(path),str(output)],cwd=ROOT,check=True)
            m.begin_validation()
            for i in range(2):m.add('v'+str(i),item)
            m.freeze();self.assertEqual(json.loads(output.read_text()),m.checkpoint())

    def test_corrupt_counts_source_policy_and_nonfinite_rejected(self):
        m,f=ready();saved=m.checkpoint()
        for mutate in [lambda p:p['seen'].append('invented'),
                       lambda p:p['sources'].update({'energy.py':'wrong'}),
                       lambda p:p['policy'].update({'shrinkage':1.}),
                       lambda p:p.update(stage='other')]:
            bad=deepcopy(saved);mutate(bad['payload']);bad['sha256']=digest(bad['payload'])
            with self.assertRaises(ValueError):EnergyCalibration.restore(bad)
        for value in [float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):m.predict(f,value)

    def test_outliers_are_robust_and_correction_is_bounded(self):
        m=EnergyCalibration();b,p,f=states()
        for i,e in enumerate([40.,40.,100000.]):m.add(str(i),dict(features=f,raw_J=100.,actual_J=100.+e))
        m.begin_validation()
        for i in range(2):m.add('v'+str(i),dict(features=f,raw_J=100.,actual_J=140.))
        m.freeze();self.assertEqual(m.correction(f),20.)
        huge,f=ready(residual=10000.,validation=1000.)
        self.assertEqual(huge.correction(f),POLICY['correction_limit_J'])

    def test_scoring_adapter_preserves_eta_fatigue_and_inputs(self):
        m,f=ready();b,p,_=states()
        c=dict(strategy='walk',eta_s=5.,horizon_s=1,fuel_debit_J=100.,series=[p])
        learning=empty_learning();learning['fuel_bias_J']['walk']=999.
        before=deepcopy((c,b,learning,m.checkpoint()))
        raw=empty_learning()
        self.assertAlmostEqual(score(c,b,m,learning),original_score(c,raw)+.020)
        self.assertEqual((c,b,learning,m.checkpoint()),before)
        # The opt-in adapter can affect a cost comparison with a close candidate.
        alternate=deepcopy(c);alternate['strategy']='observe';alternate['series'][0]['requested']='observe'
        alternate['eta_s']=5.01
        self.assertLess(original_score(c,raw),original_score(alternate,raw))
        self.assertGreater(score(c,b,m,learning),score(alternate,b,m,learning))


if __name__=='__main__':unittest.main()
