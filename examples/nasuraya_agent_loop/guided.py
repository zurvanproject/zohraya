"""Step-by-step synthetic execution selected by a caller, not FixturePolicy.

The trusted host persists a local checkpoint after every command. This supports
process restart for this synthetic world; it is NOT recovery of API side effects.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from .local import Journal, State, ToolHost, ToolRejected, evaluate, summary, write_report


def _write(path: Path, data: dict):
    # Atomic replacement: a partial write cannot become the new checkpoint.
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save(path: Path, host: ToolHost, closed=False):
    _write(path, {"format": "nasuraya-guided-checkpoint-v1", "state": asdict(host.state),
                  "actions_used": host.actions_used, "max_actions": host.max_actions,
                  "observed": host.observed, "closed": closed, "events": host.journal.events})


def _load(path: Path) -> tuple[ToolHost, bool]:
    data = json.loads(path.read_text())
    if data.get("format") != "nasuraya-guided-checkpoint-v1":
        raise ValueError("unsupported checkpoint format")
    state = State(**data["state"])
    journal = Journal()
    journal.events = data["events"]
    if not journal.events or journal.events[0].get("kind") != "run_started":
        raise ValueError("checkpoint has no start record")
    if [e.get("seq") for e in journal.events] != list(range(1, len(journal.events) + 1)):
        raise ValueError("checkpoint event sequence invalid")
    host = ToolHost(state, journal, max_actions=data["max_actions"])
    count = sum(e.get("kind") == "tool_result" and e.get("name") in ("recover", "process_job")
                for e in journal.events)
    if type(data["actions_used"]) is not int or data["actions_used"] != count or count > host.max_actions:
        raise ValueError("checkpoint action count invalid")
    if type(data["observed"]) is not bool or type(data["closed"]) is not bool:
        raise ValueError("checkpoint flags invalid")
    results = [e for e in journal.events if e.get("kind") == "tool_result"]
    expected = results[-1]["after"] if results else journal.events[0]["initial_state"]
    if asdict(state) != expected:
        raise ValueError("checkpoint state does not match saved tool result")
    initial = journal.events[0]["initial_state"]
    if state.pending_jobs + state.completed_jobs != initial["pending_jobs"] + initial["completed_jobs"]:
        raise ValueError("checkpoint job conservation failed")
    # Observed flag must follow the last observation/mutation, not just a field in JSON.
    observation_events = [e for e in results if e.get("name") in ("observe_state", "recover", "process_job")]
    expected_observed = bool(observation_events and observation_events[-1]["name"] == "observe_state")
    if data["observed"] != expected_observed:
        raise ValueError("checkpoint observation flag invalid")
    host.actions_used, host.observed = count, data["observed"]
    return host, data["closed"]


def start(path: Path, state=State(), *, max_actions=8):
    path.parent.mkdir(parents=True, exist_ok=True)
    host = ToolHost(state, Journal(), max_actions=max_actions)
    host.journal.emit("run_started", backend="chat_guided", initial_state=asdict(state),
                      mode="bounded", max_actions=max_actions,
                      selection_source="caller_selected_actions")
    # Reserve the name without overwriting another checkpoint.
    with path.open("x", encoding="utf-8"):
        pass
    _save(path, host)
    return {"status": "started", "state": asdict(state), "max_actions": max_actions}


def observe(path: Path):
    host, closed = _load(path)
    if closed:
        raise ValueError("guided session is closed")
    observation = host.call("observe_state", {})
    measurement = host.call("evaluate_state", {})
    _save(path, host)
    return {"state": observation, "evaluation": measurement, "actions_used": host.actions_used,
            "actions_remaining": host.max_actions - host.actions_used}


def act(path: Path, name: str, arguments: dict, reason: str):
    host, closed = _load(path)
    if closed:
        raise ValueError("guided session is closed")
    if name not in ("recover", "process_job"):
        raise ValueError("guided action must be a mutation tool")
    if not isinstance(reason, str) or len(reason) > 240:
        raise ValueError("reason must be a short public decision summary")
    host.journal.emit("action_selected", name=name, reason=reason,
                      selection_source="caller_selected_actions")
    try:
        result = host.call(name, arguments)
    except ToolRejected:
        _save(path, host)
        raise
    measurement = host.call("evaluate_state", {})
    host.journal.emit("outcome_evaluated", **measurement)
    _save(path, host)
    return {"state": result, "evaluation": measurement, "actions_used": host.actions_used}


def finish(path: Path, output_dir: Path):
    host, closed = _load(path)
    if closed:
        raise ValueError("guided session is closed")
    output_dir.mkdir(parents=True, exist_ok=False)
    status = "completed" if evaluate(host.state)["goal_reached"] else "goal_unmet"
    host.journal.emit("run_finished", status=status, final_state=asdict(host.state),
                      evaluation=evaluate(host.state))
    result = summary(host, status, backend="chat_guided")
    result.update(selection_source="caller_selected_actions", external_model_api_used=False,
                  checkpoint_recovery_scope="synthetic state only")
    (output_dir / "events.jsonl").write_text("".join(json.dumps(e, sort_keys=True, ensure_ascii=False)+"\n"
                                                for e in host.journal.events))
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n")
    write_report(output_dir / "report.md", result, host.journal)
    _save(path, host, closed=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guided synthetic session; no automatic policy")
    parser.add_argument("command", choices=["start", "observe", "act", "finish"])
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--energy", type=int, default=45)
    parser.add_argument("--heat", type=int, default=50)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--max-actions", type=int, default=8)
    parser.add_argument("--tool", choices=["recover", "process_job"])
    parser.add_argument("--ticks", type=int)
    parser.add_argument("--reason", default="selected by caller")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "start":
        result = start(args.session, State(args.energy, args.heat, args.jobs), max_actions=args.max_actions)
    elif args.command == "observe":
        result = observe(args.session)
    elif args.command == "act":
        if not args.tool:
            parser.error("--tool required for act")
        arguments = {"ticks": args.ticks} if args.tool == "recover" else {}
        if args.tool == "process_job" and args.ticks is not None:
            parser.error("process_job accepts no ticks")
        result = act(args.session, args.tool, arguments, args.reason)
    else:
        if not args.output_dir:
            parser.error("--output-dir required for finish")
        result = finish(args.session, args.output_dir)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
