"""V1 physiological breathing actuator derived from unchanged V06 gas kernel.

Adds rate control and voluntary airflow gating. Gas conservation and paid
breathing work retain the same single V09 resource owner. All parameters are
engineering assumptions. No physical breath or clinical vital is measured.
"""
from breath_motion_v06 import *

class ActuatedBreath(BreathMotionLoop):
    breath_mode = "normal"

    def step(self, e=Environment()):
        self._validate_state()
        dt, maps = self._validate_environment(e)  # complete validation before mutations
        exchange_capacity = getattr(self, "exchange_capacity", 1.0)
        unit(exchange_capacity, "lung exchange capacity")
        before = asdict(self.gas)
        activity = self._choose(e, dt)
        requested = {c: maps["requests"][c] * activity for c in CHANNELS}
        metabolic_request = sum((requested[c] + maps["postural"][c]) * (maps["speeds"][c] / 0.30 + 0.06)
                                 for c in CHANNELS)
        g = self.gas
        gas_ratio = clamp(g.usable_o2_L / O2_REFERENCE_L)
        co2_adequacy = min(1.0, 0.30 / max(0.30, g.co2_store_L))
        target_ve = min(MAX_VENTILATION_L_MIN,
                        BASE_VENTILATION_L_MIN + 0.085 * metabolic_request
                        + 40.0 * max(0.0, g.co2_store_L - 0.25)
                        + 20.0 * max(0.0, O2_REFERENCE_L - g.usable_o2_L))
        paced = bool((self.breath_mode == "slow" or e.request_paced_breath) and activity < 0.12 and metabolic_request < 350.
                     and gas_ratio >= 0.90 and co2_adequacy >= 0.90
                     and e.airway_capacity >= 0.90 and e.support_quality >= 0.75)
        rate_target = (24.0 if self.breath_mode == "rapid" else
                       (max(6.0, target_ve / 2.6) if paced else min(32.0, 11.0 + 0.32 * (target_ve - 12.1))))
        tidal_target = min(2.6, target_ve / rate_target)
        if self.breath_mode == "rapid": tidal_target = max(1.1, tidal_target)
        response = 1.0 - math.exp(-dt / 5.0)
        g.rate_min += (rate_target - g.rate_min) * response
        g.tidal_L += (tidal_target - g.tidal_L) * response
        effective_rate = g.rate_min * e.airway_capacity * (0.0 if self.breath_mode == "hold" else 1.0)
        minute_ventilation = effective_rate * g.tidal_L
        alveolar_ventilation = effective_rate * max(0.0, g.tidal_L - DEAD_SPACE_L)
        # Finite aggregate uptake, with an explicit store-gradient design term.
        uptake = (alveolar_ventilation / 60.0 * 0.21 * 0.95
                  * e.ambient_oxygen_factor
                  * exchange_capacity
                  * max(0.0, 1.0 - g.usable_o2_L / O2_CAPACITY_L) * dt)
        available_o2 = g.usable_o2_L + uptake
        work_breath_W = 1.5 + 0.005 * minute_ventilation ** 2
        ventilation_ok = alveolar_ventilation >= 8.0
        # A brief voluntary hold has zero achieved airflow; posture can use
        # existing gas stocks until the explicit reserve guard is crossed.
        # This is a bounded proxy rule, not a clinical breath-holding limit.
        body_ventilation_guard_ok = ventilation_ok or bool(
            self.breath_mode == "hold" and g.usable_o2_L >= 1.9 and g.co2_store_L <= .35)
        paced = paced and ventilation_ok and self.breath_mode != "hold"
        # Paced timing stays 4/6. Free timing follows respiratory rate and is
        # deliberately independent of the beat / movement phase.
        cycle_s = 60.0 / max(0.1, g.rate_min)
        inhale_s, exhale_s = (0.4 * cycle_s, 0.6 * cycle_s)
        actual_input = replace(e.body, force_requests_N=requested,
                               oxygen_fraction=gas_ratio,
                               co2_adequacy_proxy=co2_adequacy,
                               ventilation_ok=body_ventilation_guard_ok,
                               paced_breath=paced, inhale_s=inhale_s, exhale_s=exhale_s,
                               respiratory_work_requested_W=work_breath_W,
                               aerobic_limit_W=available_o2 * OXYGEN_J_PER_L / dt)
        f = self.body.step(actual_input)
        consumed = f["ledger"]["fuel_used_J"] / OXYGEN_J_PER_L
        unused_expired = max(0.0, available_o2 - consumed - O2_CAPACITY_L)
        g.usable_o2_L = max(0.0, available_o2 - consumed - unused_expired)
        produced_co2 = RESPIRATORY_QUOTIENT * consumed
        # Exponential removal keeps the gas stock nonnegative at every allowed dt.
        # Oxygen and CO2 have separate auditable source/sink balances.
        co2_before_clearance = g.co2_store_L + produced_co2
        removed_co2 = co2_before_clearance * (1.0 - math.exp(
            -alveolar_ventilation / 60.0 * 0.25 * exchange_capacity * dt))
        g.co2_store_L = co2_before_clearance - removed_co2
        g.time_s = self.body.state.time_s
        g.phase_cycles += effective_rate / 60.0 * dt
        g.uptake_L += uptake
        g.consumed_L += consumed
        g.expired_unused_o2_L += unused_expired
        g.produced_co2_L += produced_co2
        g.cleared_co2_L += removed_co2
        self.last_aerobic_W = f["ledger"]["fuel_used_J"] / dt
        self.last_motor_W = f["ledger"]["motor_energy_J"] / dt
        # Physical contacts and capture-point margins are owned by PostureLoop.
        # Keep the incoming quality only; no force/fatigue/tail balance credit.
        self.last_balance = e.support_quality
        f["respiration"] = {
            "state": asdict(g), "rate_min": effective_rate,
            "tidal_L": g.tidal_L, "minute_ventilation_L_min": minute_ventilation,
            "alveolar_ventilation_L_min": alveolar_ventilation,
            "oxygen_adequacy_proxy": gas_ratio, "co2_adequacy_proxy": co2_adequacy,
            "paced": paced, "ventilation_ok": ventilation_ok,
            "body_ventilation_guard_ok": body_ventilation_guard_ok,
            "work_requested_W": work_breath_W,
            "work_actual_W": f["circulation"]["respiratory_work_actual_W"],
            "phase": "inhale" if g.phase_cycles % 1 < 0.4 else "exhale",
            "ledger": {"before_o2_L": before["usable_o2_L"], "uptake_L": uptake,
                       "consumed_o2_L": consumed, "expired_unused_o2_L": unused_expired,
                       "before_co2_L": before["co2_store_L"],
                       "produced_co2_L": produced_co2, "cleared_co2_L": removed_co2},
            "measured_arterial_gases": False,
            "exchange_capacity_proxy": exchange_capacity,
            "exchange_model": "bounded linear capacity fixture; not diffusion or V/Q",
            "actuator_mode": self.breath_mode,
        }
        f["task"] = {**asdict(self.planner), "requested_activity": e.activity,
                     "planned_activity": activity,
                     "nonessential_pause_executed": activity == 0 and e.activity > 0,
                     "controller": "bounded_body_task_planner_not_cognitive_workspace"}
        f["balance"] = {"support_quality": e.support_quality,
                        "margin_proxy": None, "physical_contact_owner": "PostureLoop"}
        f["dance"] = {"bpm": e.bpm,
                      "movement_phase": (g.time_s * e.bpm / 120.0) % 1,
                      "breath_locked_to_music": False}
        f["resilience"]["pause_executed"] = bool(
            f["resilience"]["nonessential_task_pause_request"]
            and f["task"]["nonessential_pause_executed"])
        self.last = f
        self._validate_state()
        return f
