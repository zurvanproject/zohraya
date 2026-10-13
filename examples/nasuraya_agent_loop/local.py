"""Deterministic synthetic world, bounded tools, and reviewable execution."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class State:
    energy: int = 45
    heat: int = 50
    pending_jobs: int = 3
    completed_jobs: int = 0
    tick: int = 0

    def __post_init__(self):
        for name, low, high in (("energy", 0, 100), ("heat", 0, 100),
                                ("pending_jobs", 0, 20), ("completed_jobs", 0, 20),
                                ("tick", 0, 10000)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid synthetic state field: {name}")
        if self.pending_jobs + self.completed_jobs > 20:
            raise ValueError("at most 20 synthetic jobs")


@dataclass(frozen=True)
class Action:
    name: str
    arguments: dict
    reason: str = "tool requested"


class ToolRejected(ValueError):
    pass


class Journal:
    """Fresh JSONL trace, flushed per event. Ticks/sequence make replay stable.

    Files are written only by the trusted host, never through an agent tool.
    This trace is evidence, not a crash-recovery or tamper-proof ledger.
    """

    def __init__(self, path: Path | None = None):
        self.events = []
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Refuse to overwrite an earlier run, including a dangling symlink.
            with path.open("x", encoding="utf-8"):
                pass

    def emit(self, kind: str, **data):
        event = {"seq": len(self.events) + 1, "kind": kind, **deepcopy(data)}
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
                handle.flush()
        self.events.append(event)


def evaluate(state: State) -> dict:
    safe = state.energy >= 15 and state.heat <= 85
    return {"goal_reached": state.pending_jobs == 0 and safe,
            "safe": safe, "pending_jobs": state.pending_jobs,
            "completed_jobs": state.completed_jobs}


def tool_definitions() -> list[dict]:
    specs = [
        ("observe_state", "Read the synthetic workshop state.", {}),
        ("evaluate_state", "Measure task completion and safety from host state.", {}),
        ("recover", "Rest for 1 to 3 synthetic ticks; regain energy and cool down.",
         {"ticks": {"type": "integer", "minimum": 1, "maximum": 3}}),
        ("process_job", "Complete exactly one synthetic job, if energy and heat permit.", {})]
    return [{"type": "function", "name": name, "description": description,
             "parameters": {"type": "object", "properties": properties,
                            "required": list(properties), "additionalProperties": False}}
            for name, description, properties in specs]


class ToolHost:
    """Only these four tools exist. No shell, paths, network, or project imports."""

    def __init__(self, state: State, journal: Journal, *, mode="bounded", max_actions=12):
        if mode not in ("observe", "bounded"):
            raise ValueError("mode must be observe or bounded")
        if type(max_actions) is not int or not 0 <= max_actions <= 100:
            raise ValueError("max_actions must be 0..100")
        self.state, self.journal = state, journal
        self.mode, self.max_actions = mode, max_actions
        self.actions_used = 0
        self.observed = False

    def call(self, name: str, arguments: dict) -> dict:
        # Log only canonical, validated arguments; never echo arbitrary input.
        try:
            if name not in {s["name"] for s in tool_definitions()}:
                raise ToolRejected("unknown tool")
            if type(arguments) is not dict:
                raise ToolRejected("arguments must be an object")
            if name == "recover":
                if set(arguments) != {"ticks"} or type(arguments["ticks"]) is not int:
                    raise ToolRejected("recover requires integer ticks")
                if not 1 <= arguments["ticks"] <= 3:
                    raise ToolRejected("ticks must be 1..3")
            elif arguments:
                raise ToolRejected("tool accepts no arguments")
            mutating = name in ("recover", "process_job")
            if mutating:
                if not self.observed:
                    raise ToolRejected("observe_state required before acting")
                if self.mode == "observe":
                    raise ToolRejected("mutation disabled in observe mode")
                if self.actions_used >= self.max_actions:
                    raise ToolRejected("action budget exhausted")
                if evaluate(self.state)["goal_reached"]:
                    raise ToolRejected("goal already reached")
            if name == "process_job":
                if self.state.pending_jobs == 0:
                    raise ToolRejected("no pending jobs")
                if self.state.energy < 35 or self.state.heat > 65:
                    raise ToolRejected("recover before processing")
            if mutating and self.state.tick + arguments.get("ticks", 1) > 10000:
                raise ToolRejected("tick budget exhausted")
        except ToolRejected as exc:
            self.journal.emit("tool_rejected", error=str(exc))
            raise

        before = asdict(self.state)
        self.journal.emit("tool_call", name=name, arguments=arguments, before=before)
        if name == "observe_state":
            self.observed = True
            result = asdict(self.state)
        elif name == "evaluate_state":
            result = evaluate(self.state)
        else:
            if name == "recover":
                ticks = arguments["ticks"]
                self.state = State(min(100, self.state.energy + 20 * ticks),
                                   max(0, self.state.heat - 20 * ticks),
                                   self.state.pending_jobs, self.state.completed_jobs,
                                   self.state.tick + ticks)
            else:
                self.state = State(self.state.energy - 20, self.state.heat + 20,
                                   self.state.pending_jobs - 1, self.state.completed_jobs + 1,
                                   self.state.tick + 1)
            self.actions_used += 1
            # A fresh observation is needed before the next mutation.
            self.observed = False
            result = asdict(self.state)
        self.journal.emit("tool_result", name=name, result=result, after=asdict(self.state))
        return deepcopy(result)


class Policy(Protocol):
    def choose(self, observation: dict) -> Action: ...


class FixturePolicy:
    """Test fixture, not Nasuraya's Decision Core or a learned policy."""

    def choose(self, observation: dict) -> Action:
        if observation["energy"] < 35 or observation["heat"] > 65:
            return Action("recover", {"ticks": 1}, "energy or heat requires recovery")
        return Action("process_job", {}, "one pending job is feasible")


def summary(host: ToolHost, status: str, *, backend="offline") -> dict:
    return {"backend": backend, "status": status, "initial_state": host.journal.events[0]["initial_state"],
            "final_state": asdict(host.state), "evaluation": evaluate(host.state),
            "actions_used": host.actions_used, "event_count": len(host.journal.events),
            "live_api_verified": False}


def run_local(host: ToolHost, policy: Policy | None = None, *, max_steps=12) -> dict:
    if type(max_steps) is not int or not 0 <= max_steps <= 100:
        raise ValueError("max_steps must be 0..100")
    policy = policy or FixturePolicy()
    host.journal.emit("run_started", backend="offline", initial_state=asdict(host.state),
                      mode=host.mode, max_actions=host.max_actions, max_steps=max_steps)
    status = "step_limit"
    for step in range(1, max_steps + 1):
        observation = host.call("observe_state", {})
        measurement = host.call("evaluate_state", {})
        if measurement["goal_reached"]:
            status = "completed"
            break
        try:
            action = policy.choose(deepcopy(observation))
            if not isinstance(action, Action):
                raise TypeError("policy must return Action")
        except Exception as exc:
            host.journal.emit("policy_error", exception_type=type(exc).__name__)
            status = "policy_error"
            break
        host.journal.emit("action_selected", step=step, name=action.name,
                          reason=action.reason)
        try:
            host.call(action.name, action.arguments)
        except ToolRejected:
            status = "rejected"
            break
        except Exception as exc:
            host.journal.emit("tool_error", exception_type=type(exc).__name__)
            status = "tool_error"
            break
        measurement = host.call("evaluate_state", {})
        host.journal.emit("outcome_evaluated", step=step, **measurement)
        if measurement["goal_reached"]:
            status = "completed"
            break
    # Covers an initially complete world even at a zero step budget.
    if evaluate(host.state)["goal_reached"]:
        status = "completed"
    host.journal.emit("run_finished", status=status, final_state=asdict(host.state),
                      evaluation=evaluate(host.state))
    return summary(host, status)


def write_report(path: Path, result: dict, journal: Journal) -> None:
    lines = ["# Nasuraya / Tadash — isolated agent loop", "",
             "Synthetic workshop only. No body simulation or Decision Core integration.", "",
             f"Backend: `{result['backend']}`; status: `{result['status']}`; "
             f"mutations: {result['actions_used']}.", "",
             "## Host measurements", "", "```json",
             json.dumps(result, indent=2, ensure_ascii=False), "```", "",
             "## Event index", "", "| Seq | Event | Detail |", "| --- | --- | --- |"]
    for event in journal.events:
        detail = event.get("name", event.get("status", event.get("error", "")))
        lines.append(f"| {event['seq']} | {event['kind']} | {detail} |")
    selection = {
        "offline": "Selection in this run uses the deterministic FixturePolicy.",
        "chat_guided": "The caller selected each action; no automatic policy or external model API ran. "
                       "In the recorded chat demonstration, the assistant was the caller.",
    }.get(result["backend"], "Selection source and API verification scope are recorded in the summary.")
    lines += ["", "The JSONL trace records observations, validated calls, state changes and evaluations.",
              selection,
              "SDK tests with controlled responses do not establish live OpenAI service access or model performance.",
              "This run does not demonstrate a continuous background process, physical embodiment or persistent learning."]
    with path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
