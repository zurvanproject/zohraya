"""Deterministic toy identification benchmark, NOT a biomechanics calibration.

The synthetic oracle is intentionally distinct from the adaptive predictor;
only observed training labels enter updates. Held-out feature pairs are never
used in training, and baseline/post-training tests see the exact same holdouts.
"""
import json
import math
from pathlib import Path


class LinearResponse:
    """One-step normalized LMS on dimensionless torque features."""
    def __init__(self):
        self.weights = [0.0, 0.0, 0.0]

    def predict(self, tail_norm, ankle_norm):
        z = (1.0, tail_norm, ankle_norm)
        return sum(w * x for w, x in zip(self.weights, z))

    def learn(self, tail_norm, ankle_norm, observed_displacement_m, eta=0.25):
        z = (1.0, tail_norm, ankle_norm)
        error = observed_displacement_m - self.predict(tail_norm, ankle_norm)
        scale = eta * error / (1.0 + sum(x*x for x in z))
        self.weights = [max(-0.1, min(0.1, w + scale*x))
                        for w, x in zip(self.weights, z)]
        return error


def synthetic_response(tail_norm, ankle_norm, *, noise_seed):
    # Hidden coefficients are the explicit toy oracle, never read by LinearResponse.
    # Values are artificial displacements (m), not measured physical dynamics.
    return (0.006 - 0.011 * tail_norm + 0.008 * ankle_norm
            + 0.00005 * math.sin(noise_seed * 3.19))


def fixtures(n, offset):
    for k in range(offset, offset + n):
        # Distinct deterministic joint excitations; holdout indices disjoint.
        t = math.sin(k * 0.28) * math.cos(k * 0.037)
        a = math.cos(k * 0.19) * math.sin(k * 0.071 + 0.5)
        yield (t, a, synthetic_response(t, a, noise_seed=k))


def rmse_m(model, examples):
    error2 = [(truth - model.predict(t, a))**2 for t, a, truth in examples]
    return math.sqrt(sum(error2) / len(error2))


def evaluate():
    training = tuple(fixtures(240, 0))
    holdout = tuple(fixtures(80, 10000))
    model = LinearResponse()
    initial = rmse_m(model, holdout)
    for t, a, y in training:
        model.learn(t, a, y)
    final = rmse_m(model, holdout)
    return {
        "schema": "nasuraya-synthetic-learning-benchmark/0.1",
        "training_samples": len(training),
        "heldout_samples": len(holdout),
        "training_indices": "0..239",
        "heldout_indices": "10000..10079",
        "pre_holdout_rmse_mm": round(initial * 1000, 6),
        "post_holdout_rmse_mm": round(final * 1000, 6),
        "improvement_pct": round((initial - final) / initial * 100, 3),
        "weights_learned": [round(x, 8) for x in model.weights],
        "result_class": "deterministic_synthetic_regression_not_physical_validation",
        "real_world_generalization": "UNTESTED",
        "real_proprioception": False,
        "model_api_calls": 0,
    }


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return int(report["post_holdout_rmse_mm"] >= report["pre_holdout_rmse_mm"])


if __name__ == "__main__":
    raise SystemExit(main())
