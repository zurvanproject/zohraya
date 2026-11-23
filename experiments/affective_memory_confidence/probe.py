"""Run with python3 probe.py. Requires git and Python 3.10+. All states are temporary."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
EXT = HERE.parents[1] / "runtimes/tadash_body/retained_extensions"
MODULES = ("nasuraya_affective_layer_v01", "nasuraya_decision_core_v1", "nasuraya_emotion_spectrum_v01")


def observe(directory):
    sys.path.insert(0, str(directory))
    import nasuraya_affective_layer_v01 as model

    cases = {
        "neutral": [("neutral", 0)] * 3,
        "zero_confidence": [("warmth", 0)] * 3,
        "confirmed": [("warmth", 1)] * 3,
        "known_then_unconfirmed": [("warmth", 1), ("warmth", 0), ("warmth", 0)],
        "known_then_neutral": [("warmth", 1), ("neutral", 0), ("neutral", 0)],
    }
    rows = {}
    for label, history in cases.items():
        state = model.initial_state()
        def step(key, signals, confidence):
            return model.transition(state, {"id": key, "source": "synthetic_fixture",
                "partner": "fixture_partner", "signals": signals, "confidence": confidence,
                "elapsed_hours": 1.0 if key == "absence" else 0.0})
        for index, (kind, confidence) in enumerate(history):
            signals = {"warmth": 1, "reliability": 1} if kind == "warmth" else {}
            step(str(index), signals, confidence)
        record = step("absence", {"absence": 1}, 1)
        rows[label] = {"relationship": state["relationships"].get("fixture_partner"),
                       "longing": state["affect"]["longing"], "sadness": state["affect"]["sadness"],
                       "action": record["plan"]["action"], "action_without_affect": record["without_affect"],
                       "recorded_events": len(state["episodes"])}
    return rows


def read_cases(directory):
    # Independent processes prevent module cache or mutable state crossing conditions.
    command = [sys.executable, "-B", "-I", str(Path(__file__).resolve()), "--observe", str(directory)]
    return json.loads(subprocess.check_output(command, text=True))


def main():
    original = read_cases(EXT)
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp)
        for name in MODULES:
            shutil.copyfile(EXT / (name + ".py"), candidate / (name + ".py"))
        subprocess.run(["git", "apply", str(HERE / "guard.patch")], cwd=candidate, check=True)
        fixed = read_cases(candidate)
    checks = {
        "baseline_reproduced": original["zero_confidence"]["longing"] > original["neutral"]["longing"],
        "unsupported_matches_neutral": fixed["zero_confidence"] == fixed["neutral"],
        "no_unsupported_relationship": fixed["zero_confidence"]["relationship"] is None,
        "unsupported_does_not_increment_prior_relationship": fixed["known_then_unconfirmed"] == fixed["known_then_neutral"],
        "positive_control_preserved": original["confirmed"] == fixed["confirmed"],
        "positive_control_changes_plan": fixed["confirmed"]["action"] != fixed["confirmed"]["action_without_affect"],
        "only_known_partner_has_longing": fixed["neutral"]["longing"] == 0 < fixed["confirmed"]["longing"],
        "all_observations_retained": all(row["recorded_events"] == 4 for row in fixed.values()),
    }
    print(json.dumps({"scope": "synthetic_engineering_state", "original": original,
                      "candidate": fixed, "checks": checks}, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--observe":
        print(json.dumps(observe(Path(sys.argv[2]))))
    else:
        raise SystemExit(main())
