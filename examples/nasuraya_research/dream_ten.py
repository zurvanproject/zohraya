"""Dream Ten: bounded, offline counterfactual replay and held-out gate.

This is a deterministic learning *experiment*, never a write to canonical body.
The real native-body trial adapter supplies trial rows; this module searches
a scalar cautiousness policy over immutable recorded step observations.
"""
from dataclasses import dataclass
import json
import math

@dataclass(frozen=True)
class Step:
    support: float
    route_error_m: float
    fuel_j: float
    valid: bool

    def __post_init__(self):
        if not (0 <= self.support <= 1 and self.route_error_m >= 0 and self.fuel_j >= 0
                and all(math.isfinite(x) for x in (self.support, self.route_error_m, self.fuel_j))):
            raise ValueError("invalid recorded step")

def score(rows):
    if not rows:
        raise ValueError("empty outcome")
    return sum(r.route_error_m for r in rows)/len(rows)

def dream(training, candidate_rollout, held_out_rollout):
    """Candidate rollouts must be supplied by an independently executed native simulator.

    Never mistake rescaling recorded error for actual simulated improvement.
    A callable takes (scale, split) and returns actual Step observations.
    """
    if not training or any(not isinstance(r, Step) for r in training):
        raise ValueError("native training steps required")
    baseline = candidate_rollout(1.0, "train")
    options = []
    for scale in (0.25, 0.5, 0.75, 1.0):
        rows = candidate_rollout(scale, "train")
        if not rows or not all(isinstance(x, Step) for x in rows):
            raise ValueError("invalid native candidate rollout")
        safe = all(x.valid for x in rows)
        options.append(dict(scale=scale, mean_error_m=score(rows), safe=safe,
                            fuel_j=sum(x.fuel_j for x in rows)))
    safe_options = [x for x in options if x["safe"]]
    if not safe_options:
        return dict(accepted=False, reason="no safe training candidate", options=options)
    selected = min(safe_options, key=lambda x: (x["mean_error_m"], x["fuel_j"], -x["scale"]))
    fixed_test = held_out_rollout(1.0, "test")
    adaptive_test = held_out_rollout(selected["scale"], "test")
    if not fixed_test or not adaptive_test or len(fixed_test) != len(adaptive_test):
        raise ValueError("paired held-out native trials required")
    if any(not isinstance(x, Step) for x in fixed_test+adaptive_test):
        raise ValueError("invalid held-out step")
    fixed_fuel = sum(x.fuel_j for x in fixed_test)
    learned_fuel = sum(x.fuel_j for x in adaptive_test)
    improvement = (score(fixed_test)-score(adaptive_test))/max(score(fixed_test), 1e-12)
    accepted = (selected["scale"] != 1 and improvement >= .20 and
                all(x.valid for x in adaptive_test) and
                (fixed_fuel == 0 and learned_fuel == 0 or fixed_fuel > 0 and learned_fuel <= 1.05*fixed_fuel))
    return dict(accepted=bool(accepted), learned_scale=selected["scale"],
                train_options=options, test_relative_improvement=improvement,
                baseline_test_error_m=score(fixed_test),
                learned_test_error_m=score(adaptive_test),
                learned_test_all_valid=all(x.valid for x in adaptive_test),
                baseline_fuel_j=fixed_fuel, learned_fuel_j=learned_fuel,
                scope="candidate native simulator rollouts required; no body activation")

if __name__ == "__main__":
    raise SystemExit("Provide independent native simulator rollouts; no fabricated trials.")
