"""Finite sensory-load endurance retained on the V06 bilateral posture branch.

The 1x reference is an engineering fixture, not a measured human. A multiplier
changes control-load capacity only; it never changes tissue danger or energy.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from body_loop_v06 import BodyLoop, Inputs, number

ROOT = Path(__file__).parent
SCHEMA = "tadash-pain-resilience/0.4-bilateral"
QUIET_EXPOSURE = 0.05
RECOVERY_RATE = 0.25
PAUSE_AT_USED_FRACTION = 0.95
RELEASE_BELOW_USED_FRACTION = 0.80
CLEAR_HOLD_S = 5.0

@dataclass(frozen=True)
class Parameters:
    multiplier: float = 20.0
    reference_capacity_proxy_s: float = 60.0

@dataclass
class Endurance:
    time_s: float = 0.0
    spent_proxy_s: float = 0.0
    charged_proxy_s: float = 0.0
    recovered_proxy_s: float = 0.0
    overflow_proxy_s: float = 0.0
    pause_requested: bool = False
    clear_s: float = 0.0

def baseline_fingerprint():
    paths = ("body_loop_v06.py", "baseline/pain/pain.py", "baseline/pain/regions.json",
             "baseline/motion/sections.py", "bilateral_sections.py", "hydraulic_table_v03.json")
    data = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

class ResilientBody(BodyLoop):
    def __init__(self, table=None, initial=None, *, multiplier=20,
                 reference_capacity_proxy_s=60, body_to_pain=True,
                 regional_guard=True, breath_gain=0.25):
        # Validate the added configuration before constructing body state.
        multiplier = number(multiplier, "endurance multiplier", 1, 20)
        reference = number(reference_capacity_proxy_s, "reference capacity", 1, 3600)
        super().__init__(table, initial, body_to_pain=body_to_pain,
                         regional_guard=regional_guard, breath_gain=breath_gain)
        self.parameters = Parameters(multiplier, reference)
        self.endurance = Endurance(time_s=self.state.time_s)
        self.endurance_origin = asdict(self.endurance)

    @property
    def capacity_proxy_s(self):
        return self.parameters.multiplier * self.parameters.reference_capacity_proxy_s

    def _validate_endurance(self, e, time_s):
        for key in ("time_s", "spent_proxy_s", "charged_proxy_s", "recovered_proxy_s",
                    "overflow_proxy_s", "clear_s"):
            number(getattr(e, key), key)
        if e.spent_proxy_s > self.capacity_proxy_s + 1e-9:
            raise ValueError("control-load capacity exceeded")
        if type(e.pause_requested) is not bool:
            raise ValueError("invalid endurance pause state")
        if abs(e.time_s - time_s) > 1e-8:
            raise ValueError("endurance/body clock mismatch")

    def step(self, i=Inputs()):
        self._validate_endurance(self.endurance, self.state.time_s)
        f = super().step(i)
        dt = f["ledger"]["dt_s"]
        rows = self.pain.last["regions"]
        raw_exposure = max(r["thalamic_relay_proxy"] for r in rows)
        # The intensity display pause does not erase the ascending signal.
        exposure = max(r["thalamic_relay_proxy"] * r["PAG_RVM_gain_proxy"] for r in rows)
        e = self.endurance
        charge = exposure * dt
        quiet = exposure < QUIET_EXPOSURE
        recovery_allowance = RECOVERY_RATE * dt * max(0.0, 1 - exposure / QUIET_EXPOSURE)
        recovered = min(e.spent_proxy_s + charge, recovery_allowance)
        unbounded_spent = e.spent_proxy_s + charge - recovered
        overflow = max(0.0, unbounded_spent - self.capacity_proxy_s)
        e.spent_proxy_s = min(self.capacity_proxy_s, unbounded_spent)
        e.charged_proxy_s += charge
        e.recovered_proxy_s += recovered
        e.overflow_proxy_s += overflow
        e.time_s = self.state.time_s
        used_fraction = e.spent_proxy_s / self.capacity_proxy_s
        if used_fraction >= PAUSE_AT_USED_FRACTION:
            e.pause_requested = True
            e.clear_s = 0.0
        elif e.pause_requested:
            if quiet and used_fraction < RELEASE_BELOW_USED_FRACTION:
                e.clear_s += dt
                if e.clear_s >= CLEAR_HOLD_S:
                    e.pause_requested = False
                    e.clear_s = 0.0
            else:
                e.clear_s = 0.0
        else:
            e.clear_s = 0.0
        self._validate_endurance(e, self.state.time_s)
        f["resilience"] = {
            "target_multiplier": self.parameters.multiplier,
            "reference_is_measured_human": False,
            "capacity_proxy_s": self.capacity_proxy_s,
            "raw_sensory_exposure_proxy": raw_exposure,
            "control_exposure_proxy": exposure,
            "used_fraction": used_fraction,
            "remaining_proxy_s": self.capacity_proxy_s - e.spent_proxy_s,
            "state": asdict(e),
            "ledger": {"dt_s": dt, "charged_proxy_s": charge,
                       "recovered_proxy_s": recovered, "overflow_proxy_s": overflow},
            "nonessential_task_pause_request": e.pause_requested,
            "pause_executed": False,
            "protective_warning_overridden": False,
        }
        return f

    def body_checkpoint(self):
        return super().checkpoint()

    def checkpoint(self):
        payload = {"schema": SCHEMA, "parameters": asdict(self.parameters),
                   "body": self.body_checkpoint(), "endurance": asdict(self.endurance),
                   "endurance_origin": self.endurance_origin,
                   "baseline_fingerprint": baseline_fingerprint()}
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        return {"payload": deepcopy(payload),
                "sha256": hashlib.sha256(encoded.encode()).hexdigest()}

    @classmethod
    def from_body_checkpoint(cls, checkpoint, *, multiplier=20,
                             reference_capacity_proxy_s=60, table=None):
        base = BodyLoop.restore(checkpoint, table)
        obj = cls(base.table, asdict(base.state), multiplier=multiplier,
                  reference_capacity_proxy_s=reference_capacity_proxy_s,
                  body_to_pain=base.body_to_pain, regional_guard=base.regional_guard,
                  breath_gain=base.pain.gain)
        obj.__dict__.update(base.__dict__)
        return obj

    @classmethod
    def restore(cls, checkpoint, table=None):
        try:
            c = deepcopy(checkpoint)
            if set(c) != {"payload", "sha256"}:
                raise ValueError("invalid endurance checkpoint envelope")
            p = c["payload"]
            encoded = json.dumps(p, sort_keys=True, allow_nan=False)
            if c["sha256"] != hashlib.sha256(encoded.encode()).hexdigest() or p["schema"] != SCHEMA:
                raise ValueError("endurance checkpoint integrity/version mismatch")
            if p["baseline_fingerprint"] != baseline_fingerprint():
                raise ValueError("retained source fingerprint mismatch")
            obj = cls.from_body_checkpoint(p["body"], table=table, **p["parameters"])
            obj.endurance = Endurance(**p["endurance"])
            obj.endurance_origin = deepcopy(p["endurance_origin"])
            obj._validate_endurance(obj.endurance, obj.state.time_s)
            number(obj.endurance_origin["time_s"], "endurance origin clock",
                   obj.origin["time_s"], obj.state.time_s)
            obj._validate_endurance(Endurance(**obj.endurance_origin), obj.endurance_origin["time_s"])
            origin = obj.endurance_origin
            expected = origin["spent_proxy_s"] + obj.endurance.charged_proxy_s - origin["charged_proxy_s"]
            expected -= obj.endurance.recovered_proxy_s - origin["recovered_proxy_s"]
            expected -= obj.endurance.overflow_proxy_s - origin["overflow_proxy_s"]
            if abs(expected - obj.endurance.spent_proxy_s) > 1e-7:
                raise ValueError("endurance dose ledger mismatch")
            return obj
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError("malformed endurance checkpoint") from e
