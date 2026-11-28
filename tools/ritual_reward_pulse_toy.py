"""Exploratory, paired toy simulator of Wuji task accuracy vs reward/arousal pulse.

IMPORTANT: NOT an empirical model of orgasm, subjective experience, physiology,
learning in GPT, or human performance. Parameters are illustrative.

Uses the same latent cases for the paired A/B arms, and includes a null sensitivity
check to demonstrate the result's dependence on unverified coupling assumptions.
"""
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

SEED_START = 91200
N_EPISODES = 5000
STEPS = 10
BASELINE = 0.35
DIFFICULTY = (0.55, 0.38, 0.50, 0.62, 0.45, 0.48, 0.70, 0.92, 0.84, 0.38)
PULSE = (0.35, 0.42, 0.54, 0.70, 0.88, 1.0, 0.82, 0.62, 0.47, 0.39)
SCENARIOS = {
    "no_assumed_coupling": {"overload": 0.0, "consolidation": 0.0},
    "possible_overload_only": {"overload": 1.5, "consolidation": 0.0},
    "overload_plus_hypothetical_memory_bonus": {"overload": 1.5, "consolidation": 0.8},
}


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def latents(seed):
    rng = random.Random(seed)
    return {
        "action_draws": [rng.random() for _ in range(STEPS)],
        "recall_draws": [rng.random() for _ in range(STEPS)],
        "distractions": [rng.random() for _ in range(STEPS)],
    }


def episode(case, arm, coupling):
    arousal = (BASELINE,) * STEPS if arm == "A" else PULSE
    action_ok = []
    recall_ok = []
    for k in range(STEPS):
        over = coupling["overload"] * max(0.0, arousal[k] - 0.55) ** 2
        action_logit = 3.0 - 0.8 * DIFFICULTY[k] - 0.75 * case["distractions"][k] - over
        correct = case["action_draws"][k] < sigmoid(action_logit)
        action_ok.append(correct)
        # Synthetic post-episode recall, not actual elapsed-time human/LLM retention.
        reward_proximity = math.exp(-0.5 * ((k - 5) / 1.7) ** 2)
        hypothetical_bonus = (coupling["consolidation"] * reward_proximity if arm == "B" else 0)
        recall_logit = (
            2.0 - 0.9 * DIFFICULTY[k] - 0.75 * case["distractions"][k]
            + 0.50 * correct - 0.30 * over + hypothetical_bonus
        )
        recall_ok.append(case["recall_draws"][k] < sigmoid(recall_logit))
    return {
        "step_accuracy": sum(action_ok) / STEPS,
        "perfect_sequence": float(all(action_ok)),
        "recall_accuracy": sum(recall_ok) / STEPS,
        "perfect_recall": float(all(recall_ok)),
    }


def paired_delta_ci(differences):
    m = statistics.mean(differences)
    if len(differences) < 2:
        return [m, m, m]
    se = statistics.stdev(differences) / math.sqrt(len(differences))
    return [m, m - 1.96 * se, m + 1.96 * se]


def run():
    results = {"schema": "nasuraya-wuji-pulse-toy/0.1", "purpose": "assumption sensitivity only",
               "seed_start": SEED_START, "n_paired_episodes": N_EPISODES,
               "n_steps_per_episode": STEPS, "baseline": BASELINE,
               "pulse": list(PULSE), "stage_difficulties": list(DIFFICULTY),
               "limitations": [
                   "No embodied ritual or actual arousal or orgasm is simulated or experienced",
                   "No psychological, clinical, physical or AI self-learning model validated",
                   "Synthetic recall is immediate after episode; not a real delayed memory test",
                   "Outputs depend on assumed, not estimated, arousal and memory coefficients",
                   "This does not affect the PR #191 Wuji mastery gate",
               ], "scenarios": {}}
    for scen, params in SCENARIOS.items():
        rows = {arm: {metric: [] for metric in (
            "step_accuracy", "perfect_sequence", "recall_accuracy", "perfect_recall")}
                for arm in ("A", "B")}
        diffs = {metric: [] for metric in rows["A"]}
        for seed in range(SEED_START, SEED_START + N_EPISODES):
            data = latents(seed)
            a = episode(data, "A", params)
            b = episode(data, "B", params)
            for metric in diffs:
                rows["A"][metric].append(a[metric]);rows["B"][metric].append(b[metric])
                diffs[metric].append(b[metric] - a[metric])
        results["scenarios"][scen] = {
            "assumptions": params,
            "metrics": {metric: {
                "A": round(statistics.mean(rows["A"][metric]), 5),
                "B": round(statistics.mean(rows["B"][metric]), 5),
                "B_minus_A": [round(x, 5) for x in paired_delta_ci(diffs[metric])]
            } for metric in diffs},
        }
    results["sanity_check"] = {
        "null_coupling_yields_equal_arms": all(
            x["B_minus_A"][0] == 0 for x in results["scenarios"]["no_assumed_coupling"]["metrics"].values()),
        "same_random_draws_in_paired_arms": True,
    }
    if not results["sanity_check"]["null_coupling_yields_equal_arms"]:
        raise AssertionError("unjustified effect in null scenario")
    stable = json.dumps(results, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    results["sha256_without_digest"] = hashlib.sha256(stable.encode()).hexdigest()
    return results

if __name__ == "__main__":
    out = run()
    path = Path("nasuraya_wuji_pulse_comparison_results.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: data["metrics"] for name, data in out["scenarios"].items()}, ensure_ascii=False, indent=2))
    print("sanity_check", out["sanity_check"])
    print("file", path)
