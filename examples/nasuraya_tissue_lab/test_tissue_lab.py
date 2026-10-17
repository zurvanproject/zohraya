from copy import deepcopy
import json
import unittest
from tissue_lab import TissueObserver, NAMES, forecast, digest


def fixture():
    return dict(source_id='fixture/0',kind='recorded_snapshot',source_tick=1,
        Q_L_min=10.5,reference_flow_L_min=10.5,oxygen_proxy=1.,
        paid_W=dict(special=.2,neural=2.,immune=1.),systemic_inflammation=0.,
        patency={n:1. for n in NAMES},lymph={n:1. for n in NAMES},insult={n:0. for n in NAMES})


class TissueTests(unittest.TestCase):
    def test_shared_flow_and_paid_budget(self):
        for q in (0.,.01,10.5,49.5,100.):
            x=fixture();x['Q_L_min']=q
            r=TissueObserver().advance(x)
            self.assertAlmostEqual(r['allocated_flow_L_min']+r['unassigned_flow_L_min'],q)
            for k in x['paid_W']: self.assertLessEqual(r['paid_annotation_J'][k],x['paid_W'][k]*.1+1e-12)
            self.assertEqual(r['native_energy_debit_J'],0.)

    def test_oxygen_absent_no_function(self):
        x=fixture();x['oxygen_proxy']=0
        self.assertTrue(all(r['function_ceiling']==0 for r in TissueObserver().advance(x)['regions'].values()))

    def test_unfunded_special_does_not_borrow(self):
        x=fixture();x['paid_W']['special']=0
        r=TissueObserver().advance(x)['regions']
        self.assertEqual(r['resonan_L']['function_ceiling'],0)
        self.assertEqual(r['spandar']['function_ceiling'],0)
        self.assertEqual(r['brain']['function_ceiling'],1)

    def test_local_obstruction_is_local(self):
        x=fixture();x['patency']['resonan_L']=0
        r=TissueObserver().advance(x)['regions']
        self.assertEqual(r['resonan_L']['delivery_index'],0)
        self.assertEqual(r['resonan_R']['delivery_index'],1)

    def test_failed_lymph_worsens_inflamed_tissue(self):
        x=fixture();x['systemic_inflammation']=1
        _,normal=forecast(x)
        _,blocked=forecast(x,intervention=lambda z:z['lymph'].update(spandar=0))
        self.assertGreater(blocked[-1]['regions']['spandar']['edema_index'],normal[-1]['regions']['spandar']['edema_index'])
        self.assertLess(blocked[-1]['regions']['spandar']['function_ceiling'],normal[-1]['regions']['spandar']['function_ceiling'])

    def test_cold_restore_continues_identically(self):
        a=TissueObserver();x=fixture();a.advance(x)
        b=TissueObserver.restore(json.loads(json.dumps(a.checkpoint())))
        x['source_id']='fixture/1';x['source_tick']=2
        self.assertEqual(a.advance(x),b.advance(x));self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_replay_and_stale_do_not_commit(self):
        a=TissueObserver();x=fixture();a.advance(x);before=a.checkpoint()
        with self.assertRaises(ValueError):a.advance(x)
        x['source_id']='new-id'
        with self.assertRaises(ValueError):a.advance(x)
        self.assertEqual(a.checkpoint(),before)

    def test_invalid_input_is_atomic(self):
        for key,value in (('Q_L_min',float('nan')),('oxygen_proxy',1.01),('reference_flow_L_min',0)):
            a=TissueObserver();x=fixture();x[key]=value;before=a.checkpoint()
            with self.assertRaises(ValueError):a.advance(x)
            self.assertEqual(a.checkpoint(),before)

    def test_input_not_mutated(self):
        x=fixture();before=deepcopy(x);TissueObserver().advance(x);forecast(x);self.assertEqual(x,before)

    def test_forged_or_invalid_state_rejected(self):
        x=TissueObserver().checkpoint();x['payload']['time_s']=4
        with self.assertRaises(ValueError):TissueObserver.restore(x)
        x=TissueObserver().checkpoint();x['payload']['regions']['face']['edema_index']=2;x['sha256']=digest(x['payload'])
        with self.assertRaises(ValueError):TissueObserver.restore(x)

    def test_pressure_flow_reduction_lowers_delivery(self):
        x=fixture();r=TissueObserver().advance(x)
        x['Q_L_min']/=2;s=TissueObserver().advance(x)
        self.assertAlmostEqual(s['regions']['myocardium']['delivery_index'],.5*r['regions']['myocardium']['delivery_index'])

    def test_forecast_label_and_time_bounds(self):
        x=fixture();_,rows=forecast(x,seconds=3)
        self.assertEqual(rows[-1]['observer_time_s'],3)
        self.assertTrue(all(r['kind']=='forecast' for r in rows))
        with self.assertRaises(ValueError):TissueObserver().advance(x,1.1)


if __name__=='__main__': unittest.main()
