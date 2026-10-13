"""Tadash V06: one finite ledger with bilateral joints and priority posture forces.

An engineering design fixture. Numerical rates and biological proxies are
unvalidated assumptions retained from earlier project models.
"""
from __future__ import annotations
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path

from bilateral_sections import bilateral_sections
from baseline.pain.pain import PainSystem

ROOT = Path(__file__).parent
CHANNELS = ("elbow", "hip_L", "knee_L", "ankle_L", "hip_R", "knee_R", "ankle_R", "tail")
REGION_FOR = {"elbow": "upper_arm_L", "hip_L": "thigh_L", "knee_L": "thigh_L", "ankle_L": "calf_L", "hip_R": "thigh_R", "knee_R": "thigh_R", "ankle_R": "calf_R", "tail": "tail_L_1"}
HEAT_LIMIT_J = 195000.0
REPAIR_J_KG = 50000.0
TISSUE_J_KG = 10000.0
REPAIR_WATER_L_KG = 3.0
REPAIR_RATE_KG_S = 0.00003  # aggregate, not one allowance per channel
SCHEMA = "tadash-body-feedback/0.6-bilateral"

def number(value, name, low=0.0, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + ": finite numeric value required")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(name + ": out of design bounds")
    return float(value)

def unit(value, name):
    return number(value, name, 0, 1)

def clamp(value):
    return min(1.0, max(0.0, value))

def channel_values(values=None, default=0.0, high=1e12):
    values = {} if values is None else values
    if not isinstance(values, dict) or set(values) - set(CHANNELS):
        raise ValueError("unknown force channel")
    return {c: number(values.get(c, default), c, high=high) for c in CHANNELS}

@dataclass
class State:
    time_s: float = 0.0
    fuel_J: float = 4000000.0
    reserve_J: float = 60000.0
    free_water_L: float = 110.0
    bound_water_L: float = 0.0
    material_kg: float = 1.0
    repaired_kg: float = 0.0
    heat_J: float = 0.0
    wounds_kg: dict = field(default_factory=lambda: channel_values())
    fatigue: dict = field(default_factory=lambda: channel_values())
    previous_force_N: dict = field(default_factory=lambda: channel_values())
    latched: dict = field(default_factory=lambda: {c: False for c in (*CHANNELS, "systemic")})
    clear_s: dict = field(default_factory=lambda: {c: 0.0 for c in (*CHANNELS, "systemic")})
    return_fraction: dict = field(default_factory=lambda: {c: 1.0 for c in CHANNELS})

@dataclass(frozen=True)
class Inputs:
    dt_s: float = 0.5
    force_requests_N: dict = field(default_factory=lambda: channel_values())
    postural_force_requests_N: dict = field(default_factory=lambda: channel_values())
    speeds_m_s: dict = field(default_factory=lambda: channel_values(default=0.25))
    regional_perfusion: dict = field(default_factory=lambda: channel_values(default=1.0))
    tendon_integrity: dict = field(default_factory=lambda: channel_values(default=1.0))
    injury_events_kg: dict = field(default_factory=lambda: channel_values())
    stimuli: dict = field(default_factory=dict)
    respiratory_work_requested_W: float = 0.0
    aerobic_limit_W: float = 1e7
    oxygen_fraction: float = 1.0
    co2_adequacy_proxy: float = 1.0
    ventilation_ok: bool = True
    geometry_open: bool = True
    paced_breath: bool = False
    inhale_s: float = 4.0
    exhale_s: float = 6.0
    food_intake_J_s: float = 0.0
    water_intake_L_s: float = 0.00025
    evap_efficiency: float = 0.8
    passive_cooling_W: float = 180.0

class BodyLoop:
    def __init__(self, table=None, initial=None, *, body_to_pain=True,
                 regional_guard=True, breath_gain=0.25):
        if type(body_to_pain) is not bool or type(regional_guard) is not bool:
            raise ValueError("ablation flags must be bool")
        self.table = deepcopy(table if table is not None else
                              json.loads((ROOT / "hydraulic_table_v03.json").read_text()))
        required = {str(x / 10) for x in range(5, 11)}
        if set(self.table) != required:
            raise ValueError("incomplete circulation table")
        for key, row in self.table.items():
            for name in ("flow_L_min", "head_pressure_proxy_mmHg",
                         "pump_extra_metabolic_W", "node_balance_error_L_min"):
                number(row[name], name)
        self.body_to_pain = body_to_pain
        self.regional_guard = regional_guard
        self.pain = PainSystem(breath_gain=number(breath_gain, "gain", 0, 0.25))
        self.sections = bilateral_sections()
        self.state = State(**deepcopy(initial or {}))
        self._validate_state(self.state)
        self.pain.time = self.state.time_s
        self.origin = asdict(self.state)
        self.last = None

    def _validate_state(self, state):
        for key in ("time_s", "fuel_J", "reserve_J", "free_water_L",
                    "bound_water_L", "material_kg", "repaired_kg", "heat_J"):
            number(getattr(state, key), key)
        for key in ("wounds_kg", "fatigue", "previous_force_N"):
            values = getattr(state, key)
            if not isinstance(values, dict) or set(values) != set(CHANNELS):
                raise ValueError("state channel mismatch")
            for value in values.values():
                number(value, key, high=1 if key == "fatigue" else 1e12)
        gates = set(CHANNELS) | {"systemic"}
        if set(state.latched) != gates or any(type(v) is not bool for v in state.latched.values()):
            raise ValueError("invalid protective latch")
        if set(state.clear_s) != gates:
            raise ValueError("invalid latch timers")
        for value in state.clear_s.values():
            number(value, "clear timer")
        if set(state.return_fraction) != set(CHANNELS):
            raise ValueError("invalid return ramp")
        for value in state.return_fraction.values():
            unit(value, "return ramp")

    def _validate_input(self, i):
        if not isinstance(i, Inputs):
            raise ValueError("Inputs required")
        dt = number(i.dt_s, "dt", 0.05, 1.0)
        maps = {
            "requests": channel_values(i.force_requests_N, high=1e6),
            "postural": channel_values(i.postural_force_requests_N, high=1e6),
            "speeds": channel_values(i.speeds_m_s, high=5),
            "perfusion": channel_values(i.regional_perfusion, 1, 1),
            "tendon": channel_values(i.tendon_integrity, 1, 1),
            "injury": channel_values(i.injury_events_kg, high=1),
        }
        for name in ("oxygen_fraction", "co2_adequacy_proxy", "evap_efficiency"):
            unit(getattr(i, name), name)
        for name in ("ventilation_ok", "geometry_open", "paced_breath"):
            if type(getattr(i, name)) is not bool:
                raise ValueError(name + ": bool required")
        for name in ("inhale_s", "exhale_s"):
            number(getattr(i, name), name, 0.01, 60)
        for name in ("food_intake_J_s", "water_intake_L_s", "passive_cooling_W", "respiratory_work_requested_W", "aerobic_limit_W"):
            number(getattr(i, name), name, 0, 1e7)
        if not isinstance(i.stimuli, dict):
            raise ValueError("stimuli must be a mapping")
        allowed = {"mechanical", "thermal", "chemical", "ischemia",
                   "damage", "nerve_injury", "touch"}
        for key, row in i.stimuli.items():
            if key not in self.pain.regions or not isinstance(row, dict) or set(row) - allowed:
                raise ValueError("invalid regional stimulus")
            for value in row.values():
                unit(value, "stimulus")
        return dt, maps

    def _latch(self, name, hazard, dt):
        if hazard >= 0.65:
            self.state.latched[name] = True
            self.state.clear_s[name] = 0.0
            if name in CHANNELS:
                self.state.return_fraction[name] = 0.0
            else:
                for channel in CHANNELS:
                    self.state.return_fraction[channel] = 0.0
        elif self.state.latched[name]:
            if hazard < 0.45:
                self.state.clear_s[name] += dt
                if self.state.clear_s[name] >= 2.0:
                    self.state.latched[name] = False
            else:
                self.state.clear_s[name] = 0.0

    def step(self, i=Inputs()):
        dt, m = self._validate_input(i)  # all external validation before state mutation
        s = self.state
        before = asdict(s)
        for c in CHANNELS:
            s.wounds_kg[c] += m["injury"][c]
        food_in = i.food_intake_J_s * dt
        water_in = i.water_intake_L_s * dt
        s.fuel_J += food_in
        s.free_water_L += water_in
        hydration = min(1.0, max(0.5, s.free_water_L / 110.0))
        key = str(round(math.floor((hydration + 1e-9) * 10) / 10, 1))
        flow = self.table[key]
        oxygen_W = flow["flow_L_min"] * 0.20 * 0.65 * 20000 / 60 * i.oxygen_fraction
        vital_requested_W = 177.0 + flow["pump_extra_metabolic_W"] + i.respiratory_work_requested_W
        aerobic_W = min(oxygen_W, i.aerobic_limit_W, s.fuel_J / dt)
        vital_W = min(vital_requested_W, aerobic_W)
        free_W = max(0.0, aerobic_W - vital_W)
        oxygen_adequacy = min(i.oxygen_fraction, vital_W / vital_requested_W)
        perfusion = {
            c: m["perfusion"][c] * min(1.0, flow["flow_L_min"] / self.table["1.0"]["flow_L_min"])
            for c in CHANNELS
        }

        stimuli = deepcopy(i.stimuli)
        if self.body_to_pain:
            # Uniform thermal-risk broadcast is a control proxy, not tissue temperature.
            thermal_hazard = clamp((s.heat_J / HEAT_LIMIT_J - 0.70) / 0.30)
            for region in self.pain.regions:
                row = stimuli.setdefault(region, {})
                row["thermal"] = max(row.get("thermal", 0.0), thermal_hazard)
            for c, region in REGION_FOR.items():
                row = stimuli.setdefault(region, {})
                row["damage"] = max(row.get("damage", 0.0), clamp(s.wounds_kg[c] / 0.02))
                row["ischemia"] = max(row.get("ischemia", 0.0), 1.0 - perfusion[c])
                # Previous delivered load feeds the next sensory tick.
                old_limit = self.sections[c]["external_force_ceiling_N"]
                load = 0.30 * clamp(s.previous_force_N[c] / old_limit)
                row["mechanical"] = max(row.get("mechanical", 0.0), load)

        pain = self.pain.step(
            stimuli, dt=dt, paced=i.paced_breath, oxygen=oxygen_adequacy,
            co2_ok=i.co2_adequacy_proxy, ventilation_ok=i.ventilation_ok,
            inhale_s=i.inhale_s, exhale_s=i.exhale_s,
        )
        hazards = {c: 0.0 for c in (*CHANNELS, "systemic")}
        for row in pain["regions"]:
            region = self.pain.regions[row["id"]]["region"]
            rid = row["id"]
            side = "L" if "_L" in rid else ("R" if "_R" in rid else None)
            if region == "arm":
                targets = ("elbow",)
            elif region == "leg":
                targets = tuple(k + "_" + s for s in ((side,) if side else ("L", "R"))
                                for k in ("hip", "knee", "ankle"))
            elif region == "tail":
                targets = ("tail",)
            else:
                targets = ("systemic",)
            for target in targets:
                hazards[target] = max(hazards[target], row["raw_hazard"])
        if self.regional_guard:
            for name, hazard in hazards.items():
                self._latch(name, hazard, dt)
            for channel in CHANNELS:
                if not s.latched[channel] and not s.latched["systemic"]:
                    s.return_fraction[channel] = min(
                        1.0, s.return_fraction[channel] + dt / 4.0
                    )

        # One aggregate repair allowance and one material/water/energy balance.
        wounds_before_repair = dict(s.wounds_kg)
        total_wound = sum(s.wounds_kg.values())
        weights = {c: s.wounds_kg[c] * perfusion[c] for c in CHANNELS}
        weight_sum = sum(weights.values())
        aggregate_perfusion = weight_sum / total_wound if total_wound else 0.0
        repair_total = min(
            total_wound, s.material_kg, REPAIR_RATE_KG_S * dt * aggregate_perfusion,
            free_W * dt / REPAIR_J_KG, s.free_water_L / REPAIR_WATER_L_KG,
        )
        repairs = {
            c: min(s.wounds_kg[c], repair_total * weights[c] / weight_sum)
            if weight_sum else 0.0 for c in CHANNELS
        }
        repair_total = sum(repairs.values())
        repair_J = repair_total * REPAIR_J_KG
        tissue_J = repair_total * TISSUE_J_KG
        bound_L = repair_total * REPAIR_WATER_L_KG
        free_W = max(0.0, free_W - repair_J / dt)

        cooling_water = max(0.0, s.free_water_L - bound_L)
        evap_L = min(
            0.001 * dt, cooling_water,
            s.heat_J / (2400000 * i.evap_efficiency) if i.evap_efficiency > 0 else 0.0,
        )
        evap_removed_J = evap_L * 2400000 * i.evap_efficiency
        passive_removed_J = min(
            i.passive_cooling_W * dt, max(0.0, s.heat_J - evap_removed_J)
        )
        heat_removed_J = evap_removed_J + passive_removed_J

        systemic_stop = bool(self.regional_guard and s.latched["systemic"])
        critical_stop = (
            not i.geometry_open or flow["head_pressure_proxy_mmHg"] < 65.0
            or vital_W < vital_requested_W - 1e-9 or i.oxygen_fraction <= 0
            or not i.ventilation_ok or s.heat_J >= HEAT_LIMIT_J
        )
        capacity = {}
        hazard_cap = {}
        candidates = {}
        postural_candidates = {}
        optional_candidates = {}
        for c in CHANNELS:
            a = self.sections[c]
            muscle_moment = a["muscle_force_N"] * (1 - 0.5 * s.fatigue[c]) * a["muscle_moment_arm_m"] * perfusion[c]
            tendon_moment = a["tendon_allowable_force_N"] * m["tendon"][c] * a["muscle_moment_arm_m"]
            capacity[c] = min(
                muscle_moment, tendon_moment, a["bone_allowable_moment_Nm"],
                a["joint_allowable_moment_Nm"],
            ) / a["external_load_arm_m"]
            if self.regional_guard:
                hazard_cap[c] = 0.0 if s.latched[c] else min(
                    1 - hazards[c], 1 - hazards["systemic"], s.return_fraction[c]
                )
            else:
                hazard_cap[c] = 1.0
            guarded_capacity = capacity[c] * hazard_cap[c]
            postural_candidates[c] = min(m["postural"][c], guarded_capacity)
            optional_candidates[c] = min(m["requests"][c], max(0., guarded_capacity - postural_candidates[c]))
            if critical_stop or systemic_stop:
                postural_candidates[c] = optional_candidates[c] = 0.0
            candidates[c] = postural_candidates[c] + optional_candidates[c]

        coefficients = {c: m["speeds"][c] / 0.30 + 0.06 for c in CHANNELS}
        candidate_motor_W = sum(candidates[c] * coefficients[c] for c in CHANNELS)
        candidate_work_W = sum(candidates[c] * m["speeds"][c] for c in CHANNELS)
        reserve_W = min(s.reserve_J / dt, 1800.0)
        heat_room_J = max(0.0, HEAT_LIMIT_J - s.heat_J + heat_removed_J
                          - (vital_W * dt + repair_J - tissue_J))
        budget_W = free_W + reserve_W
        allocated = {}
        factors = {}
        for label, candidates_tier in (("postural", postural_candidates), ("optional", optional_candidates)):
            power_W = sum(candidates_tier[c] * coefficients[c] for c in CHANNELS)
            heat_J = sum(candidates_tier[c] * (coefficients[c] - m["speeds"][c]) * dt for c in CHANNELS)
            fraction = min(1., budget_W / power_W) if power_W else 1.
            if heat_J:
                fraction = min(fraction, heat_room_J / heat_J)
            factors[label] = fraction
            allocated[label] = {c: candidates_tier[c] * fraction for c in CHANNELS}
            budget_W = max(0., budget_W - power_W * fraction)
            heat_room_J = max(0., heat_room_J - heat_J * fraction)
        forces = {c: allocated["postural"][c] + allocated["optional"][c] for c in CHANNELS}
        factor = min(factors.values())
        motor_W = sum(forces[c] * coefficients[c] for c in CHANNELS)
        work_J = sum(forces[c] * m["speeds"][c] * dt for c in CHANNELS)
        motor_aerobic_W = min(free_W, motor_W)
        reserve_used_J = max(0.0, motor_W - motor_aerobic_W) * dt
        fuel_used_J = vital_W * dt + repair_J + motor_aerobic_W * dt
        produced_J = fuel_used_J + reserve_used_J - work_J - tissue_J

        s.fuel_J = max(0.0, s.fuel_J - fuel_used_J)
        s.reserve_J = max(0.0, s.reserve_J - reserve_used_J)
        s.heat_J = max(0.0, s.heat_J + produced_J - heat_removed_J)
        s.material_kg = max(0.0, s.material_kg - repair_total)
        s.repaired_kg += repair_total
        s.free_water_L = max(0.0, s.free_water_L - bound_L - evap_L)
        s.bound_water_L += bound_L
        respiratory_L = min(s.free_water_L, 0.000015 * dt)
        s.free_water_L -= respiratory_L
        urine_L = min(s.free_water_L, 0.00002 * dt * hydration)
        s.free_water_L -= urine_L
        for c in CHANNELS:
            s.wounds_kg[c] = max(0.0, s.wounds_kg[c] - repairs[c])
            effort = forces[c] / max(1.0, capacity[c])
            s.fatigue[c] = clamp(s.fatigue[c] + dt * (0.004 * effort - 0.002 * (effort < 0.1)))
            s.previous_force_N[c] = forces[c]
        s.time_s += dt
        result = {
            "t_s": s.time_s, "state": asdict(s),
            "motor": {
                "force_N": forces, "capacity_N": capacity, "hazard_fraction_cap": hazard_cap,
                "requests_N": {c: m["requests"][c] + m["postural"][c] for c in CHANNELS},
                "postural_requests_N": m["postural"], "optional_requests_N": m["requests"],
                "postural_force_N": allocated["postural"], "optional_force_N": allocated["optional"],
                "priority_fractions": factors, "speeds_m_s": m["speeds"], "critical_stop": critical_stop,
                "systemic_stop": systemic_stop, "support_request": bool(
                    self.regional_guard and any(s.latched[c] for c in CHANNELS if c.startswith(("hip_", "knee_", "ankle_")))
                ),
                "support_executed": False, "regional_hazard": hazards,
                "allocation_fraction": factor,
            },
            "pain": {
                "peak_intensity_proxy": pain["brain_workspace"]["intensity_proxy"],
                "peak_region": pain["brain_workspace"]["source"],
                "modulation_available": pain["breath_modulation_available"],
                "calming_proxy": pain["calming_proxy"], "breath_phase": pain["breath_phase"],
                "raw_protective_signal": pain["brain_workspace"]["protective_stop"],
            },
            "circulation": {
                "Q_L_min": flow["flow_L_min"],
                "head_pressure_proxy_mmHg": flow["head_pressure_proxy_mmHg"],
                "oxygen_power_W": oxygen_W, "oxygen_adequacy_proxy": oxygen_adequacy,
                "vital_requested_W": vital_requested_W, "vital_actual_W": vital_W,
                "vital_shortfall_W": vital_requested_W - vital_W,
                "respiratory_work_actual_W": i.respiratory_work_requested_W * vital_W / vital_requested_W,
                "regional_perfusion": perfusion,
            },
            "ledger": {
                "dt_s": dt, "food_input_J": food_in, "water_input_L": water_in,
                "fuel_used_J": fuel_used_J, "reserve_used_J": reserve_used_J,
                "work_J": work_J, "tissue_energy_J": tissue_J,
                "heat_produced_J": produced_J, "heat_removed_J": heat_removed_J,
                "evaporated_L": evap_L, "respiratory_water_loss_L": respiratory_L,
                "urine_loss_L": urine_L, "repair_material_kg": repair_total,
                "water_bound_L": bound_L, "repair_by_channel_kg": repairs,
                "injury_events_kg": m["injury"],
                "wounds_before_repair_kg": wounds_before_repair,
                "motor_energy_J": motor_W * dt,
                "motor_heat_J": motor_W * dt - work_J,
                "thermal_overrun_J": max(0.0, s.heat_J - HEAT_LIMIT_J),
            },
        }
        self.last = result
        return result

    def comfort_pause(self):
        self.pain.comfort_pause()

    def resume(self):
        self.pain.resume()

    def checkpoint(self):
        payload = {
            "schema": SCHEMA, "state": asdict(self.state), "origin": self.origin,
            "body_to_pain": self.body_to_pain, "regional_guard": self.regional_guard,
            "table_sha256": hashlib.sha256(json.dumps(self.table, sort_keys=True).encode()).hexdigest(),
            "pain": {
                "time": self.pain.time, "calming": self.pain.calming, "enabled": self.pain.enabled,
                "gain": self.pain.gain, "slow": self.pain.slow, "sens": self.pain.sens,
                "queue": list(self.pain.queue), "memory": list(self.pain.memory),
            },
        }
        payload = deepcopy(payload)
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        return {"payload": payload, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}

    @classmethod
    def restore(cls, checkpoint, table=None):
        c = deepcopy(checkpoint)
        if set(c) != {"payload", "sha256"}:
            raise ValueError("invalid checkpoint envelope")
        p = c["payload"]
        actual = hashlib.sha256(json.dumps(p, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if actual != c["sha256"] or p["schema"] != SCHEMA:
            raise ValueError("checkpoint integrity/version mismatch")
        obj = cls(table, p["state"], body_to_pain=p["body_to_pain"],
                  regional_guard=p["regional_guard"], breath_gain=p["pain"]["gain"])
        table_hash = hashlib.sha256(json.dumps(obj.table, sort_keys=True).encode()).hexdigest()
        if p["table_sha256"] != table_hash:
            raise ValueError("circulation fixture mismatch")
        obj.origin = deepcopy(p["origin"])
        obj._validate_state(State(**obj.origin))
        pain = p["pain"]
        number(pain["time"], "pain clock")
        if abs(pain["time"] - obj.state.time_s) > 1e-8:
            raise ValueError("clock mismatch")
        unit(pain["calming"], "calming")
        if type(pain["enabled"]) is not bool:
            raise ValueError("invalid pause")
        for name, upper in (("slow", 1.0), ("sens", 0.5)):
            if set(pain[name]) != set(obj.pain.regions):
                raise ValueError("sensory atlas mismatch")
            for v in pain[name].values():
                number(v, name, 0, upper)
        if len(pain["memory"]) > 128 or len(pain["queue"]) > 203 * 8:
            raise ValueError("unbounded sensory state")
        previous = obj.state.time_s
        for when, region, value in pain["queue"]:
            number(when, "pending clock", obj.state.time_s, obj.state.time_s + 0.200001)
            if when < previous or region not in obj.pain.regions:
                raise ValueError("invalid pending relay")
            unit(value, "pending relay")
            previous = when
        for event in pain["memory"]:
            number(event["t"], "event clock", 0, obj.state.time_s)
            if any(k not in obj.pain.regions for k in event["hazards"]):
                raise ValueError("event region mismatch")
        for name in ("time", "calming", "enabled", "slow", "sens"):
            setattr(obj.pain, name, deepcopy(pain[name]))
        obj.pain.queue = deque(tuple(v) for v in pain["queue"])
        obj.pain.memory = deque(pain["memory"], maxlen=128)
        return obj
