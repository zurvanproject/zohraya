"""Evaluate paired binary prediction performance, not phenomenal consciousness."""
from __future__ import annotations
import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

def _prob(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be numeric")
    p = float(value)
    if not 0 <= p <= 1:
        raise ValueError(f"{name} must be finite in [0, 1]")
    return p

def evaluate_binary_predictions(trials: Sequence[Mapping[str, Any]], *, min_trials: int = 30) -> dict[str, Any]:
    """Brier improvement vs baseline; deterministic paired bootstrap if enough trials.

    Results are descriptive; no independence, held-out evaluation or source
    provenance is verified. A positive result is NOT evidence of sentience.
    """
    if isinstance(trials, (str, bytes)) or not isinstance(trials, (list, tuple)):
        raise TypeError("trials must be a list")
    if not 1 <= len(trials) <= 10000:
        raise ValueError("trials must have 1-10000 records")
    if isinstance(min_trials, bool) or not isinstance(min_trials, int) or not 2 <= min_trials <= 10000:
        raise ValueError("min_trials invalid")
    pairs = []
    for row in trials:
        if not isinstance(row, Mapping):
            raise TypeError("each trial must be an object")
        p = _prob(row.get("prediction"), "prediction")
        b = _prob(row.get("baseline"), "baseline")
        outcome = row.get("outcome")
        if type(outcome) is not int or outcome not in (0, 1):
            raise ValueError("outcome must be integer 0 or 1")
        pairs.append(((p - outcome) ** 2, (b - outcome) ** 2))
    n = len(pairs)
    ours = sum(p for p, _ in pairs) / n
    baseline = sum(b for _, b in pairs) / n
    delta = baseline - ours
    relative = 100 * delta / baseline if baseline else None
    relative_status = "baseline_zero" if baseline == 0 else "finite"
    # Valid probabilities can produce a subnormal, nonzero baseline Brier.
    # Its relative percentage may overflow even though all inputs are finite.
    if relative is not None and not math.isfinite(relative):
        relative, relative_status = None, "numeric_overflow"
    interval = None
    if n >= min_trials:
        rng = random.Random(281)
        bootstrap = []
        for _ in range(1000):
            sample = [pairs[rng.randrange(n)] for _ in range(n)]
            bootstrap.append(sum(b - p for p, b in sample) / n)
        bootstrap.sort()
        interval = [round(bootstrap[25], 6), round(bootstrap[974], 6)]
    return {
        "schema": "dios.nous.brier_probe.v1",
        "trials": n, "model_brier": round(ours, 6),
        "baseline_brier": round(baseline, 6),
        "improvement_delta": round(delta, 6),
        "relative_improvement_pct": round(relative, 3) if relative is not None else None,
        "relative_improvement_status": relative_status,
        "paired_bootstrap_95ci": interval,
        "sufficient_for_preliminary_stats": n >= min_trials,
        "evidence_supports": "predictive performance on the supplied binary tasks",
        "evidence_does_not_prove": ["subjective experience", "sentience", "autonomy rights"],
        "limitations": "Independence, prespecification, representative sampling and blinded tests are not verified.",
    }
