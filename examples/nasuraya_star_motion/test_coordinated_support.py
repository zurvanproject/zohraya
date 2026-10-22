import os
import sys
from pathlib import Path
import json
import unittest
from copy import deepcopy

sys.path.insert(0,os.environ['NASURAYA_NATIVE_ROOT'])
from unified_body_v2 import UnifiedBody
from persistent_embodiment_v1 import digest
from extension_state import attach,checkpoint,restore


class CoordinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=json.loads(Path(os.environ['NASURAYA_FAILURE_FIXTURE']).read_text())

    def body(self,improved=True):
        b=UnifiedBody.restore(self.source['body'])
        if improved:attach(b,self.source['controller'])
        return b

    def advance(self,b,*,friction=.6,event=None):
        return b.cycle(event_id=event or self.source['next_event_id'],
            at_utc=self.source['next_at_utc'],duration_s=1.,requested='walk',expected_revision=b.revision,
            external=dict(native=dict(upper_targets=dict(shoulder_L=.35,shoulder_R=.35,elbow_L=1.2,elbow_R=1.2,head_pitch=-.1,head_yaw=0.),friction=dict(L=friction,R=friction)),
                sensors=dict(vision=dict(value=.25,source_id='authored-star-floor-40',sampled_at_s=b.owner.owner.body.state.time_s,kind='declared_simulated_input'))))

    def test_recorded_failure_and_corrected_transition(self):
        a=self.body(False);old=self.advance(a)
        b=self.body();new=self.advance(b)
        self.assertFalse(old['owner']['physical_model_valid'])
        self.assertTrue(new['owner']['physical_model_valid'])
        self.assertGreater(b.owner.physical.support_adjustments,0)
        self.assertGreaterEqual(b.owner.physical.last['contact']['joint_support_fraction'],.999)
        self.assertEqual(b.owner.physical.state.walk_steps,3)

    def test_native_stocks_not_reset_on_attach(self):
        b=self.body(False);native=b.checkpoint();attach(b,self.source['controller'])
        self.assertEqual(b.checkpoint(),native)

    def test_cold_restore_preserves_controller_and_outcome(self):
        a=self.body();b=restore(json.loads(json.dumps(checkpoint(a))))
        self.assertEqual(self.advance(a),self.advance(b))
        self.assertEqual(checkpoint(a),checkpoint(b))

    def test_corruption_and_source_mismatch_rejected(self):
        e=checkpoint(self.body());e['payload']['controller']['star_started']['L']=99
        with self.assertRaises(ValueError):restore(e)
        e=checkpoint(self.body());e['payload']['sources']['coordinated_support.py']='altered';e['sha256']=digest(e['payload'])
        with self.assertRaises(ValueError):restore(e)

    def test_zero_friction_is_not_turned_into_success(self):
        b=self.body();r=self.advance(b,friction=0)
        self.assertFalse(r['owner']['physical_model_valid'])
        self.assertEqual(b.owner.physical.state.failed_reason,'friction_limit_exceeded')

    def test_replay_does_not_move_or_charge_twice(self):
        b=self.body();first=self.advance(b);saved=checkpoint(b)
        again=b.cycle(event_id=self.source['next_event_id'],at_utc=self.source['next_at_utc'],duration_s=1.,requested='walk',expected_revision=self.source['body']['payload']['revision'],
            external=dict(native=dict(upper_targets=dict(shoulder_L=.35,shoulder_R=.35,elbow_L=1.2,elbow_R=1.2,head_pitch=-.1,head_yaw=0.),friction=dict(L=.6,R=.6)),sensors=dict(vision=dict(value=.25,source_id='authored-star-floor-40',sampled_at_s=self.body(False).owner.owner.body.state.time_s,kind='declared_simulated_input'))))
        self.assertEqual(first,again);self.assertEqual(checkpoint(b),saved)

    def test_prediction_clones_do_not_advance_or_charge_the_owner(self):
        b=self.body();time=b.owner.owner.body.state.time_s;fuel=b.owner.owner.body.state.fuel_J
        r=self.advance(b)
        self.assertAlmostEqual(b.owner.owner.body.state.time_s-time,1.)
        self.assertEqual(r['owner_ticks'],10)
        self.assertEqual(len(r['trace']),10)
        self.assertAlmostEqual(fuel-b.owner.owner.body.state.fuel_J,sum(x['fuel_used_J'] for x in r['trace']),places=6)
        self.assertLess(r['whole_body_audit']['energy_error_J'],5e-5)
        self.assertLess(r['whole_body_audit']['water_error_L'],1e-8)


if __name__=='__main__':unittest.main()
