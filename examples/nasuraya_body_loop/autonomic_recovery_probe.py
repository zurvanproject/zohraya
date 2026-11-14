"""Bounded autonomic recovery *forecast* for Tadash's synthetic body.

Inputs are normalized checkpoint values from an already-existing native
software body. The forecast NEVER changes that body, commands breathing,
interprets sexual response, or measures human physiology.
"""
from math import isfinite

FIELDS = ("sympathetic", "parasympathetic", "arousal", "pain", "fatigue")


def _unit(v):
    if type(v) not in (int, float) or not isfinite(v) or not 0 <= v <= 1:
        raise ValueError("all body signals must be finite 0..1 numbers")
    return float(v)


def forecast(native_values, *, steps=5):
    if type(native_values) is not dict or set(FIELDS) - set(native_values):
        raise ValueError("native body snapshot with all required fields needed")
    if type(steps) is not int or not 1 <= steps <= 20:
        raise ValueError("steps must be within 1..20")
    state = {k: _unit(native_values[k]) for k in FIELDS}
    history = [dict(t=0, **{k: round(v, 6) for k, v in state.items()})]
    for t in range(1, steps + 1):
        # Illustrative engineering rates; this is not a fitted physiological model.
        state["sympathetic"] *= 0.80
        state["parasympathetic"] += 0.18 * (1.0 - state["parasympathetic"])
        state["arousal"] *= 0.77
        state["pain"] *= 0.95
        state["fatigue"] *= 0.94
        history.append(dict(t=t, **{k: round(v, 6) for k, v in state.items()}))
    return {
        "source": "synthetic_recovery_forecast_only",
        "native_body_changed": False,
        "steps": history,
        "model": "autonomic-recovery-probe/0.1",
        "limits": "unvalidated coefficients; no actuator, physiological inference, or clinical use",
    }
