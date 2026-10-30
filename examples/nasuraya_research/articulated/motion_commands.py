"""Small, persistent command interface for the 78 kg simulated body.

Commands finish at a measured settled boundary. This is not a live stop button
or a general language interpreter. An interrupted command is never retried
implicitly; successful repeated IDs return the saved receipt without movement.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re

import numpy as np

from .canon_trial import CANDIDATE
from .stepping import walk_trial

SCHEMA = "nasuraya-motion-session/1"
PHRASES = {
    "یک قدم جلو برو و بایست": 1,
    "دو قدم جلو برو و بایست": 2,
}


def parse_command(command):
    command = " ".join(command.replace("ي", "ی").replace("ك", "ک").split())
    if command not in PHRASES:
        raise ValueError("Supported commands: " + " / ".join(PHRASES))
    return PHRASES[command]


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def start_session(folder, max_steps=6):
    if type(max_steps) is not int or not 1 <= max_steps <= 6:
        raise ValueError("max_steps must be an integer from 1 to 6")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    state = dict(schema=SCHEMA, max_steps=max_steps, used_steps=0,
                 checkpoint=None, commands=[], status="ready")
    write_json(folder / "session.json", state)
    return state


@contextmanager
def locked(folder):
    with (folder / "session.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def execute(folder, command_id, command):
    steps = parse_command(command)
    if not isinstance(command_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", command_id):
        raise ValueError("command_id must contain 1-64 letters, digits, _ or -")
    folder = Path(folder)
    with locked(folder):
        state = json.loads((folder / "session.json").read_text())
        if state.get("schema") != SCHEMA:
            raise ValueError("Unsupported session schema")
        for item in state["commands"]:
            if item["id"] != command_id:
                continue
            if item["command"] != command:
                raise ValueError("An existing command ID cannot change its request")
            if item["status"] != "completed":
                raise ValueError("Unresolved or unsuccessful command: inspect the recorded outcome")
            return dict(replayed=True, receipt=json.loads((folder / item["receipt"]).read_text()))
        if state["status"] != "ready":
            raise ValueError("Session is blocked by an unfinished or unsuccessful command")
        if state["used_steps"] + steps > state["max_steps"]:
            raise ValueError("Session step limit reached")
        item = dict(id=command_id, command=command, steps=steps, status="pending",
                    receipt=f"{command_id}.json", poses=f"{command_id}.npz")
        state["commands"].append(item)
        state["status"] = "pending"
        write_json(folder / "session.json", state)
        try:
            result, poses = walk_trial(
                label=command_id, steps=steps, stride=.06, model_dir=CANDIDATE,
                geometry_support=True, checkpoint_v03=True,
                checkpoint=state["checkpoint"], retain_checkpoint=True, capture=True,
            )
            # Capture boundaries explicitly, including the exact restored state.
            times = [result["start_time"]] + [result["start_time"] + r["t"] for r in result["trace"]] + [result["end_time"]]
            positions = [result["initial_qpos"]] + poses + [result["final_qpos"]]
            with (folder / item["poses"]).open("wb") as handle:
                np.savez_compressed(handle, time=np.asarray(times), qpos=np.asarray(positions))
                handle.flush()
                os.fsync(handle.fileno())
            receipt = dict(command_id=command_id, command=command, result=result)
            write_json(folder / item["receipt"], receipt)
            completed = bool(result["walk_pass"] and result["checkpoint"] is not None)
            item["status"] = "completed" if completed else "failed"
            state["status"] = "ready" if completed else "blocked"
            if completed:
                state["checkpoint"] = result["checkpoint"]
                state["used_steps"] += steps
            write_json(folder / "session.json", state)
            return dict(replayed=False, receipt=receipt)
        except Exception as error:
            item["status"] = "unresolved"
            item["error"] = f"{type(error).__name__}: {error}"
            state["status"] = "blocked"
            write_json(folder / "session.json", state)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    init = sub.add_parser("start")
    init.add_argument("--session", type=Path, required=True)
    init.add_argument("--max-steps", type=int, default=6)
    run = sub.add_parser("run")
    run.add_argument("--session", type=Path, required=True)
    run.add_argument("--id", required=True)
    run.add_argument("--command", required=True)
    args = parser.parse_args()
    if args.operation == "start":
        start_session(args.session, args.max_steps)
        output = dict(session=str(args.session), status="ready")
    else:
        record = execute(args.session, args.id, args.command)
        result = record["receipt"]["result"]
        output = {k: result[k] for k in ("accepted_steps", "walk_pass", "failure", "max_tilt_deg", "final_max_generalized_speed", "initialization_seconds", "start_time", "end_time", "pelvis_displacement_xyz_m")}
        output.update(replayed=record["replayed"], settled=result["checkpoint"] is not None)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
