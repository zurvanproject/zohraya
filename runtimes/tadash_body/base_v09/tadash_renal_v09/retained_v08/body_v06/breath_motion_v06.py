"""Explicit gas-store / finite-body coupling for fictional Tadash.

Gas units are oxygen-equivalent litres and an aggregate CO2 store, NOT PaO2,
SpO2, arterial CO2, a fitted lung, or a clinical prediction. All constants below
are design fixtures. Breathing work shares the existing finite energy ledger.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import math
from pathlib import Path

from body_loop_v06 import CHANNELS, Inputs, clamp, number, unit
from pain_resilience_v04 import ResilientBody

SCHEMA = "tadash-breath-motion/0.6-bilateral"
OXYGEN_J_PER_L = 20000.0
O2_CAPACITY_L = 3.0
O2_REFERENCE_L = 2.0
RESPIRATORY_QUOTIENT = 0.8
DEAD_SPACE_L = 0.20
BASE_VENTILATION_L_MIN = 12.1
BASE_METABOLIC_W = 220.0
MAX_VENTILATION_L_MIN = 80.0
MODES = {"move", "rest", "stabilize"}


@dataclass(frozen=True)
class Environment:
    body: Inputs = field(default_factory=Inputs)
    activity: float = 0.0
    support_quality: float = 1.0
    ambient_oxygen_factor: float = 1.0
    airway_capacity: float = 1.0
    request_paced_breath: bool = False
    bpm: float = 123.05


@dataclass
class GasState:
    time_s: float = 0.0
    usable_o2_L: float = 2.0
    co2_store_L: float = 0.22
    rate_min: float = 11.0
    tidal_L: float = 1.1
    phase_cycles: float = 0.0
    uptake_L: float = 0.0
    consumed_L: float = 0.0
    expired_unused_o2_L: float = 0.0
    produced_co2_L: float = 0.0
    cleared_co2_L: float = 0.0


@dataclass
class Planner:
    mode: str = "rest"
    reason: str = "quiet_choice"
    recovery_s: float = 0.0
    rest_latched: bool = False
    return_fraction: float = 1.0


def checksum(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def coupling_fingerprint():
    root = Path(__file__).parent
    return checksum({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                     for name in ("breath_motion_v06.py", "pain_resilience_v04.py")})


class BreathMotionLoop:
    def __init__(self, *, body=None, initial_gas=None):
        self.body = body if body is not None else ResilientBody()
        self.gas = GasState(**deepcopy(initial_gas or {}))
        self.gas.time_s = self.body.state.time_s
        self.gas_origin = asdict(self.gas)
        self.planner = Planner()
        self.last_balance = 1.0
        self.last_aerobic_W = BASE_METABOLIC_W
        self.last_motor_W = 0.0
        self.last = None
        self._validate_state()

    def _validate_state(self):
        g = self.gas
        for key, value in asdict(g).items():
            number(value, key)
        number(g.usable_o2_L, "oxygen store", 0, O2_CAPACITY_L)
        number(g.rate_min, "respiratory rate", 0, 60)
        number(g.tidal_L, "tidal volume", 0, 3)
        if abs(g.time_s - self.body.state.time_s) > 1e-8:
            raise ValueError("gas/body clock mismatch")
        if self.planner.mode not in MODES:
            raise ValueError("unknown planner mode")
        if not isinstance(self.planner.reason, str):
            raise ValueError("planner reason must be a string")
        if type(self.planner.rest_latched) is not bool:
            raise ValueError("rest latch must be bool")
        number(self.planner.recovery_s, "recovery timer")
        unit(self.planner.return_fraction, "task return ramp")
        unit(self.last_balance, "last balance")
        number(self.last_aerobic_W, "last aerobic power")
        number(self.last_motor_W, "last motor power")

    def _validate_environment(self, e):
        if not isinstance(e, Environment):
            raise ValueError("Environment required")
        dt, maps = self.body._validate_input(e.body)
        for key in ("activity", "support_quality", "ambient_oxygen_factor", "airway_capacity"):
            unit(getattr(e, key), key)
        if type(e.request_paced_breath) is not bool:
            raise ValueError("paced request must be bool")
        number(e.bpm, "bpm", 20, 250)
        # Gases, pacing, and respiratory power are outputs of this coupling.
        # Reject hidden competing settings instead of silently ignoring them.
        defaults = Inputs()
        for key in ("oxygen_fraction", "co2_adequacy_proxy", "ventilation_ok",
                    "paced_breath", "inhale_s", "exhale_s",
                    "respiratory_work_requested_W", "aerobic_limit_W"):
            if getattr(e.body, key) != getattr(defaults, key):
                raise ValueError("coupling owns body input: " + key)
        return dt, maps

    def _choose(self, e, dt):
        s, g, p = self.body.state, self.gas, self.planner
        o2_ratio = clamp(g.usable_o2_L / O2_REFERENCE_L)
        raw_hazard = max((max((v for k, v in row.items() if k != "touch"), default=0.0)
                          for row in e.body.stimuli.values()), default=0.0)
        wound_danger = max(s.wounds_kg.values(), default=0.0) / 0.02
        fatigue = max(s.fatigue[c] for c in CHANNELS if c.startswith(("hip_", "knee_", "ankle_")))
        if e.support_quality < 0.40 or self.last_balance < 0.35:
            p.mode, p.reason = "stabilize", "footing"
            p.rest_latched, p.recovery_s = True, 0.0
            p.return_fraction = 0.0
            return 0.0
        reason = None
        if e.airway_capacity < 0.15 or o2_ratio < 0.78 or g.co2_store_L > 0.60:
            reason = "gas"
        elif raw_hazard >= 0.65 or wound_danger >= 0.65 or s.latched["systemic"]:
            reason = "tissue_warning"
        elif s.fuel_J < 40000.0:
            reason = "energy"
        elif fatigue >= 0.60:
            reason = "fatigue"
        elif self.body.endurance.pause_requested:
            reason = "sensory_load"
        if reason:
            p.mode, p.reason = "rest", reason
            p.rest_latched, p.recovery_s = True, 0.0
            p.return_fraction = 0.0
            return 0.0
        if p.rest_latched:
            recovered = (o2_ratio >= 0.93 and g.co2_store_L < 0.34
                         and e.support_quality >= 0.75 and fatigue < 0.48
                         and s.fuel_J >= 50000.0 and raw_hazard < 0.45
                         and wound_danger < 0.45
                         and not any(s.latched.values())
                         and not self.body.endurance.pause_requested)
            p.recovery_s = p.recovery_s + dt if recovered else 0.0
            if p.recovery_s < 5.0:
                p.mode, p.reason = "rest", "recovery_hold"
                return 0.0
            p.rest_latched, p.recovery_s = False, 0.0
        p.mode = "move" if e.activity > 0 else "rest"
        p.reason = "chosen_activity" if e.activity > 0 else "quiet_choice"
        if e.activity > 0:
            p.return_fraction = min(1.0, p.return_fraction + dt / 8.0)
        # Slow down progressively before the hard fatigue/energy threshold.
        scale = min(1.0, max(0.0, (0.65 - fatigue) / 0.25),
                    max(0.0, (s.fuel_J - 40000.0) / 100000.0))
        return e.activity * scale * p.return_fraction

    def step(self, e=Environment()):
        self._validate_state()
        dt, maps = self._validate_environment(e)  # complete validation before mutations
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
        paced = bool(e.request_paced_breath and activity < 0.12 and metabolic_request < 80.
                     and gas_ratio >= 0.90 and co2_adequacy >= 0.90
                     and e.airway_capacity >= 0.90 and e.support_quality >= 0.75)
        rate_target = 6.0 if paced else min(32.0, 11.0 + 0.32 * (target_ve - 12.1))
        tidal_target = min(2.6, target_ve / rate_target)
        response = 1.0 - math.exp(-dt / 5.0)
        g.rate_min += (rate_target - g.rate_min) * response
        g.tidal_L += (tidal_target - g.tidal_L) * response
        effective_rate = g.rate_min * e.airway_capacity
        minute_ventilation = effective_rate * g.tidal_L
        alveolar_ventilation = effective_rate * max(0.0, g.tidal_L - DEAD_SPACE_L)
        # Finite aggregate uptake, with an explicit store-gradient design term.
        uptake = (alveolar_ventilation / 60.0 * 0.21 * 0.95
                  * e.ambient_oxygen_factor
                  * max(0.0, 1.0 - g.usable_o2_L / O2_CAPACITY_L) * dt)
        available_o2 = g.usable_o2_L + uptake
        work_breath_W = 1.5 + 0.005 * minute_ventilation ** 2
        ventilation_ok = alveolar_ventilation >= 8.0
        paced = paced and ventilation_ok
        # Paced timing stays 4/6. Free timing follows respiratory rate and is
        # deliberately independent of the beat / movement phase.
        cycle_s = 10.0 if paced else 60.0 / max(0.1, g.rate_min)
        inhale_s, exhale_s = (4.0, 6.0) if paced else (0.4 * cycle_s, 0.6 * cycle_s)
        actual_input = replace(e.body, force_requests_N=requested,
                               oxygen_fraction=gas_ratio,
                               co2_adequacy_proxy=co2_adequacy,
                               ventilation_ok=ventilation_ok,
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
            -alveolar_ventilation / 60.0 * 0.25 * dt))
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
            "work_requested_W": work_breath_W,
            "work_actual_W": f["circulation"]["respiratory_work_actual_W"],
            "phase": "inhale" if g.phase_cycles % 1 < 0.4 else "exhale",
            "ledger": {"before_o2_L": before["usable_o2_L"], "uptake_L": uptake,
                       "consumed_o2_L": consumed, "expired_unused_o2_L": unused_expired,
                       "before_co2_L": before["co2_store_L"],
                       "produced_co2_L": produced_co2, "cleared_co2_L": removed_co2},
            "measured_arterial_gases": False,
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

    def checkpoint(self):
        self._validate_state()
        p = {"schema": SCHEMA, "body": self.body.checkpoint(),
             "coupling_fingerprint": coupling_fingerprint(),
             "gas": asdict(self.gas), "gas_origin": self.gas_origin,
             "planner": asdict(self.planner), "last_balance": self.last_balance,
             "last_aerobic_W": self.last_aerobic_W, "last_motor_W": self.last_motor_W}
        return {"payload": deepcopy(p), "sha256": checksum(p)}

    @classmethod
    def restore(cls, checkpoint):
        try:
            c = deepcopy(checkpoint)
            if set(c) != {"payload", "sha256"}:
                raise ValueError("bad checkpoint envelope")
            p = c["payload"]
            if p["schema"] != SCHEMA or checksum(p) != c["sha256"]:
                raise ValueError("checkpoint integrity/version mismatch")
            if p["coupling_fingerprint"] != coupling_fingerprint():
                raise ValueError("coupling source fingerprint mismatch")
            b = ResilientBody.restore(p["body"])
            obj = cls(body=b, initial_gas=p["gas"])
            obj.gas_origin = deepcopy(p["gas_origin"])
            obj.planner = Planner(**p["planner"])
            for key in ("last_balance", "last_aerobic_W", "last_motor_W"):
                setattr(obj, key, p[key])
            obj._validate_state()
            o, g = obj.gas_origin, asdict(obj.gas)
            for value in o.values():
                number(value, "gas origin")
            expected_o = o["usable_o2_L"] + g["uptake_L"] - o["uptake_L"]
            expected_o -= g["consumed_L"] - o["consumed_L"]
            expected_o -= g["expired_unused_o2_L"] - o["expired_unused_o2_L"]
            expected_c = o["co2_store_L"] + g["produced_co2_L"] - o["produced_co2_L"]
            expected_c -= g["cleared_co2_L"] - o["cleared_co2_L"]
            if abs(expected_o - g["usable_o2_L"]) > 1e-7 or abs(expected_c - g["co2_store_L"]) > 1e-7:
                raise ValueError("gas mass-balance mismatch")
            return obj
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("malformed breath-motion checkpoint") from exc

