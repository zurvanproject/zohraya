"""Finite validation-gated synthetic forecast experiment, stdlib only.
Derived ridge solver: worldmodel_probe.py at e411099fdd0a321b141484ef9fca703a19b522b5.
No network, environment, files, credentials, model API or actuator access.
The saved code improves an experimental controller, not ChatGPT model weights.
"""
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from random import Random
import json

SCHEMA = "nasuraya-forecast-guard/0.1"
FOLDS = 12
MIN_VALIDATION_GAIN = 0.05
REGIMES = ("stable", "reversed_load", "persistence")
TRAIN_SEQUENCES = 24
VALIDATION_SEQUENCES = 8
TEST_SEQUENCES = 8
STEPS = 12
# Frozen before the first benchmark run; no seed search or test-driven tuning.
SEED_ORIGIN = 2026110700

def clip(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x):
        raise ValueError("finite numeric input required")
    return max(0.0, min(1.0, float(x)))


def unit(x):
    """External normalized signals are validated, never silently clipped."""
    if type(x) not in (int, float) or not isfinite(x) or not 0.0 <= x <= 1.0:
        raise ValueError("normalized input must be in [0, 1]")
    return float(x)


def fit(train):
    """Fixed ridge fit against *training* observed_next, never holdout targets."""
    if not train:
        raise ValueError("empty training")
    width = 5
    gram = [[0.0] * (width + 1) for _ in range(width)]
    for row in train:
        x = row["features"]
        y = row["observed_next"]
        for i in range(width):
            for j in range(width):
                gram[i][j] += x[i] * x[j]
            gram[i][-1] += x[i] * y
    for i in range(1, width):
        gram[i][i] += 0.05
    for i in range(width):
        pivot = max(range(i, width), key=lambda k: abs(gram[k][i]))
        gram[i], gram[pivot] = gram[pivot], gram[i]
        if abs(gram[i][i]) < 1e-12:
            raise ArithmeticError("singular training matrix")
        scalar = gram[i][i]
        gram[i] = [v / scalar for v in gram[i]]
        for other in range(width):
            if other == i:
                continue
            factor = gram[other][i]
            gram[other] = [a - factor * b for a, b in zip(gram[other], gram[i])]
    weights = tuple(gram[i][-1] for i in range(width))
    if not all(isfinite(x) for x in weights):
        raise ArithmeticError("nonfinite weights")
    return weights


def predict(weights, features):
    if len(weights) != 5 or len(features) != 5:
        raise ValueError("invalid feature vector")
    return clip(sum(a * b for a, b in zip(weights, features)))



def simulate(seed, sequences, regime):
    if type(seed) is not int or type(sequences) is not int or not 1 <= sequences <= 30:
        raise ValueError("bounded integer protocol required")
    if regime not in REGIMES:
        raise ValueError("unknown regime")
    rng = Random(seed)
    rows = []
    for sequence in range(sequences):
        hidden = 0.15 + 0.65 * rng.random()
        for step in range(STEPS):
            observed = clip(hidden + rng.uniform(-0.09, 0.09))
            load = rng.random()
            rest = float(rng.random() < 0.25)
            sleep = float((step + sequence) % 5 == 0)
            if regime == "persistence":
                following = hidden
            else:
                driving_load = load if regime == "stable" else 1.0 - load
                following = clip(0.80 * hidden + 0.21 * driving_load - 0.12 * rest + 0.025 * sleep)
            rows.append({
                "id": f"{seed}-{regime}-{sequence}-{step}",
                "features": (1.0, observed, load, rest, sleep),
                "observed_next": clip(following + rng.uniform(-0.09, 0.09)),
            })
            hidden = following
    return rows


def features_only(row):
    x = tuple(row["features"])
    if len(x) != 5 or x[0] != 1.0:
        raise ValueError("five normalized features with intercept required")
    return tuple(unit(v) for v in x)


def checked_weights(weights):
    values = tuple(weights)
    if len(values) != 5 or any(type(v) not in (int, float) or not isfinite(v) for v in values):
        raise ValueError("five finite weights required")
    return values


@dataclass(frozen=True)
class FrozenGate:
    weights: tuple
    use_model: bool
    validation_gain: float

    def forecast(self, features):
        x = features_only({"features": features})
        return predict(self.weights, x) if self.use_model else x[1]


def calibrate(weights, validation):
    """Use only labeled validation rows. No test rows/targets enter this API."""
    weights = checked_weights(weights)
    if not validation:
        raise ValueError("nonempty independent validation required")
    learned, baseline = [], []
    ids = []
    for row in validation:
        x = features_only(row)
        y = unit(row["observed_next"])
        ids.append(row["id"])
        learned.append(abs(predict(weights, x) - y))
        baseline.append(abs(x[1] - y))
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate validation observations")
    model_mae, base_mae = sum(learned) / len(learned), sum(baseline) / len(baseline)
    gain = (base_mae - model_mae) / base_mae if base_mae > 0 else 0.0
    return FrozenGate(weights, base_mae > 0 and gain >= MIN_VALIDATION_GAIN, gain)


def score(gate, test):
    if not test:
        raise ValueError("nonempty test required")
    # Seal every prediction before any test target is read.
    xs = [features_only(row) for row in test]
    guarded = tuple(gate.forecast(x) for x in xs)
    unguarded = tuple(predict(gate.weights, x) for x in xs)
    baseline = tuple(x[1] for x in xs)
    outcomes = tuple(unit(row["observed_next"]) for row in test)
    def mae(predictions):
        return sum(abs(p - y) for p, y in zip(predictions, outcomes)) / len(outcomes)
    return {"n": len(outcomes), "guarded_mae": mae(guarded),
            "unguarded_mae": mae(unguarded), "baseline_mae": mae(baseline)}


def require_disjoint(*partitions):
    seen = set()
    for rows in partitions:
        ids = [row["id"] for row in rows]
        if len(set(ids)) != len(ids) or not set(ids).isdisjoint(seen):
            raise ValueError("partition overlap or duplicate observations")
        seen.update(ids)


def benchmark():
    records = []
    for fold in range(FOLDS):
        origin = SEED_ORIGIN + 100 * fold
        training = simulate(origin, TRAIN_SEQUENCES, "stable")
        weights = fit(training)
        for index, regime in enumerate(REGIMES):
            validation = simulate(origin + 10 * index + 1, VALIDATION_SEQUENCES, regime)
            test = simulate(origin + 10 * index + 2, TEST_SEQUENCES, regime)
            require_disjoint(training, validation, test)
            gate = calibrate(weights, validation)
            before = (gate.weights, gate.use_model, gate.validation_gain)
            measured = score(gate, test)
            if (gate.weights, gate.use_model, gate.validation_gain) != before:
                raise AssertionError("test-time controller mutation")
            records.append({"fold": fold, "regime": regime,
                            "train_seed": origin, "validation_seed": origin + 10 * index + 1,
                            "test_seed": origin + 10 * index + 2,
                            "model_selected": gate.use_model,
                            "validation_gain": gate.validation_gain, **measured})
    by_regime = {}
    for regime in REGIMES:
        group = [row for row in records if row["regime"] == regime]
        totals = {key: sum(row[key] * row["n"] for row in group) / sum(row["n"] for row in group)
                  for key in ("guarded_mae", "unguarded_mae", "baseline_mae")}
        by_regime[regime] = {"folds": len(group), "test_rows": sum(row["n"] for row in group),
                             "model_selected": sum(row["model_selected"] for row in group), **totals}
    guarded = sum(row["guarded_mae"] * row["n"] for row in records) / sum(row["n"] for row in records)
    unguarded = sum(row["unguarded_mae"] * row["n"] for row in records) / sum(row["n"] for row in records)
    base = sum(row["baseline_mae"] * row["n"] for row in records) / sum(row["n"] for row in records)
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {
        "schema": SCHEMA, "scope": "synthetic; same-regime validation precedes sealed test",
        "protocol": {"folds": FOLDS, "regimes": REGIMES, "seed_origin": SEED_ORIGIN,
                     "train_sequences": TRAIN_SEQUENCES, "validation_sequences": VALIDATION_SEQUENCES,
                     "test_sequences": TEST_SEQUENCES, "steps": STEPS,
                     "minimum_validation_gain": MIN_VALIDATION_GAIN,
                     "target": "noisy observed_next; no hidden-state oracle"},
        "test_rows": sum(row["n"] for row in records),
        "guarded_mae": guarded, "unguarded_mae": unguarded, "baseline_mae": base,
        "relative_gain_vs_unguarded_pct": 100.0 * (unguarded - guarded) / unguarded,
        "relative_gain_vs_baseline_pct": 100.0 * (base - guarded) / base,
        "fallback_folds": sum(not row["model_selected"] for row in records),
        "by_regime": by_regime, "records": records, "records_sha256": sha256(canonical).hexdigest(),
        "learning_applied_to_live_runtime": False, "actuator_calls": 0,
    }


def bridge_summary(report):
    return (f"GUARD=SYNTH; N={report['test_rows']}; "
            f"MAE={report['guarded_mae']:.5f}; RAW={report['unguarded_mae']:.5f}; "
            f"BASE={report['baseline_mae']:.5f}; "
            f"FALLBACK={report['fallback_folds']}/{FOLDS * len(REGIMES)}; "
            f"SIG={report['records_sha256'][:16]}; ACT=0")


def main():
    report = benchmark()
    print(json.dumps({"status": "ok", "summary": bridge_summary(report)}, separators=(",", ":")))


if __name__ == "__main__":
    main()

