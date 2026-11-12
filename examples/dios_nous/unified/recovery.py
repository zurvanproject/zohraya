"""Deterministic workload advice from declared indices, never factual authority.

Thresholds are authored controller settings, not measured physiology or benefits.
No action, sleep, body cycle, model call, evidence update or goal update occurs.
"""
from __future__ import annotations

import hashlib
import json

STATES = {"ACTIVE", "PAUSED", "RECOVERING", "UNKNOWN", "HALTED"}
ADVICE = {"ACTIVE": "CONTINUE", "PAUSED": "PAUSE", "RECOVERING": "MONITOR_RECOVERY",
          "UNKNOWN": "REQUEST_OBSERVATION", "HALTED": "STOP"}


def _input(tick, stress, fatigue, energy, stop):
    if type(tick) is not int or not 0 <= tick <= 10**12:
        raise ValueError("tick must be an integer in [0, 10**12]")
    if type(stop) is not bool:
        raise ValueError("stop must be boolean")
    for value in (stress, fatigue, energy):
        if value is not None and (type(value) is not int or not 0 <= value <= 1000):
            raise ValueError("workload indices must be integer [0,1000] or null")
    return dict(tick=tick, stress=stress, fatigue=fatigue, energy=energy, stop=stop)


def _category(sample):
    s, f, e = (sample[k] for k in ("stress", "fatigue", "energy"))
    if None in (s, f, e):
        return "missing"
    if s >= 800 or f >= 700 or e <= 200:
        return "unsafe"
    if s <= 400 and f <= 400 and e >= 600:
        return "safe"
    return "middle"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


class RecoveryAdvisor:
    """Advisory hysteresis with idempotent ticks and a sticky user stop.

    All state is explicit and checkpointable. A checksum detects accidental
    change only, not a jointly rewritten checkpoint and checksum.
    """
    def __init__(self):
        self._state = "UNKNOWN"
        self._safe = 0
        self._last = None

    def _result(self):
        return {"schema": "dios.workload-advice.v1", "state": self._state,
                "advice": ADVICE[self._state], "consecutive_safe_samples": self._safe,
                "tick": None if self._last is None else self._last["tick"],
                "input_kind": "declared_engineering_indices",
                "empirical_recovery_benefit_measured": False,
                "execution_permitted": False, "external_actions_taken": 0}

    def read(self):
        """A passive read; no progression of time or state."""
        return self._result()

    def request_stop(self):
        """Stop independently of sensor ticks, including before any sample."""
        self._state, self._safe = "HALTED", 0
        return self.read()

    def step(self, *, tick, stress, fatigue, energy, stop=False):
        sample = _input(tick, stress, fatigue, energy, stop)
        if self._last is not None:
            if tick < self._last["tick"]:
                raise ValueError("workload time rollback")
            if tick == self._last["tick"]:
                if sample != self._last:
                    raise ValueError("conflicting workload replay")
                return self.read()
        category = _category(sample)
        if self._state == "HALTED" or stop:
            self._state, self._safe = "HALTED", 0
        elif category == "missing":
            self._state, self._safe = "UNKNOWN", 0
        elif category == "unsafe":
            self._state, self._safe = "PAUSED", 0
        elif category == "safe":
            self._safe = min(2, self._safe + 1)
            self._state = ("ACTIVE" if self._state == "ACTIVE" or self._safe >= 2
                           else "RECOVERING")
        else:
            self._safe = 0
            if self._state != "ACTIVE":
                self._state = "PAUSED"
        self._last = sample
        return self.read()

    def checkpoint(self):
        payload = {"schema": "dios.workload-checkpoint.v1", "state": self._state,
                   "safe_streak": self._safe,
                   "last_input": None if self._last is None else dict(self._last)}
        return {**payload, "sha256": _digest(payload)}

    @classmethod
    def restore(cls, checkpoint):
        if type(checkpoint) is not dict or set(checkpoint) != {
                "schema", "state", "safe_streak", "last_input", "sha256"}:
            raise ValueError("invalid workload checkpoint fields")
        if checkpoint["schema"] != "dios.workload-checkpoint.v1":
            raise ValueError("invalid workload checkpoint schema")
        state, streak = checkpoint["state"], checkpoint["safe_streak"]
        if type(state) is not str or state not in STATES:
            raise ValueError("invalid workload state")
        if type(streak) is not int or not 0 <= streak <= 2:
            raise ValueError("invalid workload streak")
        last = checkpoint["last_input"]
        if last is None:
            if state not in {"UNKNOWN", "HALTED"} or streak != 0:
                raise ValueError("invalid initial checkpoint")
        else:
            if type(last) is not dict or set(last) != {"tick", "stress", "fatigue", "energy", "stop"}:
                raise ValueError("invalid stored workload input")
            last = _input(**last)
            category = _category(last)
            valid = (
                state == "HALTED" and streak == 0
                or not last["stop"] and (
                    state == "UNKNOWN" and category == "missing" and streak == 0
                    or state == "PAUSED" and category in {"unsafe", "middle"} and streak == 0
                    or state == "RECOVERING" and category == "safe" and streak == 1
                    or state == "ACTIVE" and (
                        category == "safe" and streak in {1, 2}
                        or category == "middle" and streak == 0)))
            if not valid:
                raise ValueError("inconsistent workload checkpoint")
        payload = {k: checkpoint[k] for k in ("schema", "state", "safe_streak", "last_input")}
        if type(checkpoint["sha256"]) is not str or checkpoint["sha256"] != _digest(payload):
            raise ValueError("workload checkpoint checksum mismatch")
        result = cls()
        result._state, result._safe, result._last = state, streak, last
        return result


def describe_interfaces():
    return {"model": "authored_workload_advice", "clock": "logical_ticks",
            "indices": {name: {"unit": "per_mille_index", "range": [0, 1000]}
                        for name in ("stress", "fatigue", "energy")},
            "pause_if": {"stress_at_least": 800, "fatigue_at_least": 700,
                         "energy_at_most": 200},
            "resume_after": {"successive_safe_observations": 2, "stress_at_most": 400,
                             "fatigue_at_most": 400, "energy_at_least": 600},
            "stop_is_sticky": True, "states": sorted(STATES),
            "updates_evidence_or_goals": False, "benefit_measured": False}
