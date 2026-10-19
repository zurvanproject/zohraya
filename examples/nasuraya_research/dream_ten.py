"""Dream Ten: bounded, offline counterfactual replay and held-out gate.

This is a deterministic learning *experiment*, never a write to canonical body.
The real native-body trial adapter supplies trial rows; this module searches
a scalar cautiousness policy over immutable recorded step observations.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Step:
    support: float
    route_error_m: float
    fuel_j: float
    valid: bool

    def __post_init__(self):
        if type(self.valid) is not bool:
            raise ValueError("recorded validity must be boolean")
        if not (0 <= self.support <= 1 and self.route_error_m >= 0 and self.fuel_j >= 0
                and all(math.isfinite(x) for x in (self.support, self.route_error_m, self.fuel_j))):
            raise ValueError("invalid recorded step")

def score(rows):
    if not rows:
        raise ValueError("empty outcome")
    return sum(r.route_error_m for r in rows)/len(rows)

def summary(rows):
    if not rows or not all(isinstance(x, Step) for x in rows):
        raise ValueError("nonempty native Step observations required")
    return dict(mean_error_m=score(rows), fuel_j=sum(x.fuel_j for x in rows),
                valid_steps=sum(x.valid for x in rows), steps=len(rows),
                mean_support=sum(x.support for x in rows)/len(rows),
                minimum_support=min(x.support for x in rows))


def dream(training, candidate_rollout, held_out_rollout):
    """Select on train only; inspect held-out baseline/winner once, then stop.

    Callers must pair fresh simulator bodies, fixed references and disjoint
    initial states. `training` is a measured baseline, checked against the callback
    baseline rollout. Held-out failure never triggers another candidate search.
    Step.fuel_j denotes total consumed fuel + anaerobic reserve in joules.
    """
    summary(training)
    baseline = candidate_rollout(1.0, "train")
    if list(baseline) != list(training):
        raise ValueError("training observations differ from native baseline")
    options = []
    for scale in (0.25, 0.5, 0.75, 1.0):
        rows = baseline if scale == 1.0 else candidate_rollout(scale, "train")
        metrics = summary(rows)
        if len(rows) != len(training):
            raise ValueError("paired training trials required")
        options.append(dict(scale=scale, safe=all(x.valid for x in rows), **metrics))
    safe_options = [x for x in options if x["safe"]]
    if not safe_options:
        return dict(accepted=False, reason="no safe training candidate", train_options=options)
    selected = min(safe_options, key=lambda x: (x["mean_error_m"], x["fuel_j"], -x["scale"]))
    # Selection is locked before any test callback is invoked.
    fixed_test = held_out_rollout(1.0, "test")
    adaptive_test = held_out_rollout(selected["scale"], "test")
    fixed, learned = summary(fixed_test), summary(adaptive_test)
    if len(fixed_test) != len(adaptive_test):
        raise ValueError("paired held-out native trials required")
    improvement = (fixed["mean_error_m"]-learned["mean_error_m"])/max(fixed["mean_error_m"], 1e-12)
    gates = dict(changed_policy=selected["scale"] != 1.,
        error_improved_20_percent=improvement >= .20 and learned["mean_error_m"] < fixed["mean_error_m"],
        all_valid=learned["valid_steps"] == learned["steps"],
        fuel_within_5_percent=learned["fuel_j"] <= 1.05*fixed["fuel_j"],
        support_not_worse=learned["minimum_support"] >= fixed["minimum_support"]-1e-9)
    return dict(accepted=all(gates.values()), learned_scale=selected["scale"],
                reason="held-out gates passed" if all(gates.values()) else "held-out improvement not confirmed",
                gates=gates, train_options=options, test_relative_improvement=improvement,
                baseline_test_error_m=fixed["mean_error_m"], learned_test_error_m=learned["mean_error_m"],
                learned_test_all_valid=gates["all_valid"],
                baseline_fuel_j=fixed["fuel_j"], learned_fuel_j=learned["fuel_j"],
                baseline_test=fixed, learned_test=learned,
                scope="bounded native simulation experiment; no body activation")

if __name__ == "__main__":
    raise SystemExit("Use python -m examples.nasuraya_research.dream_ten_native --output NEW_DIRECTORY")
