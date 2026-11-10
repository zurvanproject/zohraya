"""Run a paired, pre-registered synthetic benchmark. Python standard library."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
from time import process_time_ns

from .cycle import ARMS, checkpoint, tick
from .scenarios import DEV, HOLDOUT, REGIMES, scenario


def episode(arm, first, second, root):
    path = root / "state.json"
    start = process_time_ns()
    prior = tick(arm, first, {}, root)
    frozen = checkpoint(prior)
    anchor = hashlib.sha256(frozen).digest()
    path.write_bytes(frozen)
    first_size = len(frozen)
    del prior, frozen
    recovered = json.loads(path.read_bytes())
    recovery = hashlib.sha256(checkpoint(recovered)).digest() == anchor
    final = tick(arm, second, recovered, root)
    final_size = len(checkpoint(final))
    path.unlink()
    elapsed = process_time_ns() - start
    return final["history"], recovery, max(first_size, final_size), elapsed


def scored(history, recovered, size, cpu_ns, target, initial_goal):
    prior, final = history
    reversible = target.belief is not None and target.belief != target.prior
    exact = (final["goal"], final["route"], final["belief"]) == (
        target.goal, target.route, target.belief)
    return {
        "exact": exact,
        "revision": (prior["belief"] == target.prior and final["belief"] == target.belief
                     if reversible else None),
        "false_confidence": final["belief"] != target.belief and final["confidence"] >= 0.8,
        "goal": final["goal"] == target.goal, "changed": initial_goal != target.goal,
        "memory": recovered, "peak_bytes": size, "cpu_ns": cpu_ns, "history": history,
    }


def rate(rows, metric):
    values = [row[metric] for row in rows if row[metric] is not None]
    return [sum(values), len(values)]


def summarize(rows):
    metrics = {key: rate(rows, key) for key in ("exact", "revision", "false_confidence", "goal", "memory")}
    for changed, name in ((True, "changed_goal"), (False, "unchanged_goal")):
        metrics[name] = rate([row for row in rows if row["changed"] == changed], "goal")
    metrics["cpu_ms_per_episode"] = round(sum(row["cpu_ns"] for row in rows) / len(rows) / 1e6, 4)
    metrics["peak_bytes"] = max(row["peak_bytes"] for row in rows)
    return metrics


def benchmark(seeds):
    cases = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for i, seed in enumerate(seeds):
            first, second, truth = scenario(seed)
            results = {}
            # Counterbalance execution order across the paired cases.
            order = ARMS[i % 3:] + ARMS[:i % 3]
            for arm in order:
                outputs = episode(arm, first, second, root)
                results[arm] = scored(*outputs, truth, first.proposed_goal)
            cases.append({"seed": seed, "target": asdict(truth), "arms": results})
    summary = {arm: summarize([case["arms"][arm] for case in cases]) for arm in ARMS}
    strata = {name: {arm: summarize([c["arms"][arm] for c in cases if c["target"]["regime"] == name])
                     for arm in ARMS} for name in REGIMES}
    count = len(cases)
    hypothesis = (all(100 * (summary["C"]["exact"][0] - summary[arm]["exact"][0]) >= 5 * count
                      for arm in ("A", "B"))
                  and summary["C"]["false_confidence"][0] <= summary["B"]["false_confidence"][0]
                  and all(summary["C"][key][0] >= summary["B"][key][0] for key in ("goal", "memory")))
    # Digest of every scored decision and reason, excluding machine timing only.
    stable = [{**case, "arms": {arm: {k: v for k, v in row.items() if k != "cpu_ns"}
                                for arm, row in case["arms"].items()}} for case in cases]
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    return {"summary": summary, "by_scenario": strata, "primary_supported": hypothesis,
            "paired_digest": digest, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("partition", choices=("dev", "holdout"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = benchmark(DEV if args.partition == "dev" else HOLDOUT)
    args.output.write_text(json.dumps(result, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("cases", "by_scenario")}, sort_keys=True))
