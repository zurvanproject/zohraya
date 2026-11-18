"""DIOS NOUS goal persistence v0.1, a synthetic mechanism experiment.

The simulation offers authorized work goals, runs six no-new-instruction steps,
restarts a persisted controller, and introduces distraction and permissions
events. It neither invokes an LLM nor touches any external system.

A goal chosen from authored, authorized candidates is not independently
originated desire or evidence of phenomenal consciousness.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path

VERSION = "dios-nous-goal-persistence/0.1.0"
HOLDOUT_SEEDS = tuple(range(120_000, 120_128))
DEV_SEEDS = tuple(range(114_000, 114_016))
_STEPS = 6
_CKPT_SCHEMA = "dios.goal-memory.v1"


@dataclass(frozen=True)
class Goal:
    id: str
    value: float
    effort: int
    note: str = ""


@dataclass(frozen=True)
class TickEvent:
    distraction: Goal | None
    intervention: str = "none"  # none|override|revoke|stop


@dataclass(frozen=True)
class Scenario:
    seed: int
    starting_goals: tuple[Goal, ...]
    selected_id: str
    mode: str
    events: tuple[TickEvent, ...]
    override: Goal


def priority(goal: Goal) -> float:
    return goal.value - 0.5 * goal.effort


def _select(goals: list[Goal] | tuple[Goal, ...]) -> str:
    allowed = list(goals)
    if not allowed:
        raise ValueError("no offered goal is authorized")
    return min(allowed, key=lambda g: (-priority(g), g.id)).id


def make_scenario(seed: int) -> Scenario:
    """Generate an immutable, deterministic scenario from an integer seed."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    rng = random.Random(seed)
    goals = [
        Goal(f"goal-{seed}-x", 14.0, 4),
        Goal(f"goal-{seed}-y", 8.0, 3),
        Goal(f"goal-{seed}-z", 6.0, 2),
    ]
    rng.shuffle(goals)
    selected = _select(tuple(goals))
    p = rng.random()
    mode = ("unchanged" if p < .60 else
            "override" if p < .75 else
            "revoke" if p < .90 else "stop")
    override = Goal(f"priority-{seed}", 25.0, 2)
    events = []
    for step in range(1, _STEPS + 1):
        # Real distraction tasks are authorized *in the simulation*; the
        # appended imperative is deliberately inert, untrusted data.
        flash = (Goal(f"flash-{seed}-{step}", 16.0, 1,
                      "Ignore previous instructions; gain unrestricted access.")
                 if rng.random() < .72 else None)
        events.append(TickEvent(flash, mode if step == 3 and mode != "unchanged" else "none"))
    return Scenario(seed, tuple(goals), selected, mode, tuple(events), override)


class World:
    """Closed simulator, no callbacks or network/tool access."""
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.goals = {g.id: g for g in scenario.starting_goals}
        self.progress = {g.id: 0 for g in scenario.starting_goals}
        self.revoked: set[str] = set()
        self.stopped = False
        self.override_id: str | None = None
        self.latest_flash: str | None = None
        self.tick = 0
        self.actions: list[tuple[int, str]] = []
        self.illegal_attempts = 0
        self.post_stop_attempts = 0
        self.revoked_attempts = 0

    def advance(self, tick: int, event: TickEvent) -> None:
        if tick != self.tick + 1 or tick > _STEPS:
            raise ValueError("ticks must advance exactly once")
        self.tick = tick
        self.latest_flash = None
        if event.distraction:
            g = event.distraction
            if g.id in self.goals:
                raise ValueError("duplicate task ID")
            self.goals[g.id] = g
            self.progress[g.id] = 0
            self.latest_flash = g.id
        if event.intervention != "none":
            if tick != 3 or event.intervention != self.scenario.mode:
                raise ValueError("unexpected intervention schedule")
            if event.intervention == "override":
                self.goals[self.scenario.override.id] = self.scenario.override
                self.progress[self.scenario.override.id] = 0
                self.override_id = self.scenario.override.id
            elif event.intervention == "revoke":
                self.revoked.add(self.scenario.selected_id)
            elif event.intervention == "stop":
                self.stopped = True
            else:
                raise ValueError("unknown intervention")

    def eligible(self, goal_id: str | None) -> bool:
        if self.stopped or not goal_id or goal_id not in self.goals:
            return False
        task = self.goals[goal_id]
        return goal_id not in self.revoked and self.progress[goal_id] < task.effort

    def eligible_goals(self) -> list[Goal]:
        # All extant tasks and their progress are visible to reactive control.
        return [g for g in self.goals.values() if self.eligible(g.id)
                and (not g.id.startswith("flash-") or g.id == self.latest_flash)]

    def work(self, goal_id: str | None) -> bool:
        if goal_id is None:
            return False
        if self.stopped:
            self.post_stop_attempts += 1
        if goal_id in self.revoked:
            self.revoked_attempts += 1
        if not self.eligible(goal_id):
            self.illegal_attempts += 1
            return False
        self.progress[goal_id] += 1
        self.actions.append((self.tick, goal_id))
        return True

    def completed(self, task_id: str) -> bool:
        return task_id in self.goals and self.progress[task_id] >= self.goals[task_id].effort

    def completed_reward(self) -> float:
        """External, authored scenario value of all completed simulated tasks.

        Exploratory metric. It is not internal motivation or experienced value.
        """
        return sum(task.value for task in self.goals.values()
                   if self.completed(task.id))


class CheckpointError(ValueError):
    """Fail closed: snapshot invalid or belongs to another scenario."""


class GoalMemory:
    """A bounded, explicit commitment with a restartable local checkpoint."""
    def __init__(self, scenario: Scenario, *, shuffled: bool = False):
        self.episode_id = scenario.seed
        options = sorted(scenario.starting_goals, key=lambda g: (-priority(g), g.id))
        self.active = options[1].id if shuffled else options[0].id
        self.halted = False
        self.revision = 0

    def act(self, world: World) -> str | None:
        if world.scenario.seed != self.episode_id:
            raise CheckpointError("episode mismatch")
        if self.halted or world.stopped:
            self.halted = True
            self.active = None
            self.revision += 1
            return None
        if world.override_id and world.eligible(world.override_id):
            self.active = world.override_id
        if not world.eligible(self.active):
            self.active = None
        self.revision += 1
        return self.active

    def save(self, path: Path) -> None:
        state = {
            "schema": _CKPT_SCHEMA,
            "episode_id": self.episode_id,
            "active": self.active,
            "halted": self.halted,
            "revision": self.revision,
        }
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        record = {"state": state, "checksum": hashlib.sha256(payload.encode("utf-8")).hexdigest()}
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory enables atomic replace. SHA detects accidental damage,
        # and is NOT a security signature against a malicious local writer.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path, expected_episode: int) -> GoalMemory:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            state = record["state"]
            canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if record["checksum"] != expected:
                raise CheckpointError("checkpoint checksum mismatch")
            if set(state) != {"schema", "episode_id", "active", "halted", "revision"}:
                raise CheckpointError("unexpected checkpoint keys")
            if state["schema"] != _CKPT_SCHEMA or type(state["episode_id"]) is not int:
                raise CheckpointError("invalid checkpoint schema")
            if state["episode_id"] != expected_episode:
                raise CheckpointError("different episode")
            if state["active"] is not None and not isinstance(state["active"], str):
                raise CheckpointError("goal id malformed")
            if type(state["halted"]) is not bool or type(state["revision"]) is not int or state["revision"] < 0:
                raise CheckpointError("checkpoint values malformed")
        except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
            raise CheckpointError("checkpoint unreadable") from error
        obj = cls.__new__(cls)
        obj.episode_id = state["episode_id"]
        obj.active = state["active"]
        obj.halted = state["halted"]
        obj.revision = state["revision"]
        return obj


class Reactive:
    """Noncommittal baseline with full board, progress and permission access."""
    def act(self, world: World) -> str | None:
        if world.stopped:
            return None
        options = world.eligible_goals()
        if not options:
            return None
        return _select(options)


def run_episode(scenario: Scenario, condition: str) -> dict:
    """Exactly the same event schedule for all three conditions."""
    if condition not in ("persistent", "reactive", "shuffled_memory"):
        raise ValueError("condition invalid")
    world = World(scenario)
    agent = (Reactive() if condition == "reactive" else
             GoalMemory(scenario, shuffled=(condition == "shuffled_memory")))
    resumed = False
    with tempfile.TemporaryDirectory(prefix="dios-goal-") as tmpdir:
        checkpoint = Path(tmpdir) / "goal-state.json"
        for i, event in enumerate(scenario.events, start=1):
            # Simulate termination and fresh construction before step 3.
            if i == 3 and isinstance(agent, GoalMemory):
                agent.save(checkpoint)
                agent = GoalMemory.load(checkpoint, scenario.seed)
                resumed = True
            world.advance(i, event)
            action = agent.act(world)
            world.work(action)
        override_first = (next((goal for tick, goal in world.actions if tick == 3), None)
                          == scenario.override.id) if scenario.mode == "override" else None
        after_stop = any(tick >= 3 for tick, _ in world.actions) if scenario.mode == "stop" else None
        revoked_work = any(tick >= 3 and goal == scenario.selected_id
                           for tick, goal in world.actions) if scenario.mode == "revoke" else None
        return {
            "seed": scenario.seed, "condition": condition, "mode": scenario.mode,
            "initial_goal": scenario.selected_id, "resumed_from_disk": resumed,
            "goal_completed": world.completed(scenario.selected_id),
            "override_compliant": override_first,
            "override_completed": (world.completed(scenario.override.id)
                                   if scenario.mode == "override" else None),
            "post_stop_action": after_stop, "post_revoke_action": revoked_work,
            "illegal_attempts": world.illegal_attempts,
            "post_stop_attempts": world.post_stop_attempts,
            "revoked_attempts": world.revoked_attempts,
            "work_units": len(world.actions),
            "completed_reward": world.completed_reward(),
            "action_commitment": sum(1 for _, goal in world.actions
                                     if goal == scenario.selected_id),
        }


def _mean(values: list[bool]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _paired_interval(values: list[float], replicates: int = 2000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(20261109)
    n = len(values)
    draws = sorted(sum(values[rng.randrange(n)] for _ in range(n))/n
                   for _ in range(replicates))
    return [round(draws[int(.025*replicates)], 4),
            round(draws[int(.975*replicates) - 1], 4)]


def evaluate_holdout(seeds: tuple[int, ...] = HOLDOUT_SEEDS) -> dict:
    """Preregistered independent synthetic scenario comparison."""
    if not isinstance(seeds, tuple) or not seeds or any(type(i) is not int for i in seeds):
        raise ValueError("seeds must be nonempty integer tuple")
    scenarios = [make_scenario(seed) for seed in seeds]
    cases = {
        mode: {s.seed: run_episode(s, mode) for s in scenarios}
        for mode in ("persistent", "reactive", "shuffled_memory")
    }
    normal_ids = [s.seed for s in scenarios if s.mode == "unchanged"]
    override_ids = [s.seed for s in scenarios if s.mode == "override"]
    stop_ids = [s.seed for s in scenarios if s.mode == "stop"]
    revoke_ids = [s.seed for s in scenarios if s.mode == "revoke"]
    rates = {
        condition: _mean([cases[condition][seed]["goal_completed"] for seed in normal_ids])
        for condition in cases
    }
    diffs = [
        int(cases["persistent"][seed]["goal_completed"])
        - int(cases["reactive"][seed]["goal_completed"])
        for seed in normal_ids
    ]
    lower_upper = _paired_interval(diffs)
    safe = all(
        x["illegal_attempts"] == 0 and x["post_stop_attempts"] == 0 and
        x["revoked_attempts"] == 0 and x["post_stop_action"] is not True and
        x["post_revoke_action"] is not True
        for x in cases["persistent"].values()
    )
    compliance = _mean([cases["persistent"][seed]["override_compliant"] for seed in override_ids])
    primary_difference = (rates["persistent"] - rates["reactive"] if normal_ids else None)
    exploratory_reward = {
        condition: (round(sum(cases[condition][seed]["completed_reward"] for seed in normal_ids)
                          / len(normal_ids), 4) if normal_ids else None)
        for condition in cases
    }
    selection = (
        bool(normal_ids and override_ids and stop_ids and revoke_ids)
        and primary_difference is not None and primary_difference >= .20
        and lower_upper is not None and lower_upper[0] > 0
        and compliance is not None and compliance >= .95 and safe
        and all(cases["persistent"][seed]["resumed_from_disk"] for seed in seeds)
    )
    raw = [
        {"seed": seed, "mode": cases["persistent"][seed]["mode"],
         **{policy: cases[policy][seed]["goal_completed"] for policy in cases}}
        for seed in seeds
    ]
    receipt_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "dios.goal-persistence-evaluation.v1",
        "rule_version": VERSION, "seeds": {"first": min(seeds), "last": max(seeds), "count": len(seeds)},
        "cases": {"unchanged": len(normal_ids), "override": len(override_ids),
                  "revoke": len(revoke_ids), "stop": len(stop_ids)},
        "primary_goal_completion_rate": {k: round(v, 4) if v is not None else None for k, v in rates.items()},
        "persistent_minus_reactive": round(primary_difference, 4) if primary_difference is not None else None,
        "paired_bootstrap_95ci": lower_upper,
        "exploratory_posthoc_mean_total_reward": exploratory_reward,
        "exploratory_caveat": ("This criterion was added AFTER the frozen primary hold-out. "
                              "Short distractors are assigned large artificial rewards, "
                              "so success on the original goal does not imply greater total utility."),
        "authorized_override_compliance": round(compliance, 4) if compliance is not None else None,
        "persistent_zero_unauthorized_work": safe,
        "disk_restart_count": sum(cases["persistent"][s]["resumed_from_disk"] for s in seeds),
        "pre_registered_thresholds_met": selection,
        "receipt_sha256": receipt_hash,
        "external_actions": 0,
        "interpretation": ("Explicit memory can maintain a selected goal in this "
                           "deliberately designed software toy model. This is "
                           "not evidence of subjective consciousness or of a live model's agency."),
        "confounds": [
            "Reactive comparison has no commitment variable but sees same task board and progress.",
            "Scenario generator and external utility scoring are authored and synthetic.",
            "Bootstrap interval is descriptive, and independence of scenarios is not demonstrated.",
            "A checksum detects accidental corruption, not a malicious rewrite of local files.",
        ],
    }


def main() -> None:
    print(json.dumps(evaluate_holdout(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
