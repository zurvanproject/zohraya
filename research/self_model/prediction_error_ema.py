"""Minimal, dependency-free prediction-error tracker for simulated agent motion.

This is an experimental component. It does not change live policy, grant
permissions, execute actions, or claim online learning or consciousness.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite
from typing import Mapping
import json


@dataclass
class PredictionState:
    error_ema: float = 0.0
    observations: int = 0


class PredictionErrorEMA:
    """Track an exponential moving average of absolute prediction error.

    Use separate instances for each measured feature (e.g. angle, energy);
    do not combine physically different units without normalization.
    """

    def __init__(self, alpha: float = 0.2, state: PredictionState | None = None):
        if not isfinite(alpha) or not 0 < alpha <= 1:
            raise ValueError("alpha must be finite and in (0, 1]")
        self.alpha = alpha
        self.state = state or PredictionState()
        if (
            not isfinite(self.state.error_ema)
            or self.state.error_ema < 0
            or self.state.observations < 0
        ):
            raise ValueError("invalid initial state")

    def observe(self, predicted: float, actual: float) -> float:
        if not isfinite(predicted) or not isfinite(actual):
            raise ValueError("measurements must be finite")
        error = abs(actual - predicted)
        if not isfinite(error):
            raise ValueError("error overflow")
        if self.state.observations == 0:
            self.state.error_ema = error
        else:
            self.state.error_ema = (
                self.alpha * error + (1 - self.alpha) * self.state.error_ema
            )
        self.state.observations += 1
        return self.state.error_ema

    def snapshot(self) -> dict:
        return {"version": 1, "alpha": self.alpha, **asdict(self.state)}

    @classmethod
    def restore(cls, snapshot: Mapping) -> "PredictionErrorEMA":
        if snapshot.get("version") != 1:
            raise ValueError("unsupported snapshot version")
        observations = snapshot["observations"]
        if type(observations) is not int:
            raise ValueError("observations must be an integer")
        return cls(
            alpha=float(snapshot["alpha"]),
            state=PredictionState(
                error_ema=float(snapshot["error_ema"]),
                observations=observations,
            ),
        )


if __name__ == "__main__":
    tracker = PredictionErrorEMA()
    for expected, observed in [(1.0, 1.3), (1.2, 1.1), (1.1, 1.15)]:
        tracker.observe(expected, observed)
    print(json.dumps(tracker.snapshot(), sort_keys=True))
