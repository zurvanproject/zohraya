"""External conservation checks using output quantities, not renal methods."""
from copy import deepcopy


class SoluteAudit:
    def __init__(self, initial, *, ATP_price_J_mmol=50.):
        self.initial = deepcopy(initial)
        self.ATP_price = ATP_price_J_mmol
        self.sodium_in = self.sodium_out = self.waste_in = self.waste_out = 0.
        self.frames = 0
        self.max_errors = dict(sodium_mmol=0., waste_mOsm=0., urine_osmoles_mOsm=0., pump_J=0.)

    def frame(self, renal, body_frame=None):
        s = renal['state']; l = renal['ledger']; o = self.initial
        self.frames += 1
        self.sodium_in += l['sodium_input_mmol']; self.sodium_out += l['sodium_urine_mmol'] + l['sodium_sweat_mmol']
        self.waste_in += l['waste_input_mOsm'] + l['waste_generated_mOsm']; self.waste_out += l['waste_urine_mOsm']
        na_error = abs(o['sodium_free_mmol'] + o['sodium_bound_mmol'] + self.sodium_in -
            s['sodium_free_mmol'] - s['sodium_bound_mmol'] - self.sodium_out)
        w_error = abs(o['waste_free_mOsm'] + o['waste_bound_mOsm'] + self.waste_in -
            s['waste_free_mOsm'] - s['waste_bound_mOsm'] - self.waste_out)
        urine = l['urine_water_L']; concentration = l['actual_urine_osmolarity_mOsm_L']
        osm_error = abs(2.*l['sodium_urine_mmol'] + l['waste_urine_mOsm'] - urine*(concentration or 0.))
        pump_error = abs(l['pump_actual_J'] - l['pump_requested_J']*renal['transport_paid_fraction'])
        for k, v in dict(sodium_mmol=na_error, waste_mOsm=w_error, urine_osmoles_mOsm=osm_error, pump_J=pump_error).items():
            self.max_errors[k] = max(self.max_errors[k], v)
            assert v < 1e-6, (k, self.frames, v)
        assert 0 <= urine <= l['filtration_L'] + 1e-10
        assert l['pump_actual_J'] + 1e-10 >= l['sodium_reabsorbed_mmol']/3.*self.ATP_price, 'unpriced sodium transport'
        if body_frame:
            assert abs(body_frame['ledger']['urine_loss_L'] - urine) < 1e-12
            assert abs(body_frame['ledger']['renal_energy_included_in_fuel_J'] - l['pump_actual_J']) < 1e-10
            assert body_frame['ledger']['fuel_used_J'] + 1e-10 >= l['pump_actual_J']

    def result(self):
        return dict(passed=True, frames=self.frames, max_errors=self.max_errors,
            sodium_excreted_mmol=self.sodium_out, waste_excreted_mOsm=self.waste_out)
