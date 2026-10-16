from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

NATIVE=Path(__file__).resolve().parents[2]/'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06'
sys.path.insert(0,str(NATIVE))
from posture_step import PostureLoop,GaitEnvironment,Inputs,checksum
from coordinated_support import CoordinatedSupport
from economical_support import EconomicalSupport,checkpoint,restore


class EconomicalChecks(unittest.TestCase):
    def test_single_owner_clock_and_fuel_debit(self):
        b=EconomicalSupport()
        before=b.body.state.fuel_J
        f=b.step(GaitEnvironment(body=Inputs(dt_s=.1),external_impulse_N_s=[2.,0.]))
        self.assertEqual(b.body.state.time_s,.1)
        self.assertAlmostEqual(before-b.body.state.fuel_J,f['ledger']['fuel_used_J'],places=8)
        self.assertEqual(f['posture']['economical_governor']['candidate_probes'],5)

    def test_exact_cold_continuation(self):
        b=EconomicalSupport()
        b.step(GaitEnvironment(body=Inputs(dt_s=.1),external_impulse_N_s=[2.,0.]))
        saved=json.loads(json.dumps(checkpoint(b)))
        c=restore(deepcopy(saved))
        self.assertEqual(json.loads(json.dumps(checkpoint(c))),saved)
        e=GaitEnvironment(body=Inputs(dt_s=.1))
        self.assertEqual(b.step(e),c.step(e))
        self.assertEqual(checkpoint(b),checkpoint(c))

    def test_checksum_source_and_policy_reject(self):
        original=checkpoint(EconomicalSupport())
        for key,value in [('source','wrong'),('policy',{})]:
            modified=deepcopy(original)
            modified['payload'][key]=value
            modified['sha256']=checksum(modified['payload'])
            with self.assertRaises(ValueError):restore(modified)

    def test_real_zero_friction_failure_remains(self):
        e=GaitEnvironment(body=Inputs(dt_s=.1),friction={'L':0.,'R':0.},external_impulse_N_s=[2.,0.])
        a,b=CoordinatedSupport(),EconomicalSupport()
        fa,fb=a.step(e),b.step(e)
        self.assertFalse(fb['balance']['model_valid'])
        self.assertEqual(fa['posture']['failed_reason'],fb['posture']['failed_reason'])
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_walk_uses_existing_controller(self):
        a,b=CoordinatedSupport(),EconomicalSupport()
        e=GaitEnvironment(body=Inputs(dt_s=.1),command='walk')
        self.assertEqual(a.step(e),b.step(e))
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_invalid_input_rejects_without_mutation(self):
        b=EconomicalSupport();before=b.checkpoint()
        with self.assertRaises(ValueError):
            b.step(GaitEnvironment(body=Inputs(dt_s=.1),friction={'L':float('nan'),'R':.6}))
        self.assertEqual(b.checkpoint(),before)


if __name__=='__main__':unittest.main()
