"""Observer contracts on isolated, source-verified main-body fixtures."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from .body_observer import observe_native_body
from .adapters import geometry, sensory_sample


class ObserverContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.nasuraya_body_loop.__main__ import SOURCE, verified_sources
        cls.temp = tempfile.TemporaryDirectory(prefix='research-native-')
        cls.native = Path(cls.temp.name)
        for name in verified_sources():
            target = cls.native / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        sys.path.insert(0, str(cls.native))
        from synthetic_fixture import prepare_defaults
        prepare_defaults()  # generated defaults only inside this temporary tree

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(cls.native))
        for name, module in list(sys.modules.items()):
            file = getattr(module, '__file__', None)
            if file and Path(file).resolve().is_relative_to(cls.native):
                del sys.modules[name]
        cls.temp.cleanup()

    def body(self, pressure=.5):
        from synthetic_fixture import synthetic_body
        body = synthetic_body()
        before = body.owner.body()
        body.owner.aux['sleep_pressure'] = pressure
        body.owner._record(before, body.owner.body(), 'external_input',
                           'declared self-efficacy evaluation fixture; no user state reset', 0.)
        return body

    def test_reads_native_fixture_without_mutation_or_execution(self):
        from unified_body_v2 import UnifiedBody
        from persistent_embodiment_v1 import PersistentEmbodiment
        body = self.body(); before = deepcopy(body.checkpoint())
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native cycle')), \
             patch.object(PersistentEmbodiment, 'cycle', side_effect=AssertionError('owner cycle')), \
             patch.object(socket, 'socket', side_effect=AssertionError('network')):
            observed = observe_native_body(body)
        self.assertEqual(before, body.checkpoint())
        self.assertEqual(observed['source_checkpoint_sha256'], before['sha256'])
        for field in ('native_cycles_executed', 'action_requests_executed', 'model_api_calls'):
            self.assertEqual(observed[field], 0)
        self.assertEqual(len(observed['sensory']['q']), 6)
        self.assertEqual(len(observed['sensory']['v']), 6)
        self.assertEqual(observed['sensory']['q'][4], .5)

    def test_no_stacked_modules_or_tensor_imported_by_default(self):
        observe_native_body(self.body())
        self.assertFalse(any(name.startswith(('examples.nasuraya_security',
                         'examples.nasuraya_self_model')) for name in sys.modules))
        # Tensor methods may run earlier; stdlib-only subprocess validation is
        # additionally performed by `python -S -m unittest ...`.

    def test_rejects_invalid_decision_evidence_without_body_change(self):
        body = self.body(); before = deepcopy(body.checkpoint())
        with self.assertRaises(ValueError):
            observe_native_body(body, decisions=[{'correct': 'guessed', 'keep_withdraw': 'KEEP'}])
        self.assertEqual(before, body.checkpoint())

    def test_optional_stats_and_trajectory_preserve_body_and_caller_records(self):
        body = self.body(); before = deepcopy(body.checkpoint())
        decisions = [dict(correct=True, keep_withdraw='KEEP'),
                     dict(correct=False, keep_withdraw='WITHDRAW')]
        events = [dict(seq=1, event_id='one', run_id='run', type='run_start', payload={})]
        saved = deepcopy((decisions, events))
        result = observe_native_body(body, decisions=decisions, events=events)
        self.assertEqual(result['monitoring']['wd'], 100.)
        self.assertEqual(result['trajectory']['summary']['n_turns'], 0)
        self.assertEqual(before, body.checkpoint())
        self.assertEqual(saved, (decisions, events))

    def test_returned_senses_do_not_alias_body(self):
        body = self.body(); before = deepcopy(body.checkpoint())
        observed = observe_native_body(body)
        observed['sensory']['q'][0] = -999
        observed['sensory']['v'][0] = -999
        self.assertEqual(before, body.checkpoint())

    def test_nonfinite_sense_is_rejected(self):
        body = self.body()
        body.owner.physical.state.feet_m['L'][0] = float('nan')
        with self.assertRaises((ValueError, RuntimeError)):
            observe_native_body(body)

    def test_checkpoint_tampering_is_rejected(self):
        body = self.body(); broken = deepcopy(body.checkpoint()); broken['sha256'] = '0'*64
        with patch.object(body, 'checkpoint', return_value=broken):
            with self.assertRaises(ValueError): observe_native_body(body)

    def test_mutation_is_detected_on_success(self):
        body = self.body()
        def mutate(_):
            body.revision += 1
            return {}
        with patch('examples.nasuraya_research.body_observer.sensory_sample', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'changed canonical'):
                observe_native_body(body)

    def test_mutation_is_detected_when_adapter_raises(self):
        body = self.body()
        def mutate(_):
            body.revision += 1
            raise ValueError('adapter failed')
        with patch('examples.nasuraya_research.body_observer.sensory_sample', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'changed canonical'):
                observe_native_body(body)

    def test_missing_optional_geometry_dependency_has_no_fallback_or_body_change(self):
        import builtins
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name == 'torch': raise ModuleNotFoundError('optional torch unavailable')
            return original(name, *args, **kwargs)
        body = self.body(); before = deepcopy(body.checkpoint())
        with patch('builtins.__import__', side_effect=blocked):
            with self.assertRaises(ModuleNotFoundError):
                observe_native_body(body, include_geometry=True)
        self.assertEqual(before, body.checkpoint())

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'optional tensor dependencies absent')
    def test_geometry_known_rotation_and_all_options_have_no_authority(self):
        import torch
        torch.set_num_threads(1)
        from unified_body_v2 import UnifiedBody
        body = self.body(.42); before = deepcopy(body.checkpoint())
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native cycle')), \
             patch.object(socket, 'socket', side_effect=AssertionError('network')):
            result = observe_native_body(body, include_geometry=True, frame_yaw_rad=1.5707963267948966,
                decisions=[dict(correct=True, keep_withdraw='KEEP')],
                events=[dict(seq=1, event_id='e', run_id='r', type='run_start', payload={})])
        self.assertAlmostEqual(result['geometry']['feet_frame_m'][0][0], 0., places=12)
        self.assertAlmostEqual(result['geometry']['feet_frame_m'][0][1], -.196, places=12)
        self.assertLess(result['geometry']['max_roundtrip_error_m'], 1e-12)
        self.assertEqual(before, body.checkpoint())

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'optional tensor dependencies absent')
    def test_invalid_geometry_yaws_leave_body_unchanged(self):
        body = self.body(); before = deepcopy(body.checkpoint())
        for yaw in (float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                observe_native_body(body, include_geometry=True, frame_yaw_rad=yaw)
        self.assertEqual(before, body.checkpoint())

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'optional tensor dependencies absent')
    def test_retained_mjlab_zero_delta_pose_is_finite(self):
        import torch
        from .vendor.mjlab_math import apply_delta_pose
        p=torch.tensor([[1.,2.,3.]]); q=torch.tensor([[1.,0.,0.,0.]])
        a,b=apply_delta_pose(p,q,torch.zeros(1,6))
        self.assertTrue(torch.equal(a,p) and torch.equal(b,q))


if __name__ == '__main__':
    unittest.main()
