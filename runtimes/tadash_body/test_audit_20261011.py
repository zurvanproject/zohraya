"""Regression and causal probes; synthetic fixtures are never canonical state."""
import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from unified_body_v2 import UnifiedBody, ROOT, instant

from synthetic_fixture import synthetic_body
BASE = synthetic_body()

def advance(b, external=None, requested='observe', duration=.1):
    return b.cycle(event_id='audit-test-'+str(b.revision),
        at_utc=(instant(b.owner.wall_utc)+timedelta(seconds=duration)).isoformat(),
        duration_s=duration,external=external or {},requested=requested)

def sample(value, t, source='audit'):
    return dict(value=value,source_id=source,sampled_at_s=t,kind='declared_simulated_input')

class AuditChecks(unittest.TestCase):
    def test_zero_lung_capacity_stops_both_exchange_fluxes(self):
        b=copy.deepcopy(BASE);advance(b,{'capacities':{'lung':0.}})
        led=b.owner.physical.last['respiration']['ledger']
        self.assertEqual(led['uptake_L'],0.)
        self.assertEqual(led['cleared_co2_L'],0.)
        self.assertGreater(led['consumed_o2_L'],0.)

    def test_reduced_lung_capacity_reduces_both_fluxes(self):
        a,b=copy.deepcopy(BASE),copy.deepcopy(BASE)
        advance(a);advance(b,{'capacities':{'lung':.2}})
        x=a.owner.physical.last['respiration']['ledger'];y=b.owner.physical.last['respiration']['ledger']
        self.assertGreater(x['uptake_L'],y['uptake_L'])
        self.assertGreater(x['cleared_co2_L'],y['cleared_co2_L'])

    def test_recovered_lung_restores_exchange_without_double_capacity_debit(self):
        b=copy.deepcopy(BASE);advance(b,{'capacities':{'lung':0.}});advance(b)
        self.assertGreater(b.owner.physical.last['respiration']['ledger']['uptake_L'],0.)
        self.assertEqual(b.owner.physical.last['respiration']['exchange_capacity_proxy'],1.)

    def test_older_sample_rejected_without_any_mutation(self):
        b=copy.deepcopy(BASE);t=b.owner.owner.body.state.time_s
        advance(b,{'sensors':{'hearing':sample(.2,t)}});before=b.checkpoint()
        with self.assertRaisesRegex(ValueError,'out-of-order'):
            advance(b,{'sensors':{'hearing':sample(.9,t-1)}})
        self.assertEqual(b.checkpoint(),before)

    def test_same_time_conflict_rejected_without_mutation(self):
        b=copy.deepcopy(BASE);t=b.owner.owner.body.state.time_s
        advance(b,{'sensors':{'touch':sample(.2,t)}});before=b.checkpoint()
        with self.assertRaisesRegex(ValueError,'contradictory'):
            advance(b,{'sensors':{'touch':sample(.9,t)}})
        self.assertEqual(b.checkpoint(),before)

    def test_newer_measurement_updates_channel(self):
        b=copy.deepcopy(BASE);t=b.owner.owner.body.state.time_s
        advance(b,{'sensors':{'hearing':sample(.2,t)}})
        advance(b,{'sensors':{'hearing':sample(.9,b.owner.owner.body.state.time_s)}})
        self.assertEqual(b.modules['senses']['samples']['hearing']['value'],.9)

    def test_swallow_excludes_phonation(self):
        b=copy.deepcopy(BASE);advance(b,{'meal_J':10000,'voice_request':True})
        self.assertGreater(b.modules['gut']['stomach_J'],0.)
        self.assertEqual(b.modules['mouth']['phonation'],0.)

    def test_voice_available_when_not_swallowing(self):
        b=copy.deepcopy(BASE);advance(b,{'voice_request':True})
        self.assertGreater(b.modules['mouth']['phonation'],0.)

    def test_zero_airway_has_no_exchange(self):
        b=copy.deepcopy(BASE);advance(b,{'native':{'airway_capacity':0.}})
        f=b.owner.physical.last['respiration']
        self.assertEqual(f['alveolar_ventilation_L_min'],0.)
        self.assertEqual(f['ledger']['uptake_L'],0.)

    def test_prediction_is_locked_before_unexpected_impulse(self):
        a,b=copy.deepcopy(BASE),copy.deepcopy(BASE)
        x=advance(a);y=advance(b,{'native':{'unexpected_impulse_N_s':[10.,0.]}})
        self.assertEqual(x['owner']['prediction']['predicted'],y['owner']['prediction']['predicted'])
        self.assertNotEqual(x['owner']['prediction']['actual'],y['owner']['prediction']['actual'])
        self.assertGreater(y['owner']['prediction']['mean_scaled_absolute_error'],0.)

    def test_current_fatigue_and_sleep_veto_walking(self):
        b=copy.deepcopy(BASE)
        b.owner.aux['sleep_pressure']=.95
        for channel in b.owner.owner.body.state.fatigue:
            b.owner.owner.body.state.fatigue[channel]=.9
        r=advance(b,requested='walk')
        self.assertNotEqual(r['owner']['selected_action'],'walk')

    def test_patched_source_checkpoint_resumes_exactly(self):
        a=copy.deepcopy(BASE);advance(a)
        b=UnifiedBody.restore(json.loads(json.dumps(a.checkpoint())))
        self.assertEqual(advance(a),advance(b))

if __name__=='__main__':unittest.main(verbosity=2)
