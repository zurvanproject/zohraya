"""Bounded native safety regressions; no paid service or fixture tuning."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .adaptive_memory import AdaptiveMemory, initial_model
from .closed_loop_benchmark import fixture, start_from
from .host import BodyLoop
from .native_preflight import preview
from .self_maintenance import MaintenanceBlocked

CASE = {'id': 'native-guard-regression', 'sleep_pressure': .2,
        'muscle_tone': .3, 'warmup_walks': 0}
PAIN = {'id': 'known-pain', 'location': 'forefoot_L', 'intensity': .8,
        'quality': 'pressure', 'cause': 'declared synthetic regression', 'duration_s': 10.}


def known_pain_body():
    body = fixture(CASE)
    # Declared input using the retained ingestion routine, before any action.
    # This fixture is not a measured sensor reading or an unknown future input.
    body.owner._external({'pain': [deepcopy(PAIN)]})
    return body


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'body.sqlite'

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_preview_is_repeatable_and_does_not_mutate_source(self):
        body = fixture(CASE)
        before = body.checkpoint()
        for action in ('walk', 'observe'):
            p = preview(body, action)
            self.assertEqual(p, preview(body, action))
            self.assertTrue(p['physical_model_valid'])
            self.assertFalse(p['eligible_for_learning'])
            self.assertFalse(p['future_unobserved_inputs_covered'])
            self.assertEqual(body.checkpoint(), before)

    def test_known_pain_both_actions_predict_joint_guard_not_energy_shortage(self):
        body = known_pain_body()
        self.assertNotEqual(body.owner.physical.state.phase, 'failed')
        for action in ('walk', 'observe'):
            p = preview(body, action)
            self.assertFalse(p['physical_model_valid'])
            self.assertEqual(p['failed_reason'], 'insufficient_joint_or_energy_support')
            self.assertEqual(p['postural_allocation_fraction'], 1.)
            self.assertEqual(p['joint_support_fraction'], 0.)
            self.assertEqual(set(p['deficient_channels']), {'hip_L', 'knee_L', 'ankle_L'})
            self.assertTrue(all(v['predicted_N'] == v['hazard_cap'] == 0.
                                for v in p['deficient_channels'].values()))

    def test_refusal_retains_budget_model_identity_and_survives_real_restart(self):
        with start_from(self.path, known_pain_body()) as loop:
            m = AdaptiveMemory(loop)
            before = loop.status()
            with self.assertRaisesRegex(MaintenanceBlocked, 'preflight predicts'):
                m.execute('guarded', 'observe')
            self.assertEqual(loop.status(), before)
            self.assertEqual(m.verify(), (1, initial_model()))
            self.assertEqual(loop.engine.get('guarded'), None)
            self.assertEqual(m.db.execute('SELECT COUNT(*) FROM nasu_experiences').fetchone()[0], 0)
        code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.adaptive_memory import AdaptiveMemory
from examples.nasuraya_body_loop.self_maintenance import MaintenanceBlocked
with BodyLoop(sys.argv[1]) as loop:
 m=AdaptiveMemory(loop)
 try: m.execute('guarded','observe')
 except MaintenanceBlocked as e:
  print(json.dumps({'reason':str(e),'remaining':loop.status()['actions_remaining'],'version':m.verify()[0],'cycles':loop.status()['completed_cycles'],'refusals':m.db.execute('SELECT COUNT(*) FROM nasu_preflight_refusals').fetchone()[0]}))
 else: raise AssertionError('refused action executed after restart')
'''
        p = subprocess.run([sys.executable, '-c', code, str(self.path)], capture_output=True,
                           text=True, timeout=60, check=True)
        r = json.loads(p.stdout)
        self.assertEqual((r['remaining'], r['version'], r['cycles'], r['refusals']), (3, 1, 0, 1))

    def test_corrupt_refusal_blocks_before_new_action(self):
        with start_from(self.path, known_pain_body()) as loop:
            m = AdaptiveMemory(loop)
            with self.assertRaises(MaintenanceBlocked): m.execute('bad', 'observe')
            m.db.execute("UPDATE nasu_preflight_refusals SET record='{}'")
            with self.assertRaisesRegex(MaintenanceBlocked, 'corrupt preflight'):
                m.execute('other', 'observe')
            self.assertEqual(loop.status()['completed_cycles'], 0)

    def test_conflicting_refusal_replay_is_rejected(self):
        with start_from(self.path, known_pain_body()) as loop:
            m = AdaptiveMemory(loop)
            with self.assertRaises(MaintenanceBlocked): m.execute('same', 'walk')
            with self.assertRaisesRegex(MaintenanceBlocked, 'conflicting preflight'):
                m.execute('same', 'observe')
            self.assertEqual(loop.status()['actions_remaining'], 3)

    def test_successful_preview_is_not_a_learning_episode(self):
        with BodyLoop.start(self.path, max_actions=3) as loop:
            m = AdaptiveMemory(loop)
            before = loop.status()
            preview(loop.body(), 'observe')
            self.assertEqual(loop.status(), before)
            self.assertEqual(m.verify(), (1, initial_model()))
            result = m.execute('actual', 'observe')
            self.assertTrue(result['learned'])
            self.assertEqual(m.verify()[0], 2)
            self.assertEqual(loop.status()['completed_cycles'], 1)
            raw = m.db.execute('SELECT intent FROM nasu_experiences').fetchone()[0]
            self.assertFalse(json.loads(raw)['native_preflight']['eligible_for_learning'])

    def test_bad_preview_provenance_cannot_authorize_an_action(self):
        with BodyLoop.start(self.path, max_actions=3) as loop:
            m = AdaptiveMemory(loop)
            p = preview(loop.body(), 'observe')
            p['before_sha'] = '0' * 64
            with patch('examples.nasuraya_body_loop.adaptive_memory.native_preview', return_value=p):
                with self.assertRaisesRegex(MaintenanceBlocked, 'provenance'):
                    m.execute('mismatch', 'observe')
            self.assertEqual(loop.status()['completed_cycles'], 0)

    def test_preview_cannot_predict_an_unobserved_future_disturbance(self):
        body = fixture(CASE)
        self.assertTrue(preview(body, 'observe')['physical_model_valid'])
        at = (datetime.fromisoformat(body.owner.wall_utc) + timedelta(seconds=.1)).isoformat()
        r = body.cycle(event_id='surprise', at_utc=at, duration_s=.1, requested='observe',
                       external={'native': {'pain': [deepcopy(PAIN)]}})
        self.assertFalse(r['owner']['physical_model_valid'])

    def test_unauthorized_actions_are_rejected(self):
        with self.assertRaises(ValueError): preview(fixture(CASE), 'single_R')


if __name__ == '__main__':
    unittest.main()
