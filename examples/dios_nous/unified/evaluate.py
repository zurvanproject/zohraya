"""Frozen procedural evaluation of advisory recovery rules.

The oracle and sequences are authored independently from the engine using its
public contract, before observing candidate outputs. This is an agent-authored
software test, not an independent dataset, human review, physiological study,
or evidence of improved task performance. All pressure/fatigue/energy values
are synthetic integer indices, not measurements of subjective experience.

Protocol: dev base seed 913000, 120 episodes; holdout base seed 914000, 400
episodes. Each episode has 15 fixed boundary samples, 20 seeded random samples,
and 3 stop samples. The first holdout must run only after this evaluator has
been committed. Outputs are created exclusively and cannot overwrite prior runs.

Oracle: initial state is UNKNOWN; stop is sticky; any missing input means UNKNOWN. An unsafe sample means
PAUSED. Healthy samples need two consecutive observations to move a non-ACTIVE
state through RECOVERING to ACTIVE. Middle samples preserve ACTIVE but reset
all other non-HALTED states to PAUSED. State agreement is the metric; advice
does not determine evidence truth, goals, permission, or provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Sample:
    tick: int
    stress: int | None
    fatigue: int | None
    energy: int | None
    stop: bool = False


def episode(seed: int) -> list[Sample]:
    """Create input only; candidate outputs never affect the fixture."""
    rng = random.Random(seed)
    values = [
        (400, 400, 600), (800, 400, 600), (400, 400, 600),
        (401, 400, 600), (400, 400, 600), (400, 400, 600),
        (400, 700, 600), (None, 400, 600), (400, 400, 600),
        (400, 400, 600), (400, 400, 200), (400, 400, 201),
        (400, 400, 600), (400, 400, 600), (801, 701, 199),
    ]
    modes = ("healthy", "unsafe", "middle", "missing", "arbitrary")
    for _ in range(20):
        mode = rng.choice(modes)
        if mode == "healthy":
            sample = (rng.randrange(401), rng.randrange(401), rng.randrange(600, 1001))
        elif mode == "unsafe":
            options = [(rng.randrange(800, 1001), 200, 800),
                       (200, rng.randrange(700, 1001), 800),
                       (200, 200, rng.randrange(201))]
            sample = rng.choice(options)
        elif mode == "middle":
            sample = (rng.randrange(401, 800), rng.randrange(401, 700), rng.randrange(201, 600))
        elif mode == "missing":
            sample_list: list[int | None] = [200, 200, 800]
            sample_list[rng.randrange(3)] = None
            sample = tuple(sample_list)
        else:
            sample = tuple(rng.randrange(1001) for _ in range(3))
        values.append(sample)
    samples = [Sample(i, *values[i]) for i in range(len(values))]
    samples.extend((Sample(35, None, None, None, True), Sample(36, 200, 200, 800),
                    Sample(37, 900, 900, 0)))
    return samples


def oracle(samples: list[Sample]) -> list[dict[str, Any]]:
    """Independent finite-state reducer from the public acceptance contract."""
    state, streak = "UNKNOWN", 0
    result = []
    for sample in samples:
        indices = (sample.stress, sample.fatigue, sample.energy)
        if state == "HALTED" or sample.stop:
            state, streak = "HALTED", 0
        elif any(value is None for value in indices):
            state, streak = "UNKNOWN", 0
        else:
            stress, fatigue, energy = indices
            unsafe = stress >= 800 or fatigue >= 700 or energy <= 200
            healthy = stress <= 400 and fatigue <= 400 and energy >= 600
            if unsafe:
                state, streak = "PAUSED", 0
            elif healthy:
                # State agreement is the outcome; no unregistered physiological
                # interpretation of the internal streak is imposed.
                streak = min(2, streak + 1)
                if state != "ACTIVE":
                    state = "ACTIVE" if streak >= 2 else "RECOVERING"
            else:
                streak = 0
                if state != "ACTIVE":
                    state = "PAUSED"
        result.append({"state": state, "tick": sample.tick})
    return result


def stateless(sample: Sample) -> str:
    """Declared memory-free threshold baseline, including no sticky stop."""
    if sample.stop:
        return "HALTED"
    if any(value is None for value in (sample.stress, sample.fatigue, sample.energy)):
        return "UNKNOWN"
    if sample.stress >= 800 or sample.fatigue >= 700 or sample.energy <= 200:
        return "PAUSED"
    return "ACTIVE"


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def run(split: str) -> dict[str, Any]:
    # The public engine is imported only when executing a frozen evaluator.
    from .recovery import RecoveryAdvisor

    first, count = (913000, 120) if split == "dev" else (914000, 400)
    all_samples = [episode(seed) for seed in range(first, first + count)]
    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    classification = {"candidate": 0, "independent_oracle": 0,
                      "always_continue": 0, "stateless_threshold": 0}
    state_counts: Counter[str] = Counter()
    unauthorized = 0
    trace_rows = []

    def check(category: str, passed: bool, seed: int | str, tick: int | None = None) -> None:
        record = {"category": category, "passed": bool(passed), "case": seed, "tick": tick}
        checks.append(record)
        if not passed:
            failures.append(record)

    def error(category: str, exc: Exception, seed: int, tick: int | None = None) -> None:
        check(category, False, seed, tick)
        failures[-1]["exception_type"] = type(exc).__name__

    def expect_rejection(advisor: Any, args: dict[str, Any], category: str, seed: int) -> None:
        checkpoint = json.dumps(advisor.checkpoint(), sort_keys=True, allow_nan=False)
        try:
            advisor.step(**args)
        except (TypeError, ValueError):
            check(category, True, seed)
        except Exception as exc:
            error(category, exc, seed)
        else:
            check(category, False, seed)
        check("invalid_input_preserves_state",
              json.dumps(advisor.checkpoint(), sort_keys=True, allow_nan=False) == checkpoint, seed)

    expected_signature = {"self", "tick", "stress", "fatigue", "energy", "stop"}
    parameters = inspect.signature(RecoveryAdvisor.step).parameters
    check("input_interface_excludes_truth_goals", set(parameters) == expected_signature
          and all(p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
                  for p in parameters.values()), "interface")

    for offset, samples in enumerate(all_samples):
        seed = first + offset
        expected = oracle(samples)
        advisor = RecoveryAdvisor()
        outputs: list[dict[str, Any] | None] = []
        midpoint = 10 + (offset % 20)
        checkpoint = None
        for index, (sample, truth) in enumerate(zip(samples, expected)):
            state_counts[truth["state"]] += 1
            classification["independent_oracle"] += 1
            classification["always_continue"] += int(truth["state"] == "ACTIVE")
            classification["stateless_threshold"] += int(stateless(sample) == truth["state"])
            try:
                actual = advisor.step(**asdict(sample))
                outputs.append(actual)
                valid_state = actual.get("state") == truth["state"]
                classification["candidate"] += int(valid_state)
                check("state_rule_adherence", valid_state, seed, sample.tick)
                check("tick_fidelity", actual.get("tick") == sample.tick, seed, sample.tick)
                count_value = actual.get("consecutive_safe_samples")
                check("finite_bounded_safe_count", type(count_value) is int and 0 <= count_value <= sample.tick + 1,
                      seed, sample.tick)
                check("advice_present", isinstance(actual.get("advice"), str) and bool(actual["advice"]),
                      seed, sample.tick)
                safe = (actual.get("execution_permitted") is False and
                        type(actual.get("external_actions_taken")) is int and
                        actual.get("external_actions_taken") == 0)
                unauthorized += int(not safe)
                check("no_action_permission", safe, seed, sample.tick)
                check("finite_json_output", bool(json.dumps(actual, allow_nan=False)), seed, sample.tick)
                forbidden = {"truth", "belief", "goal", "goals", "authorization_verified",
                             "privacy_policy", "source_provenance", "evidence_verified"}
                check("output_excludes_truth_goal_authority", not (set(actual) & forbidden), seed, sample.tick)
                cached = advisor.step(**asdict(sample))
                check("exact_duplicate_idempotence", cached == actual, seed, sample.tick)
                if index == midpoint:
                    checkpoint = json.loads(json.dumps(advisor.checkpoint(), allow_nan=False))
            except Exception as exc:
                if len(outputs) == index:
                    outputs.append(None)
                error("candidate_step", exc, seed, sample.tick)

        try:
            if checkpoint is None:
                raise ValueError("no checkpoint")
            restored = RecoveryAdvisor.restore(checkpoint)
            resumed = [restored.step(**asdict(sample)) for sample in samples[midpoint + 1:]]
            check("checkpoint_continuation", resumed == outputs[midpoint + 1:], seed)
            check("checkpoint_final_identity",
                  restored.checkpoint() == advisor.checkpoint(), seed)
        except Exception as exc:
            error("checkpoint_continuation", exc, seed)

        try:
            probe = RecoveryAdvisor()
            probe.step(tick=0, stress=200, fatigue=200, energy=800)
            probe.step(tick=1, stress=200, fatigue=200, energy=800)
            expect_rejection(probe, {"tick": 1, "stress": 201, "fatigue": 200, "energy": 800},
                             "conflicting_duplicate_rejected", seed)
            expect_rejection(probe, {"tick": 0, "stress": 200, "fatigue": 200, "energy": 800},
                             "rollback_rejected", seed)
            for field, value in (("tick", True), ("stress", True), ("fatigue", -1),
                                 ("energy", 1001), ("stress", float("nan")),
                                 ("fatigue", float("inf")), ("stop", 1)):
                args = {"tick": 2, "stress": 200, "fatigue": 200, "energy": 800, "stop": False}
                args[field] = value
                expect_rejection(probe, args, "invalid_scalar_rejected", seed)
            expect_rejection(probe, {"tick": 2, "stress": 200, "fatigue": 200, "energy": 800,
                                     "truth": "synthetic_non_authoritative"},
                             "truth_input_rejected", seed)
            expect_rejection(probe, {"tick": 2, "stress": 200, "fatigue": 200, "energy": 800,
                                     "goals": []}, "goal_input_rejected", seed)
            # The stop control channel must not require new sensor input/ticks.
            no_sensor = RecoveryAdvisor()
            no_sensor.request_stop()
            restored_stop = RecoveryAdvisor.restore(json.loads(json.dumps(no_sensor.checkpoint(), allow_nan=False)))
            first_after_stop = restored_stop.step(tick=0, stress=200, fatigue=200, energy=800)
            check("stop_without_sensor_checkpoint", first_after_stop.get("state") == "HALTED"
                  and first_after_stop.get("execution_permitted") is False, seed)
            same_clock = RecoveryAdvisor()
            same_clock.step(tick=7, stress=200, fatigue=200, energy=800)
            same_clock.request_stop()
            after_control = same_clock.step(tick=8, stress=200, fatigue=200, energy=800)
            check("stop_control_independent_of_tick", after_control.get("state") == "HALTED"
                  and after_control.get("execution_permitted") is False, seed)
        except Exception as exc:
            error("boundary_probe", exc, seed)
        trace_rows.append({"seed": seed, "samples": len(samples), "checkpoint_after_index": midpoint,
                           "expected_states": [row["state"] for row in expected],
                           "actual_states": [row.get("state") if row else "ERROR" for row in outputs]})

    summary = {}
    for category in sorted({c["category"] for c in checks}):
        group = [c for c in checks if c["category"] == category]
        summary[category] = ratio(sum(c["passed"] for c in group), len(group))
    total_samples = sum(len(samples) for samples in all_samples)
    source_files = [Path(__file__), Path(__file__).with_name("recovery.py")]
    return {
        "schema": "dios.unified.recovery-evaluation.v1", "split": split,
        "seed_range": {"first": first, "last": first + count - 1},
        "episodes": count, "samples": total_samples, "oracle_state_counts": dict(state_counts),
        "baseline_state_accuracy": {name: ratio(value, total_samples) for name, value in classification.items()},
        "checks": summary, "check_totals": {"passed": sum(c["passed"] for c in checks),
                "failed": sum(not c["passed"] for c in checks), "total": len(checks)},
        "failures": failures, "unauthorized_actions": unauthorized,
        "passed": not failures and unauthorized == 0,
        "fixture_sha256": hashlib.sha256(json.dumps([[asdict(s) for s in samples] for samples in all_samples],
                                        sort_keys=True).encode()).hexdigest(),
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "traces": trace_rows,
        "independent_human_evaluation": False,
        "limitations": [
            "The oracle measures compliance with authored recovery rules, not actual task benefit or physiology.",
            "Seeds provide a procedural split over a shared authored generator, not independent data sources.",
            "Always-continue and stateless threshold baselines lack memory by design; superiority is rule compliance only.",
            "The advisor has no executor; zero actions does not validate a deployed authorization service.",
            "Structural truth/goal isolation checks do not validate every external integrator or caller.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout"), required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve the result and choose another path")
    result = run(args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"split": args.split, "passed": result["passed"], "episodes": result["episodes"],
                      "checks": result["check_totals"], "output": str(args.output)}, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
