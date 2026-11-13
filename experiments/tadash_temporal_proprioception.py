"""Temporal proprioception v0.2, a conservative interpretation of simulated traces.

All inputs are simulated native MuJoCo state reports. The cause of a residual is
never inferred as a named stimulus. White noise and missing provenance lead to
abstention rather than a confident "body sensed stimulus" label.
"""
from __future__ import annotations

import math
from statistics import median

from experiments.tadash_embodied_origin import (
    FEATURES, THRESHOLD, _validated, deviation, interpret,
)

PROPRIO_KEYS = ("pelvis_yaw_rad", "tail_yaw_rad", "com_x_m", "com_y_m")
WEIGHTS = dict(FEATURES)
PERSISTENCE_THRESHOLD = 0.065
PERSISTENCE_MIN_FRAMES = 7
PERSISTENCE_MIN_CHANNELS = 2
MAX_JAGGEDNESS = 1.35
LARGE_SMOOTH_EXCURSION = 0.25
LARGE_SMOOTH_MAX_JAGGEDNESS = 0.85
LARGE_SMOOTH_MIN_SIGN_FRAMES = 4


def _normalized_residual(prediction, actual, key):
    return [
        (observed[key] - expected[key]) * WEIGHTS[key]
        for expected, observed in zip(prediction["frames"], actual["frames"])
    ]


def _temporal_features(residuals):
    positive = sum(v >= PERSISTENCE_THRESHOLD for v in residuals)
    negative = sum(v <= -PERSISTENCE_THRESHOLD for v in residuals)
    sign_persistence = max(positive, negative)
    differences = [residuals[i] - residuals[i-1] for i in range(1, len(residuals))]
    second = [differences[i] - differences[i-1] for i in range(1, len(differences))]
    jaggedness = sum(abs(v) for v in second) / max(1e-9, sum(abs(v) for v in differences))
    max_abs = max(abs(v) for v in residuals)
    persistent_small = (sign_persistence >= PERSISTENCE_MIN_FRAMES and
                        jaggedness <= MAX_JAGGEDNESS)
    smooth_large = (max_abs >= LARGE_SMOOTH_EXCURSION and
                    sign_persistence >= LARGE_SMOOTH_MIN_SIGN_FRAMES and
                    jaggedness <= LARGE_SMOOTH_MAX_JAGGEDNESS)
    return {
        "sign_persistence": sign_persistence,
        "median_normalized_residual": median(residuals),
        "max_abs_normalized_residual": max_abs,
        "jaggedness": jaggedness,
        "persistent_small": persistent_small,
        "smooth_large_excursion": smooth_large,
        "temporally_supported": persistent_small or smooth_large,
    }


def classify_temporal(reference, prediction, actual, intended_command_nm):
    """Predict -> observe -> conservative state; no oracle of true stimulus cause."""
    base = interpret(reference, prediction, actual, intended_command_nm)
    if base["state"] == "unverified":
        return {"state": "unverified", "reason": base.get("reason", "upstream_unverified"),
                "source": "read_only_mujoco_origin_v03"}
    # Previous interpret() already validates source, sample grid and command.
    features = {
        key: _temporal_features(_normalized_residual(prediction, actual, key))
        for key in PROPRIO_KEYS
    }
    supported = [name for name, info in features.items() if info["temporally_supported"]]
    residual = deviation(prediction, actual)
    if not math.isfinite(residual):
        return {"state": "unverified", "reason": "non_finite_residual",
                "source": "read_only_mujoco_origin_v03"}
    if residual <= THRESHOLD:
        state = "no_detectable_change" if abs(intended_command_nm) < 1e-9 else "command_consistent"
    elif len(supported) >= PERSISTENCE_MIN_CHANNELS:
        state = ("unexplained_change" if abs(intended_command_nm) < 1e-9
                 else "command_outcome_mismatch")
    else:
        state = "uncertain_noise_or_weak_signal"
    return {
        "state": state, "residual": residual,
        "supported_proprioceptive_channels": supported,
        "temporal_features": features,
        "source": "read_only_mujoco_origin_v03",
        "meaning": ("Unexpected coherent motion, not identification of external cause"
                    if state in ("unexplained_change", "command_outcome_mismatch")
                    else "No causal or sentience assertion"),
    }
