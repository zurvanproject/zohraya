"""Conservative one-pool renal design fixture; NOT plasma or a fitted nephron.

Water belongs to the existing body. This object owns only new, explicitly
initialized sodium-equivalent and neutral-waste osmoles. Sodium includes an
equal paired-anion equivalent (2 mOsm/mmol); potassium and acid-base are absent.
Camel urine measurements are comparative envelope anchors, not a capacity
measurement for Tadash. ATP price, GFR, thresholds and controller timing are
declared design assumptions. Water channels themselves are passive.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'tadash-renal-solutes/0.9'


def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, allow_nan=False).encode()).hexdigest()


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def number(v, name, lo=0., hi=1e12):
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(name + ': finite value outside allowed bounds')
    return float(v)


def unit(v):
    return min(1., max(0., v))


@dataclass(frozen=True)
class RenalInputs:
    sodium_intake_mmol_s: float = 0.
    neutral_waste_intake_mOsm_s: float = 0.
    perfusion_factor: float = 1.

    def validate(self):
        number(self.sodium_intake_mmol_s, 'sodium intake', 0., 1.)
        number(self.neutral_waste_intake_mOsm_s, 'waste intake', 0., 1.)
        number(self.perfusion_factor, 'renal perfusion', 0., 1.)


@dataclass(frozen=True)
class Parameters:
    reference_water_L: float = 110.
    initial_sodium_mmol_L: float = 140.
    initial_waste_mOsm_L: float = 10.
    filtration_reference_L_s: float = .002
    waste_filtered_excretion_fraction: float = .6
    basal_sodium_leak_mmol_s: float = .0005
    sodium_feedback_tau_s: float = 86400.
    water_signal_tau_s: float = 30.
    baseline_urine_anchor_mOsm_L: float = 952.
    concentrated_urine_anchor_mOsm_L: float = 1963.
    sweat_sodium_mmol_L: float = 35.
    waste_generated_mOsm_J: float = .012 / 220.
    ATP_price_J_mmol: float = 50.
    sodium_per_ATP: float = 3.
    camel_envelope_enabled: bool = True

    def validate(self):
        for k, v in asdict(self).items():
            if k == 'camel_envelope_enabled':
                if type(v) is not bool: raise ValueError('concentration mode must be bool')
            else:
                number(v, k, 0., 1e6)
        for k in ('reference_water_L', 'sodium_feedback_tau_s', 'water_signal_tau_s', 'sodium_per_ATP',
                  'ATP_price_J_mmol', 'baseline_urine_anchor_mOsm_L'):
            if getattr(self, k) <= 0: raise ValueError('positive parameter required: ' + k)
        if not 0 <= self.waste_filtered_excretion_fraction <= 1: raise ValueError('waste fraction')
        if self.concentrated_urine_anchor_mOsm_L < self.baseline_urine_anchor_mOsm_L:
            raise ValueError('concentration anchor order')
        if self.sodium_per_ATP != 3.: raise ValueError('declared sodium-pump stoichiometry must remain three')


class RenalModel:
    def __init__(self, *, time_s=0., water_L=110., parameters=None):
        self.parameters = parameters or Parameters()
        self.parameters.validate()
        number(time_s, 'renal clock'); number(water_L, 'initial free-water pool')
        p = self.parameters
        self.state = dict(time_s=float(time_s), sodium_free_mmol=p.initial_sodium_mmol_L * water_L,
            sodium_bound_mmol=0., waste_free_mOsm=p.initial_waste_mOsm_L * water_L,
            waste_bound_mOsm=0., water_signal=0., ticks=0,
            sodium_input_mmol=0., sodium_urine_mmol=0., sodium_sweat_mmol=0.,
            waste_input_mOsm=0., waste_generated_mOsm=0., waste_urine_mOsm=0.,
            pump_energy_J=0., filtered_L=0.)
        self.origin = deepcopy(self.state)

    def concentrations(self, water_L, state=None):
        number(water_L, 'free water')
        s = state or self.state
        denominator = max(1e-8, water_L)
        sodium = s['sodium_free_mmol'] / denominator
        waste = s['waste_free_mOsm'] / denominator
        return dict(sodium_proxy_mmol_L=sodium, waste_proxy_mOsm_L=waste,
            pool_osmolarity_proxy_mOsm_L=2. * sodium + waste,
            concentrations_are_plasma_measurements=False)

    def guard(self, water_L, state=None):
        c = self.concentrations(water_L, state)
        reasons = []
        if water_L < .8 * self.parameters.reference_water_L: reasons.append('free_water_below_fixture_floor')
        if not 115. <= c['sodium_proxy_mmol_L'] <= 155.: reasons.append('sodium_pool_outside_fixture_bounds')
        if not 245. <= c['pool_osmolarity_proxy_mOsm_L'] <= 325.: reasons.append('osmotic_pool_outside_fixture_bounds')
        if c['waste_proxy_mOsm_L'] > 40.: reasons.append('waste_pool_above_fixture_bound')
        return dict(optional_pause=bool(reasons), reasons=reasons,
            thresholds_are_unvalidated_engineering_choices=True)

    def prepare(self, *, time_s, dt_s, water_L, water_intake_L, flow_ratio,
                oxygen_fraction, inputs=RenalInputs()):
        self.validate()
        number(time_s, 'prepare clock'); number(dt_s, 'renal dt', .05, 60.)
        number(water_L, 'water before'); number(water_intake_L, 'water input')
        number(flow_ratio, 'circulation ratio', 0., 1.)
        number(oxygen_fraction, 'oxygen proxy', 0., 1.)
        if not isinstance(inputs, RenalInputs): raise ValueError('RenalInputs required')
        inputs.validate()
        if abs(time_s - self.state['time_s']) > 1e-8: raise ValueError('renal/body clock mismatch')
        p = self.parameters; s = deepcopy(self.state)
        ni = inputs.sodium_intake_mmol_s * dt_s
        wi = inputs.neutral_waste_intake_mOsm_s * dt_s
        s['sodium_free_mmol'] += ni; s['waste_free_mOsm'] += wi
        water = water_L + water_intake_L
        c = self.concentrations(water, s)
        signal_target = unit(max((1. - water / p.reference_water_L) / .05,
            (c['pool_osmolarity_proxy_mOsm_L'] - 290.) / 30.))
        signal = s['water_signal'] + (signal_target - s['water_signal']) * (1. - math.exp(-dt_s / p.water_signal_tau_s))
        hydration_support = unit(water / p.reference_water_L)
        filtration_L = p.filtration_reference_L_s * dt_s * flow_ratio * inputs.perfusion_factor * oxygen_fraction * hydration_support
        filtered_na = filtration_L * c['sodium_proxy_mmol_L']
        desired_na = dt_s * (p.basal_sodium_leak_mmol_s * unit((c['sodium_proxy_mmol_L'] - 115.) / 25.)
            + max(0., s['sodium_free_mmol'] - p.initial_sodium_mmol_L * water) / p.sodium_feedback_tau_s)
        na_out = min(filtered_na, desired_na)
        waste_out = filtration_L * c['waste_proxy_mOsm_L'] * p.waste_filtered_excretion_fraction
        reabsorbed_na = max(0., filtered_na - na_out)
        # Aggregate sodium-pump equivalent; no extra animal multiplier and no
        # membrane-channel energy benefit credited. Other nephron work is absent.
        pump_J = reabsorbed_na / p.sodium_per_ATP * p.ATP_price_J_mmol
        anchor = p.baseline_urine_anchor_mOsm_L
        if p.camel_envelope_enabled:
            anchor += signal * (p.concentrated_urine_anchor_mOsm_L - anchor)
        plan = dict(time_s=time_s, dt_s=dt_s, water_before_L=water_L, water_after_input_L=water,
            water_input_L=water_intake_L, inputs_flow_ratio=flow_ratio, inputs_oxygen_fraction=oxygen_fraction,
            state_before_sha256=digest(self.state), inputs=asdict(inputs), sodium_input_mmol=ni,
            waste_input_mOsm=wi, concentrations=c, signal_target=signal_target, signal=signal,
            filtration_requested_L=filtration_L, sodium_excretion_requested_mmol=na_out,
            waste_excretion_requested_mOsm=waste_out, sodium_reabsorption_requested_mmol=reabsorbed_na,
            pump_requested_J=pump_J, concentration_anchor_mOsm_L=anchor)
        return dict(payload=plan, sha256=digest(plan))

    def settle(self, plan, *, paid_fraction, water_available_L, water_bound_L=0.,
               evaporated_L=0., fuel_used_J=0.):
        self.validate()
        number(paid_fraction, 'paid transport fraction', 0., 1.)
        for k, v in [('water available', water_available_L), ('bound water', water_bound_L),
                     ('evaporation', evaporated_L), ('fuel consumed', fuel_used_J)]: number(v, k)
        q = deepcopy(plan['payload'])
        if plan['sha256'] != digest(q) or q['state_before_sha256'] != digest(self.state):
            raise ValueError('altered or already consumed renal plan')
        # Recompute the complete plan: a recomputed envelope checksum alone
        # cannot introduce free clearance or change the requested energy.
        expected = self.prepare(time_s=q['time_s'], dt_s=q['dt_s'], water_L=q['water_before_L'],
            water_intake_L=q['water_input_L'],
            flow_ratio=q['inputs_flow_ratio'], oxygen_fraction=q['inputs_oxygen_fraction'],
            inputs=RenalInputs(**q['inputs']))
        if expected != plan: raise ValueError('renal plan differs from current inputs')
        if water_available_L + water_bound_L + evaporated_L > q['water_after_input_L'] + 1e-8:
            raise ValueError('settlement has more water than the prepared body pool')
        p = self.parameters; s = deepcopy(self.state); c = q['concentrations']
        s['sodium_free_mmol'] += q['sodium_input_mmol']; s['sodium_input_mmol'] += q['sodium_input_mmol']
        s['waste_free_mOsm'] += q['waste_input_mOsm']; s['waste_input_mOsm'] += q['waste_input_mOsm']
        bound_na = min(s['sodium_free_mmol'], water_bound_L * c['sodium_proxy_mmol_L'])
        bound_waste = min(s['waste_free_mOsm'], water_bound_L * c['waste_proxy_mOsm_L'])
        s['sodium_free_mmol'] -= bound_na; s['sodium_bound_mmol'] += bound_na
        s['waste_free_mOsm'] -= bound_waste; s['waste_bound_mOsm'] += bound_waste
        sweat_na = min(s['sodium_free_mmol'], evaporated_L * p.sweat_sodium_mmol_L)
        s['sodium_free_mmol'] -= sweat_na; s['sodium_sweat_mmol'] += sweat_na
        generated = fuel_used_J * p.waste_generated_mOsm_J
        s['waste_free_mOsm'] += generated; s['waste_generated_mOsm'] += generated
        filtration = q['filtration_requested_L'] * paid_fraction
        na_out = min(s['sodium_free_mmol'], q['sodium_excretion_requested_mmol'] * paid_fraction)
        waste_out = min(s['waste_free_mOsm'], q['waste_excretion_requested_mOsm'] * paid_fraction)
        pool_before_urine = self.concentrations(water_available_L, s)['pool_osmolarity_proxy_mOsm_L']
        concentration = max(1e-8, pool_before_urine,
            pool_before_urine + (q['concentration_anchor_mOsm_L'] - pool_before_urine) * paid_fraction)
        requested_urine = (2. * na_out + waste_out) / concentration
        urine = min(water_available_L, filtration, requested_urine)
        volume_fraction = min(1., urine / requested_urine) if requested_urine else 1.
        filtration *= volume_fraction
        na_out *= volume_fraction; waste_out *= volume_fraction
        s['sodium_free_mmol'] -= na_out; s['sodium_urine_mmol'] += na_out
        s['waste_free_mOsm'] -= waste_out; s['waste_urine_mOsm'] += waste_out
        pump_J = q['pump_requested_J'] * paid_fraction
        s['pump_energy_J'] += pump_J; s['filtered_L'] += filtration
        s['water_signal'] = q['signal']; s['ticks'] += 1; s['time_s'] += q['dt_s']
        self._validate_state(s)
        self.state = s
        after = self.concentrations(water_available_L - urine)
        return dict(state=deepcopy(s), before=deepcopy(c), after=after,
            guard=self.guard(water_available_L - urine), signal_target=q['signal_target'],
            transport_paid_fraction=paid_fraction,
            ledger=dict(dt_s=q['dt_s'], sodium_input_mmol=q['sodium_input_mmol'],
                sodium_bound_mmol=bound_na, sodium_sweat_mmol=sweat_na, sodium_urine_mmol=na_out,
                waste_input_mOsm=q['waste_input_mOsm'], waste_generated_mOsm=generated,
                waste_bound_mOsm=bound_waste, waste_urine_mOsm=waste_out,
                urine_water_L=urine, filtration_L=filtration,
                sodium_reabsorbed_mmol=q['sodium_reabsorption_requested_mmol']*paid_fraction*volume_fraction,
                unused_paid_pump_allowance_J=q['pump_requested_J']*paid_fraction*(1.-volume_fraction),
                pump_requested_J=q['pump_requested_J'],
                pump_actual_J=pump_J, transport_shortfall_J=q['pump_requested_J']-pump_J,
                actual_urine_osmolarity_mOsm_L=(2.*na_out+waste_out)/urine if urine else None,
                filtration_is_internal_not_a_water_loss=True),
            concentration_anchor_mOsm_L=q['concentration_anchor_mOsm_L'],
            camel_measurements_are_comparative_not_tadash_calibration=True,
            biological_capacity_verified=False, potassium_and_acid_base_modelled=False)

    def _validate_state(self, s):
        if set(s) != set(self.origin): raise ValueError('renal state fields differ')
        for k, v in s.items():
            if k == 'ticks':
                if type(v) is not int or v < 0: raise ValueError('invalid renal tick count')
            else: number(v, k)
        number(s['water_signal'], 'water signal', 0., 1.)
        o = self.origin
        na_error = o['sodium_free_mmol'] + o['sodium_bound_mmol'] + s['sodium_input_mmol'] - o['sodium_input_mmol']
        na_error -= s['sodium_free_mmol'] + s['sodium_bound_mmol'] + s['sodium_urine_mmol'] - o['sodium_urine_mmol'] + s['sodium_sweat_mmol'] - o['sodium_sweat_mmol']
        w_error = o['waste_free_mOsm'] + o['waste_bound_mOsm'] + s['waste_input_mOsm'] - o['waste_input_mOsm'] + s['waste_generated_mOsm'] - o['waste_generated_mOsm']
        w_error -= s['waste_free_mOsm'] + s['waste_bound_mOsm'] + s['waste_urine_mOsm'] - o['waste_urine_mOsm']
        if abs(na_error) > 1e-6 or abs(w_error) > 1e-6: raise ValueError('renal solute ledger mismatch')

    def validate(self):
        self.parameters.validate()
        expected = {'time_s', 'sodium_free_mmol', 'sodium_bound_mmol', 'waste_free_mOsm', 'waste_bound_mOsm',
            'water_signal', 'ticks', 'sodium_input_mmol', 'sodium_urine_mmol', 'sodium_sweat_mmol',
            'waste_input_mOsm', 'waste_generated_mOsm', 'waste_urine_mOsm', 'pump_energy_J', 'filtered_L'}
        if set(self.origin) != expected: raise ValueError('renal origin fields differ')
        self._validate_state(self.origin); self._validate_state(self.state)
        if self.state['time_s'] < self.origin['time_s']: raise ValueError('renal clock precedes origin')

    def checkpoint(self):
        self.validate()
        p = dict(schema=SCHEMA, source_sha256=source_hash(), parameters=asdict(self.parameters),
            state=deepcopy(self.state), origin=deepcopy(self.origin))
        return dict(payload=p, sha256=digest(p))

    @classmethod
    def restore(cls, checkpoint):
        try:
            p = deepcopy(checkpoint['payload'])
            if checkpoint['sha256'] != digest(p) or p['schema'] != SCHEMA or p['source_sha256'] != source_hash():
                raise ValueError('renal checkpoint integrity/source mismatch')
            obj = cls(parameters=Parameters(**p['parameters']))
            obj.origin = p['origin']; obj.state = p['state']; obj.validate()
            return obj
        except (KeyError, TypeError, AttributeError) as e: raise ValueError('malformed renal checkpoint') from e
