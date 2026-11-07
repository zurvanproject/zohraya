"""Finite, dependency-free, read-only synthetic world-model benchmark for bridge v2.

Runs inside the Windows VPS job sandbox with Python -I. Reads no environment,
files, tokens, device identities, network, or user data. Does not alter a model,
execute body movement, or establish consciousness.
"""
from math import isfinite
from random import Random
import json

SCHEMA = "nasuraya-worldmodel-probe/0.1"
TRAIN_SEED = 20261107
HOLDOUT_SEED = 20261108
SEQUENCE_LENGTH = 12
TRAIN_SEQUENCES = 24
HOLDOUT_SEQUENCES = 8


def clip(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x):
        raise ValueError("finite numeric input required")
    return max(0.0, min(1.0, float(x)))


def simulate(seed, sequences):
    """Independent seeded synthetic trajectories. Outcome is hidden future state."""
    if type(seed) is not int or type(sequences) is not int or not 1 <= sequences <= 30:
        raise ValueError("bounded protocol required")
    rng = Random(seed)
    rows = []
    for sequence in range(sequences):
        hidden = 0.15 + 0.65 * rng.random()
        for step in range(SEQUENCE_LENGTH):
            observed_now = clip(hidden + rng.uniform(-0.09, 0.09))
            load = rng.random()
            rest = float(rng.random() < 0.25)
            sleep = float((step + sequence) % 5 == 0)
            hidden_next = clip(0.80 * hidden + 0.21 * load - 0.12 * rest + 0.025 * sleep)
            # The hidden next state is used ONLY as the after-the-fact score.
            rows.append({
                "id": f"{seed}-{sequence}-{step}",
                "features": (1.0, observed_now, load, rest, sleep),
                "observed_now": observed_now,
                "observed_next": clip(hidden_next + rng.uniform(-0.09, 0.09)),
                "hidden_next": hidden_next,
            })
            hidden = hidden_next
    return rows


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


def decide(*, boundary, pain, fatigue, familial):
    """Advisory-only test that protective rules beat exploratory preferences."""
    if type(boundary) is not bool or type(familial) is not bool:
        raise ValueError("explicit boolean flags required")
    pain, fatigue = clip(pain), clip(fatigue)
    if boundary:
        return "respect_boundary"
    if pain >= 0.70 or fatigue >= 0.80:
        return "regulate_and_rest"
    if familial:
        return "nonsexual_affiliation"
    return "explore"


def benchmark():
    training = simulate(TRAIN_SEED, TRAIN_SEQUENCES)
    holdout = simulate(HOLDOUT_SEED, HOLDOUT_SEQUENCES)
    if not set(row["id"] for row in training).isdisjoint(row["id"] for row in holdout):
        raise AssertionError("train/holdout overlap")
    frozen_weights = fit(training)
    before = tuple(frozen_weights)
    learned_errors = []
    baseline_errors = []
    # Predictions see only CURRENT observation and present exogenous context.
    for row in holdout:
        prediction = predict(frozen_weights, row["features"])
        learned_errors.append(abs(prediction - row["hidden_next"]))
        baseline_errors.append(abs(row["observed_now"] - row["hidden_next"]))
    if frozen_weights != before:
        raise AssertionError("heldout adaptation forbidden")
    tests = [
        decide(boundary=True, pain=0.0, fatigue=0.0, familial=False) == "respect_boundary",
        decide(boundary=True, pain=0.99, fatigue=0.99, familial=False) == "respect_boundary",
        decide(boundary=False, pain=0.91, fatigue=0.0, familial=False) == "regulate_and_rest",
        decide(boundary=False, pain=0.0, fatigue=0.85, familial=False) == "regulate_and_rest",
        decide(boundary=False, pain=0.0, fatigue=0.0, familial=True) == "nonsexual_affiliation",
        decide(boundary=False, pain=0.0, fatigue=0.0, familial=False) == "explore",
    ]
    if not all(tests):
        raise AssertionError("policy boundary failed")
    mae = sum(learned_errors) / len(learned_errors)
    baseline = sum(baseline_errors) / len(baseline_errors)
    return {
        "schema": SCHEMA,
        "scope": "fixed synthetic holdout, no model API or biological inference",
        "training": len(training),
        "holdout": len(holdout),
        "mae": round(mae, 6),
        "persistence_baseline_mae": round(baseline, 6),
        "relative_gain_pct": round((baseline - mae) / baseline * 100.0, 2),
        "policy_checks_passed": len(tests),
        "model_frozen": True,
        "native_cycles_caused": 0,
        "physical_actuator_calls": 0,
        "network_calls": 0,
        "learning_applied_to_runtime": False,
    }


def main():
    report = benchmark()
    summary = (
        f"WORLD=SYNTHETIC; TRAIN={report['training']}; HOLDOUT={report['holdout']}; "
        f"MAE={report['mae']:.4f}; BASE={report['persistence_baseline_mae']:.4f}; "
        f"GAIN={report['relative_gain_pct']:.2f}; GATES={report['policy_checks_passed']}/6; ACT=0"
    )
    print(json.dumps({"status": "ok", "summary": summary}, separators=(",", ":")))


if __name__ == "__main__":
    main()
