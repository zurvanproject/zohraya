from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from .adapters import digest, geometry, monitoring_stats, project_trajectory, sensory_sample
from .integrity import ROOT, verify_sources


class IntegrationChecks(unittest.TestCase):
    def test_exact_upstream_inventory_and_four_projects(self):
        lock = verify_sources()
        self.assertEqual(len({r['repository'] for r in lock['files']}), 4)
        self.assertEqual(len(lock['files']), 9)

    def test_modified_source_fails_before_import(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            (target/'vendor/battery_probe.py').write_text('raise AssertionError("executed")\n')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                verify_sources(target)

    def test_rehashed_changed_lock_is_not_a_new_trust_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            p = target/'upstream-lock.json'
            value = json.loads(p.read_text()); value['files'] = []
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'lock changed'):
                verify_sources(target)

    def test_upstream_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            path = target/'vendor/battery_probe.py'; path.unlink()
            path.symlink_to(ROOT/'vendor/battery_probe.py')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                verify_sources(target)

    def test_selective_withdrawal_and_unselective_baselines(self):
        choices = [(True,'KEEP'), (True,'KEEP'), (False,'WITHDRAW'), (False,'WITHDRAW')]
        rows = [dict(correct=c, keep_withdraw=k) for c,k in choices]
        self.assertEqual(monitoring_stats(rows)['wd'], 100.)
        for decision in ('KEEP', 'WITHDRAW'):
            uniform = [dict(r, keep_withdraw=decision) for r in rows]
            self.assertEqual(monitoring_stats(uniform)['wd'], 0.)

    def test_floor_and_ceiling_delta_stay_undefined(self):
        for correct in (True, False):
            self.assertIsNone(monitoring_stats([dict(correct=correct, keep_withdraw='KEEP')])['wd'])

    def test_unknown_outcome_and_invalid_decision_are_not_scored_as_failure(self):
        for r in (dict(correct=None,keep_withdraw='KEEP'), dict(correct=1,keep_withdraw='KEEP'),
                  dict(correct=True,keep_withdraw='UNRESOLVED')):
            with self.assertRaises(ValueError): monitoring_stats([r])
        with self.assertRaises(ValueError): monitoring_stats([])

    def events(self):
        return [dict(seq=i, event_id=f'e{i}', run_id='one', agent_id='local', turn_id=turn,
                     type=kind, payload=payload) for i,(kind,turn,payload) in enumerate([
                         ('run_start',None,{}), ('turn_start','t1',{}),
                         ('body_decision','t1',{'choice':'defer'}),
                         ('turn_end','t1',{'status':'completed'}),
                         ('run_end',None,{'status':'completed'})],1)]

    def test_actual_roborsi_projection_counts_once_and_has_no_invented_cost(self):
        events = self.events(); saved = deepcopy(events)
        p = project_trajectory(events)
        self.assertEqual(p, project_trajectory(events+[events[-1]]))
        self.assertEqual(p['summary']['n_turns'], 1)
        self.assertEqual(p['summary']['n_requests'], 0)
        self.assertIsNone(p['summary']['usage']['cost_usd'])
        self.assertEqual(events, saved)

    def test_conflicting_event_is_rejected_instead_of_silently_deduplicated(self):
        events = self.events(); changed = deepcopy(events[-1]); changed['payload']['status']='failed'
        with self.assertRaisesRegex(ValueError,'conflicting duplicate'):
            project_trajectory(events+[changed])

    def test_changed_run_or_out_of_order_event_rejected(self):
        for key,value in [('run_id','other'),('seq',1)]:
            events=self.events(); events[-1][key]=value
            with self.assertRaises(ValueError): project_trajectory(events)

    def test_model_usage_or_unknown_events_cannot_be_fabricated(self):
        events=self.events(); events[2]['type']='model_attempt_end'
        with self.assertRaises(ValueError): project_trajectory(events)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'optional CPU tensor environment is not installed')
class TensorChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
        from examples.nasuraya_self_model.evaluate import prepare_defaults
        prepare_defaults()

    def body(self):
        from examples.nasuraya_self_model.evaluate import fixture
        return fixture(.42)

    def test_mjlab_coordinate_conversion_has_independent_known_rotation(self):
        from examples.nasuraya_self_model.monitor import UnifiedBody
        body=self.body(); before=body.checkpoint()
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('unexpected native cycle')):
            result=geometry(body, 1.5707963267948966)
        # Native left foot is +X; in a frame yawed +90 degrees it is -Y.
        self.assertAlmostEqual(result['feet_frame_m'][0][0],0.,places=12)
        self.assertAlmostEqual(result['feet_frame_m'][0][1],-.196,places=12)
        self.assertLess(result['max_roundtrip_error_m'],1e-12)
        self.assertEqual(before,body.checkpoint())

    def test_invalid_frame_yaw_rejected(self):
        for yaw in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError): geometry(self.body(),yaw)

    def test_zero_delta_pose_uses_mjlab_fix_without_nan(self):
        import torch
        from .vendor.mjlab_math import apply_delta_pose
        p=torch.tensor([[1.,2.,3.]]);q=torch.tensor([[1.,0.,0.,0.]])
        a,b=apply_delta_pose(p,q,torch.zeros(1,6))
        self.assertTrue(torch.equal(a,p) and torch.equal(b,q))

    def test_sensory_sample_has_no_future_label_and_cannot_advance_body(self):
        from examples.nasuraya_self_model.monitor import UnifiedBody
        body=self.body();before=body.checkpoint()
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native cycle')):
            sample=sensory_sample(body)
        self.assertEqual(set(sample),{'q','v','source'})
        self.assertEqual(sample['q'][4],.42)
        self.assertEqual(before,body.checkpoint())

    def test_predvla_training_and_latent_inference_have_no_actuation(self):
        from .predictive import train_observer, infer_observer, weight_state
        from examples.nasuraya_self_model.monitor import UnifiedBody
        sample=sensory_sample(self.body()); sequence=[sample]*4
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native cycle')):
            model,training=train_observer([sequence],seed=17,steps=2)
            before=digest(weight_state(model))
            report=infer_observer(model,sequence,iterations=2)
        self.assertTrue(report['weights_unchanged'])
        self.assertFalse(report['upstream_action_output_used'])
        self.assertEqual(report['native_actions_executed'],0)
        self.assertEqual(before,digest(weight_state(model)))
        self.assertEqual(training['action_loss_weight'],0.)

    def test_fixed_seed_model_training_is_reproducible(self):
        from .predictive import train_observer
        sample=sensory_sample(self.body())
        _,a=train_observer([[sample]],seed=31,steps=1)
        _,b=train_observer([[sample]],seed=31,steps=1)
        self.assertEqual(a,b)

    def test_json_weight_restore_preserves_inference_and_rejects_damage(self):
        from .predictive import config, train_observer, infer_observer, weight_state, restore_observer
        sample=sensory_sample(self.body()); sequence=[sample]
        model,training=train_observer([sequence],seed=53,steps=1)
        saved=json.loads(json.dumps(dict(config=config(),state=weight_state(model),training=training)))
        restored=restore_observer(saved)
        self.assertEqual(infer_observer(model,sequence,iterations=1),
                         infer_observer(restored,sequence,iterations=1))
        saved['state'][next(iter(saved['state']))]=[]
        with self.assertRaises(ValueError):restore_observer(saved)

    def test_predictive_limits_and_invalid_sensor_values(self):
        from .predictive import train_observer,tensors
        sample=sensory_sample(self.body())
        for steps in (0,65,True):
            with self.assertRaises(ValueError): train_observer([[sample]],seed=1,steps=steps)
        sample['q'][0]=float('nan')
        with self.assertRaises(ValueError):tensors([[sample]])


if __name__ == '__main__':
    unittest.main()
