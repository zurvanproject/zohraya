from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

NATIVE=Path(__file__).resolve().parents[2]/'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06'
sys.path.insert(0,str(NATIVE))
from posture_step import GaitEnvironment,Inputs,checksum
from coordinated_support import CoordinatedSupport
from horizon_support import HorizonSupport,rollout,checkpoint,restore,POLICY


class HorizonChecks(unittest.TestCase):
    def test_future_does_not_repeat_impulse_or_change_owner(self):
        b=HorizonSupport();before=b.checkpoint();seen=[]
        original=CoordinatedSupport.step
        def observed(owner,e):
            seen.append(list(e.external_impulse_N_s))
            return original(owner,e)
        with patch.object(CoordinatedSupport,'step',observed):
            trial,frames=rollout(b,GaitEnvironment(body=Inputs(dt_s=.1),external_impulse_N_s=[2.,0.]),None)
        self.assertEqual(seen,[[2.,0.]]+[[0.,0.]]*(POLICY['horizon_ticks']-1))
        self.assertEqual(b.checkpoint(),before)
        self.assertAlmostEqual(trial.state.time_s,POLICY['horizon_ticks']*.1)

    def test_actual_tick_charged_once(self):
        b=HorizonSupport();fuel=b.body.state.fuel_J
        f=b.step(GaitEnvironment(body=Inputs(dt_s=.1),external_impulse_N_s=[2.,0.]))
        self.assertEqual(b.state.time_s,.1)
        self.assertAlmostEqual(fuel-b.body.state.fuel_J,f['ledger']['fuel_used_J'],places=8)
        self.assertEqual(f['posture']['horizon_governor']['horizon_ticks'],6)

    def test_json_cold_resume_same_next_action_and_state(self):
        b=HorizonSupport();b.step(GaitEnvironment(body=Inputs(dt_s=.1),external_impulse_N_s=[2.,0.]))
        saved=json.loads(json.dumps(checkpoint(b)));c=restore(saved)
        self.assertEqual(json.loads(json.dumps(checkpoint(c))),saved)
        e=GaitEnvironment(body=Inputs(dt_s=.1))
        self.assertEqual(b.step(e),c.step(e))
        self.assertEqual(checkpoint(b),checkpoint(c))

    def test_walk_and_quiet_stand_match_existing_controller(self):
        for command in ('stand','walk'):
            a,b=CoordinatedSupport(),HorizonSupport();e=GaitEnvironment(body=Inputs(dt_s=.1),command=command)
            self.assertEqual(a.step(e),b.step(e));self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_zero_friction_failure_not_hidden(self):
        a,b=CoordinatedSupport(),HorizonSupport()
        e=GaitEnvironment(body=Inputs(dt_s=.1),friction={'L':0.,'R':0.},external_impulse_N_s=[2.,0.])
        fa,fb=a.step(e),b.step(e)
        self.assertFalse(fb['balance']['model_valid'])
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_source_and_policy_tampering_rejected(self):
        saved=checkpoint(HorizonSupport())
        for key,value in [('sources',{}),('policy',{})]:
            modified=deepcopy(saved);modified['payload'][key]=value
            modified['sha256']=checksum(modified['payload'])
            with self.assertRaises(ValueError):restore(modified)


if __name__=='__main__':unittest.main()
