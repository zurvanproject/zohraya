"""Bounded contextual decision learning from *synthetic* Tadash affect fixtures.

Uses four states supported by the previous affect model. Learns an action-value
table only from observed synthetic reward receipts. The reward-generating fixture
is not the training policy. A frozen table is evaluated on fresh jittered
situations and independent seeds. This never actuates the native body.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3

from experiments import tadash_developmental_affect as affect
from experiments import tadash_motion_episode as evidence

SCHEMA = "tadash-affect-decision-learning/1"
ACTIONS = ("explore", "repeat", "simplify", "rest")
CONTEXTS = {
    "curious": {"curiosity": .80, "calm": .80, "frustration": .10, "confidence": .75},
    "frustrated": {"curiosity": .30, "calm": .40, "frustration": .80, "confidence": .20},
    "tired": {"curiosity": .30, "calm": .20, "frustration": .35, "confidence": .20},
    "steady": {"curiosity": .40, "calm": .80, "frustration": .10, "confidence": .60},
}
TRAIN_REPEATS = 12
HOLDOUT_REPEATS = 12
MIN_GAIN_VS_REPEAT = .08
MIN_GAIN_VS_PERMUTED = .08
MIN_CONTEXT_WINS = 3
LIMITS = {"max_frozen_rows": 16, "training_rewards": 192, "holdout_contexts": 48}


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(x):
    return hashlib.sha256(canonical(x).encode("utf-8")).hexdigest()


def context(state):
    affect.check_state(state)
    if state["frustration"] > .6:
        return "frustrated"
    if state["calm"] < .35:
        return "tired"
    if state["curiosity"] > .65:
        return "curious"
    return "steady"


def jittered(state, name, ix):
    """Jitter features using a disjoint heldout seed; never alter its context."""
    out = {}
    rng = random.Random(f"heldout|{name}|{ix}")
    for key, value in state.items():
        out[key] = max(0., min(1., value + rng.uniform(-.025, .025)))
    affect.check_state(out)
    if context(out) != name:
        raise ValueError("Frozen context was crossed by holdout jitter")
    return out


def synthetic_reward(state, action, seed):
    """Authored task utility and reproducible sensor noise; NOT body experience."""
    affect.check_state(state)
    if action not in ACTIONS or not isinstance(seed, str) or len(seed) > 100:
        raise ValueError("Invalid synthetic feedback request")
    q, c, f, k = (state[x] for x in ("curiosity", "calm", "frustration", "confidence"))
    # These are explicit fictional decision consequences, not measured biology.
    formulas = {
        "explore": .15 + .65*q + .20*k - .55*f - .25*(1-c),
        "repeat": .45 + .15*c + .10*k - .13*f - .23*q,
        "simplify": .18 + .62*f + .22*(1-k) - .10*q,
        "rest": .22 + .50*(1-c) + .19*f - .10*k,
    }
    noise = random.Random("reward-fixture-v1|" + seed + "|" + action).uniform(-.02, .02)
    return float(max(0., min(1., formulas[action] + noise)))


class Table:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("CREATE TABLE IF NOT EXISTS q (context TEXT, action TEXT, count INTEGER, mean REAL, PRIMARY KEY(context,action))")
        self.db.execute("CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, source TEXT NOT NULL, context TEXT NOT NULL, action TEXT NOT NULL, reward REAL NOT NULL)")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for c in CONTEXTS:
                for a in ACTIONS:
                    self.db.execute("INSERT OR IGNORE INTO q VALUES (?, ?, 0, 0.0)", (c, a))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def observe(self, identifier, state, action, reward, source="synthetic_fixture"):
        c = context(state)
        if source != "synthetic_fixture" or action not in ACTIONS:
            raise ValueError("Synthetic fixture scope required")
        if type(identifier) is not str or len(identifier) > 80:
            raise ValueError("Invalid feedback id")
        if type(reward) not in (float, int) or not math.isfinite(reward) or not 0. <= reward <= 1.:
            raise ValueError("Finite normalized synthetic reward required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT context,action,reward FROM feedback WHERE id=?", (identifier,)).fetchone()
            if prior:
                if (prior[0],prior[1],prior[2]) != (c,action,float(reward)):
                    raise ValueError("Conflicting feedback replay")
                self.db.execute("COMMIT")
                return False
            n, mean = self.db.execute("SELECT count,mean FROM q WHERE context=? AND action=?", (c,action)).fetchone()
            new_mean = mean + (float(reward) - mean) / (n+1)
            self.db.execute("UPDATE q SET count=?, mean=? WHERE context=? AND action=?", (n+1,new_mean,c,action))
            self.db.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?)", (identifier,source,c,action,float(reward)))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def freeze(self):
        rows = self.db.execute("SELECT context,action,count,mean FROM q ORDER BY context,action").fetchall()
        if len(rows) != LIMITS["max_frozen_rows"] or any(n != TRAIN_REPEATS for c,a,n,m in rows):
            raise ValueError("Incomplete training")
        if self.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] != LIMITS["training_rewards"]:
            raise ValueError("Incomplete feedback ledger")
        values = {c: {} for c in CONTEXTS}
        for c,a,n,m in rows:
            if not (0. <= m <= 1. and math.isfinite(m)):
                raise ValueError("Corrupt mean")
            values[c][a] = m
        policy = {c: max(ACTIONS, key=lambda a: (values[c][a], -ACTIONS.index(a))) for c in CONTEXTS}
        return {"schema": SCHEMA, "source": "synthetic_fixture_training_only",
                "q_values": values, "policy": policy, "feedback_count": LIMITS["training_rewards"],
                "no_native_motion": True, "has_learned_from_reward": True}

    def close(self):
        self.db.close()


def evaluate(model, permuted, plan):
    if model["schema"] != SCHEMA or permuted["schema"] != SCHEMA:
        raise ValueError("Wrong policy model")
    keys = {key: 0. for key in ("learned","repeat","permuted")}
    contextual = {name: {key: [] for key in keys} for name in CONTEXTS}
    detail = []
    for name, state in CONTEXTS.items():
        for i in range(HOLDOUT_REPEATS):
            value = jittered(state, name, i)
            acts = {"learned": model["policy"][name],
                    "repeat": "repeat", "permuted": permuted["policy"][name]}
            scores = {k: synthetic_reward(value, action, f"holdout-v1|{name}|{i}")
                      for k, action in acts.items()}
            for key, reward in scores.items():
                keys[key] += reward
                contextual[name][key].append(reward)
            detail.append({"fixture_id": f"h-{name}-{i}", "context": name,
                           "jittered_state": value, "actions": acts, "rewards": scores})
    count = len(detail)
    if count != LIMITS["holdout_contexts"]:
        raise ValueError("Holdout count mismatch")
    means = {name: {key: sum(nums) / len(nums) for key, nums in vals.items()}
             for name, vals in contextual.items()}
    wins = sum(1 for name, val in means.items() if val["learned"] > val["repeat"] + 1e-10)
    aggregate = {k: v/count for k,v in keys.items()}
    conditions = {"better_than_repeat_by_0.08": aggregate["learned"]-aggregate["repeat"] >= MIN_GAIN_VS_REPEAT,
                  "better_than_reward_permuted_by_0.08": aggregate["learned"]-aggregate["permuted"] >= MIN_GAIN_VS_PERMUTED,
                  "at_least_three_context_wins": wins >= MIN_CONTEXT_WINS,
                  "no_holdout_weight_updates": True}
    return {"average_rewards": aggregate, "mean_by_context": means, "context_wins_vs_repeat": wins,
            "conditions": conditions, "criteria_met": all(conditions.values()), "rows": detail}


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_hash = evidence.sha(Path(__file__))
    plan = {"schema": SCHEMA, "contexts": CONTEXTS, "actions": ACTIONS,
            "train_repeats_per_context_action": TRAIN_REPEATS,
            "test_repeats_per_context": HOLDOUT_REPEATS,
            "training_seeds": "train-v1", "test_seeds": "holdout-v1",
            "learned": "incremental average reward for each state/action bin",
            "control": "always repeat; plus reward-rotated mislabeled training",
            "threshold_absolute_reward_vs_repeat": MIN_GAIN_VS_REPEAT,
            "threshold_absolute_reward_vs_permuted": MIN_GAIN_VS_PERMUTED,
            "minimum_context_wins": MIN_CONTEXT_WINS,
            "source_sha256": source_hash,
            "synthetic_only": True, "native_body_actions": 0}
    evidence.write(output / "plan.json", plan)
    phash = evidence.sha(output / "plan.json")
    evidence.write(output / "status.json", {"status": "running", "started_utc":datetime.now(timezone.utc).isoformat()})
    learned = None
    rotated = None
    try:
        learned = Table(output / "learned.sqlite")
        rotated = Table(output / "permuted.sqlite")
        receipts = []
        for cname, state in CONTEXTS.items():
            affect.check_state(state)
            if context(state) != cname:
                raise ValueError("Unstable context")
            for i in range(TRAIN_REPEATS):
                for ai, action in enumerate(ACTIONS):
                    identifier = f"train-{cname}-{i}-{action}"
                    score = synthetic_reward(state, action, f"train-v1|{cname}|{i}")
                    learned.observe(identifier, state, action, score)
                    shifted = ACTIONS[(ai+1) % len(ACTIONS)]
                    rotated_score = synthetic_reward(state, shifted, f"train-v1|{cname}|{i}")
                    rotated.observe(identifier, state, action, rotated_score)
                    receipts.append({"id":identifier,"synthetic":True,"context":cname,
                                     "chosen":action,"observed_reward":score,
                                     "permuted_negative_control_reward":rotated_score})
        evidence.write(output / "training-feedback.json", receipts)
        first = learned.freeze()
        second = rotated.freeze()
        evidence.write(output / "frozen-learned-policy.json", first)
        evidence.write(output / "frozen-negative-control.json", second)
        frozen_hash = evidence.sha(output / "frozen-learned-policy.json")
        negative_hash = evidence.sha(output / "frozen-negative-control.json")
        learned.close(); learned=None
        rotated.close(); rotated=None
        # A fresh process later can read the same SQLite files and reconstruct their tables.
        cold = Table(output / "learned.sqlite")
        try:
            recovered = cold.freeze()
        finally:
            cold.close()
        if recovered != first or evidence.sha(output / "frozen-learned-policy.json") != frozen_hash:
            raise ValueError("Cold state did not recover the learned policy")
        result = evaluate(first, second, plan)
        evidence.write(output / "holdout-evidence.json", result)
        if (evidence.sha(output / "frozen-learned-policy.json") != frozen_hash or
            evidence.sha(output / "frozen-negative-control.json") != negative_hash or
            evidence.sha(output / "plan.json") != phash or evidence.sha(Path(__file__)) != source_hash):
            raise ValueError("Source, plan or frozen policy drift")
        summary = {"schema": SCHEMA, "scope": "synthetic contextual bandit decision learning, not new Tadash motor or emotion experience",
                   "training_observations":len(receipts), "heldout_evaluations":LIMITS["holdout_contexts"],
                   "learned_policy":first["policy"], "negative_control_policy":second["policy"],
                   "holdout_average_reward":result["average_rewards"],
                   "context_wins":result["context_wins_vs_repeat"],
                   "criteria_met":result["criteria_met"],
                   "frozen_hash":frozen_hash,
                   "cold_recovery":True, "no_native_body_actuation":True,
                   "not_proven":["lived emotion","general autonomy","real-world behavioral improvement","learned motor control"],
                   "status":"complete"}
        evidence.write(output / "summary.json", summary)
        evidence.write(output / "status.json", {"status":"complete","summary_sha256":evidence.sha(output / "summary.json")},replace=True)
        return summary
    except BaseException as e:
        evidence.write(output / "status.json", {"status":"failed_or_unknown","error_type":type(e).__name__,
                                                "no_auto_restart":True},replace=True)
        raise
    finally:
        if learned is not None: learned.close()
        if rotated is not None: rotated.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(run(args.output),ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == "__main__":
    main()
