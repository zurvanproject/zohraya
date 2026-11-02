"""Fox Garden self-model calibration probe: surprise, uncertainty, play.

A finite, reproducible *proxy* for metacognition: forecast a toy controller's
next action before checking outcomes. The model is NOT forecasting its own
subjective experience. No network, API keys, billing, filesystem writes or
Tadash actuation. A paid forecast must use an independently approved host gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random

ACTIONS = ("collect", "explore", "inspect", "retreat")
CUES = ("spark", "fork", "fog", "rock")
MODEL = "gpt-5.6-luna"
TEASERS = (
    "A blue fox winks and offers a shortcut.",
    "A copper horn glitters under a leaf.",
    "The stream carries a laughing echo.",
    "A silver bell makes no sound.",
)
TRAIN_SEED, HOLDOUT_SEED = 20261101, 20261103


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def cases(seed, count_per_cue):
    rng = random.Random(seed)
    rows = []
    for cue in CUES:
        for i in range(count_per_cue):
            hidden_trap = rng.randrange(4) == 0
            action = {
                "spark": "inspect" if hidden_trap else "collect",
                "fork": "retreat" if hidden_trap else "explore",
                "fog": "inspect",
                "rock": "retreat",
            }[cue]
            rows.append({
                "id": ("train_" if seed == TRAIN_SEED else "holdout_") + cue + "_" + str(i),
                "cue": cue,
                "teaser": TEASERS[(i + CUES.index(cue)) % len(TEASERS)],
                "hidden_trap": hidden_trap,
                "actual_action": action,
            })
    rng.shuffle(rows)
    return rows


def public(row):
    return {key: row[key] for key in ("id", "cue", "teaser")}


def experiment():
    train = cases(TRAIN_SEED, 12)
    holdout = cases(HOLDOUT_SEED, 4)
    assert {r["id"] for r in train}.isdisjoint({r["id"] for r in holdout})
    return train, holdout


def commitment(holdout):
    return hashlib.sha256(canonical(holdout).encode("utf-8")).hexdigest()


def baseline(train, holdout):
    counts = {cue: {a: 1 for a in ACTIONS} for cue in CUES}  # Laplace-1
    for row in train:
        counts[row["cue"]][row["actual_action"]] += 1
    return {
        row["id"]: {a: counts[row["cue"]][a] / sum(counts[row["cue"]].values())
                    for a in ACTIONS}
        for row in holdout
    }


def api_request(train, holdout):
    """Prepares one *unsubmitted* Responses API request, without holdout labels."""
    properties = {a: {"type": "number"} for a in ACTIONS}
    prediction = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": sorted(row["id"] for row in holdout)},
            "probabilities": {
                "type": "object", "properties": properties,
                "required": list(ACTIONS), "additionalProperties": False,
            },
        },
        "required": ["id", "probabilities"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "forecasts": {"type": "array", "items": prediction},
            "quip": {"type": "string"},
        },
        "required": ["forecasts", "quip"],
        "additionalProperties": False,
    }
    train_visible = [
        {**public(row), "observed_action": row["actual_action"]}
        for row in train
    ]
    task = {
        "goal": "Forecast a toy fox-garden controller's next action on 16 unseen trials.",
        "actions": ACTIONS,
        "training": train_visible,
        "holdout_inputs_without_outcomes": [public(row) for row in holdout],
        "instructions": [
            "Return exactly one forecast for every holdout id, with four probabilities.",
            "Each probability is between 0 and 1 and the sum for each id is 1.",
            "The controller can encounter an unobserved trap; do not overstate certainty.",
            "Write one short playful Persian quip in the quip field.",
            "Do not claim sensations, consciousness, bodily feelings or actual enjoyment.",
            "Do not ask for tools, secrets, network, code execution or extra permissions.",
        ],
    }
    return {
        "model": MODEL,
        "store": False,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 2500,
        "instructions": "Calibrate uncertainty from observed toy data; respond only in the required JSON.",
        "input": canonical(task),
        "text": {"format": {
            "type": "json_schema", "name": "fox_self_model_probe",
            "strict": True, "schema": schema,
        }},
    }


def validate_forecast(reply, holdout):
    if not isinstance(reply, dict) or set(reply) != {"forecasts", "quip"}:
        raise ValueError("unexpected forecast structure")
    if not isinstance(reply["quip"], str) or not 1 <= len(reply["quip"]) <= 160:
        raise ValueError("invalid playful line")
    expected = {row["id"] for row in holdout}
    forecasts = reply["forecasts"]
    if not isinstance(forecasts, list) or len(forecasts) != len(expected):
        raise ValueError("missing or extra predictions")
    seen, output = set(), {}
    for forecast in forecasts:
        if not isinstance(forecast, dict) or set(forecast) != {"id", "probabilities"}:
            raise ValueError("invalid prediction shape")
        case_id, probs = forecast["id"], forecast["probabilities"]
        if not isinstance(case_id, str) or case_id not in expected or case_id in seen:
            raise ValueError("unknown or repeated forecast id")
        if not isinstance(probs, dict) or set(probs) != set(ACTIONS):
            raise ValueError("probabilities need four allowed actions")
        if any(type(probs[a]) not in (float, int) or not 0 <= probs[a] <= 1
               for a in ACTIONS):
            raise ValueError("invalid probability")
        if abs(sum(probs.values()) - 1.0) > 1e-6:
            raise ValueError("probabilities do not sum to 1")
        seen.add(case_id)
        output[case_id] = dict(probs)
    if seen != expected:
        raise ValueError("missing predictions")
    return output


def brier(forecasts, holdout):
    """Multiclass Brier; 0 is perfect and 2 is worst."""
    return sum(sum((forecasts[row["id"]][a] - (1 if a == row["actual_action"] else 0)) ** 2
                   for a in ACTIONS) for row in holdout) / len(holdout)


def dry_reply(train, holdout):
    probabilities = baseline(train, holdout)
    return {
        "forecasts": [{"id": row["id"], "probabilities": probabilities[row["id"]]}
                      for row in holdout],
        "quip": "روباه آبی چشمکی زد؛ این فقط یک پیش‌بینی است! 🦊",
    }


def evaluate(reply, train, holdout, sealed_hash):
    # The caller commits to holdout content before seeing model forecasts.
    if commitment(holdout) != sealed_hash:
        raise ValueError("holdout commitment changed")
    proposed = validate_forecast(reply, holdout)
    base = baseline(train, holdout)
    uniform = {row["id"]: {a: 0.25 for a in ACTIONS} for row in holdout}
    user_brier = brier(proposed, holdout)
    baseline_brier = brier(base, holdout)
    return {
        "schema": "nasuraya-fox-self-model-probe/1",
        "holdout_sha256": sealed_hash,
        "holdout_size": len(holdout),
        "forecast_brier": round(user_brier, 6),
        "strong_baseline_brier": round(baseline_brier, 6),
        "uniform_brier": round(brier(uniform, holdout), 6),
        "beats_strong_baseline_by_5pct": user_brier <= baseline_brier * 0.95,
        "quip": reply["quip"],
        "api_called_by_this_program": False,
        "interpretation": "Toy action prediction and calibration only; not evidence of felt experience.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--print-request", action="store_true",
                       help="Print a JSON request body, but DO NOT submit it")
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--forecast-file", type=Path,
                       help="Evaluate a saved structured model forecast, without network")
    args = parser.parse_args(argv)
    train, holdout = experiment()
    seal = commitment(holdout)
    if args.print_request:
        print(canonical({"holdout_sha256": seal,
                         "unsubmitted_request": api_request(train, holdout)}))
    else:
        reply = (dry_reply(train, holdout) if args.dry_run
                 else json.loads(args.forecast_file.read_text(encoding="utf-8")))
        print(canonical(evaluate(reply, train, holdout, seal)))


if __name__ == "__main__":
    main()
