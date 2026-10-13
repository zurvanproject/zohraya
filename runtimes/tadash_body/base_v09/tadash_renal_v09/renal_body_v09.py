"""V06 allocation with renal transport in the same vital fuel/O2 budget.

Generated from retained V06 by derive_body_v09.py. Water and fuel remain in
the existing owner; filtration is an internal flow, not a second withdrawal.
The 177 W baseline is still unpartitioned. The explicit added pump charge is
a design accounting choice, not measured total kidney metabolic cost.
"""
from copy import deepcopy
from dataclasses import asdict
import math
from body_loop_v06 import *
from pain_resilience_v04 import ResilientBody


class RenalLedgerBody(BodyLoop):
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
        renal_plan = self.renal.prepare(time_s=s.time_s, dt_s=dt, water_L=before["free_water_L"],
            water_intake_L=water_in, flow_ratio=min(1., flow["flow_L_min"]/self.table["1.0"]["flow_L_min"]),
            oxygen_fraction=i.oxygen_fraction, inputs=self.renal_input)
        renal_requested_W = renal_plan["payload"]["pump_requested_J"] / dt
        vital_requested_W = 177.0 + flow["pump_extra_metabolic_W"] + i.respiratory_work_requested_W + renal_requested_W
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
        renal_frame = self.renal.settle(renal_plan, paid_fraction=vital_W/vital_requested_W,
            water_available_L=s.free_water_L, water_bound_L=bound_L, evaporated_L=evap_L, fuel_used_J=fuel_used_J)
        urine_L = renal_frame["ledger"]["urine_water_L"]
        s.free_water_L -= urine_L
        for c in CHANNELS:
            s.wounds_kg[c] = max(0.0, s.wounds_kg[c] - repairs[c])
            effort = forces[c] / max(1.0, capacity[c])
            s.fatigue[c] = clamp(s.fatigue[c] + dt * (0.004 * effort - 0.002 * (effort < 0.1)))
            s.previous_force_N[c] = forces[c]
        s.time_s += dt
        result = {
            "t_s": s.time_s, "state": asdict(s), "renal": renal_frame,
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
                "renal_work_requested_W": renal_requested_W,
                "renal_work_actual_W": renal_frame["ledger"]["pump_actual_J"]/dt,
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
                "renal_energy_included_in_fuel_J": renal_frame["ledger"]["pump_actual_J"],
                "legacy_simple_urine_loss_replaced_not_added": True,
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


class RenalResilientBody(ResilientBody, RenalLedgerBody):
    """Retain paid posture, finite gas coupling and sensory-load endurance."""
    pass
