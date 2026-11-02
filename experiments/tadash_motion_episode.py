"""Bounded v03 motion, immutable episode, and cold evidence-gated continuation.

This uses the existing pinned MuJoCo command interface in a separate checkout.
The next action is a declared rule, not a learned policy or a Hindsight service.
Hashes detect drift relative to this run's saved anchors; they are not signatures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


MOTION_COMMIT = "c6bac77802a7fab9178fb00eed28e3c4410b9482"
MODEL_PATH = "assets/nasuraya_articulated_v03/nasuraya.xml"
MODEL_SHA256 = "3c3e129fb7d676ea666f99fc8167a0e341a2fce4c2efc7a26b548e8addae5e1d"
COMMAND = "یک قدم جلو برو و بایست"
MODULE = "examples.nasuraya_research.articulated.motion_commands"
EPISODE_SCHEMA = "tadash-motion-episode/1"
LIMITS = {"max_tilt_deg": 20.0, "max_joint_limit_excess_rad": 0.02,
          "final_max_generalized_speed_exclusive": 0.05}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))


def write(path, value, *, replace=False):
    path = Path(path)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if replace:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("x") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    else:
        with path.open("x") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def clean_env():
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT") if key in os.environ}
    # Physics and recorded-pose validation do not create a graphics context.
    # Rendering is a separate caller: do not require system EGL on CPU CI hosts.
    env.update(OPENBLAS_CORETYPE="Haswell", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", MUJOCO_GL="disable")
    return env


def source_identity(folder):
    folder = Path(folder).resolve()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(folder), *args], text=True, timeout=30).strip()
    if git("rev-parse", "HEAD") != MOTION_COMMIT:
        raise ValueError("Pinned motion source commit required")
    # No mutable tracked code, index changes, or shadowing Python source allowed.
    if git("diff", "--name-only", MOTION_COMMIT):
        raise ValueError("Motion source has tracked modifications")
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    if any(Path(name).suffix in {".py", ".xml", ".yaml", ".yml"} for name in untracked):
        raise ValueError("Untracked executable/model source in motion checkout")
    if sha(folder / MODEL_PATH) != MODEL_SHA256:
        raise ValueError("Pinned v03 model hash mismatch")
    if (folder / MODEL_PATH).is_symlink():
        raise ValueError("Model must be a regular source file")
    return {"commit": MOTION_COMMIT, "model_path": MODEL_PATH, "model_sha256": MODEL_SHA256}


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite numeric observation required")
    return value


def validate_receipt(receipt, session, model_contract, command_id, used_steps):
    if receipt.get("command_id") != command_id or receipt.get("command") != COMMAND:
        raise ValueError("Wrong command receipt")
    result = receipt["result"]
    if result.get("walk_pass") is not True or result.get("failure") is not None:
        raise ValueError("Motion did not pass")
    if (type(result.get("requested_steps")) is not int or type(result.get("accepted_steps")) is not int
            or result["requested_steps"] != 1 or result["accepted_steps"] != 1):
        raise ValueError("Exactly one accepted step is required")
    if session.get("schema") != "nasuraya-motion-session/1" or session.get("status") != "ready":
        raise ValueError("Session is incomplete or blocked")
    if session.get("used_steps") != used_steps or session.get("max_steps") != 2:
        raise ValueError("Session budget mismatch")
    commands = session.get("commands", [])
    if len(commands) != used_steps or any(row.get("status") != "completed" for row in commands):
        raise ValueError("Missing or unresolved command")
    if (commands[-1].get("id") != command_id or commands[-1].get("command") != COMMAND
            or commands[-1].get("steps") != 1):
        raise ValueError("Receipt and session disagree")
    if result.get("nonfoot_ground_contacts") != []:
        raise ValueError("Non-foot contact found")
    if not 0 <= finite(result["max_tilt_deg"]) <= LIMITS["max_tilt_deg"]:
        raise ValueError("Tilt guard exceeded")
    if not 0 <= finite(result["max_joint_limit_excess_rad"]) <= LIMITS["max_joint_limit_excess_rad"]:
        raise ValueError("Joint guard exceeded")
    if not 0 <= finite(result["final_max_generalized_speed"]) < LIMITS["final_max_generalized_speed_exclusive"]:
        raise ValueError("Unsettled motion")
    checkpoint = result.get("checkpoint")
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"value", "sha256"}:
        raise ValueError("Settled checkpoint missing")
    payload = checkpoint["value"]
    if digest(payload) != checkpoint["sha256"] or session.get("checkpoint") != checkpoint:
        raise ValueError("Checkpoint integrity mismatch")
    if payload.get("schema") != "nasuraya-articulated-checkpoint/2":
        raise ValueError("v03 checkpoint required")
    contract = payload.get("contract", {})
    if contract.get("geometry_support") is not True or contract.get("source") != model_contract:
        raise ValueError("Checkpoint source/model/package identity differs")
    if contract["source"].get("files", {}).get("nasuraya.xml") != MODEL_SHA256:
        raise ValueError("Checkpoint has wrong model")
    if (result["final_qpos"] != payload["qpos"] or result["final_qvel"] != payload["qvel"]
            or result["end_time"] != payload["time"]):
        raise ValueError("Receipt boundary differs from checkpoint")
    for name in ("integration", "qpos", "qvel"):
        if not isinstance(payload[name], list) or not payload[name]:
            raise ValueError("Checkpoint array missing")
        for number in payload[name]:
            finite(number)
    if not finite(result["end_time"]) > finite(result["start_time"]):
        raise ValueError("Motion time did not advance")
    return result


def evidence_file(folder, name, expected_hash):
    root = Path(folder).resolve()
    path = root / name
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError("Evidence must be a regular file directly within output")
    if sha(path) != expected_hash:
        raise ValueError("Episode evidence hash mismatch")
    return read(path)


def recover_episode(folder, expected_episode_sha256, identity):
    """Pure validation of saved first-step evidence; never invokes motion."""
    folder = Path(folder)
    if sha(folder / "episode.json") != expected_episode_sha256:
        raise ValueError("Episode anchor mismatch")
    episode = read(folder / "episode.json")
    if episode.get("schema") != EPISODE_SCHEMA or episode.get("source") != identity:
        raise ValueError("Episode source identity mismatch")
    evidence = episode.get("evidence", {})
    required = {"first-receipt.json", "first-session.json", "model-audit.json", "expectation.json", "capture-first.json"}
    if set(evidence) != required:
        raise ValueError("Incomplete episode evidence")
    if episode.get("motion_snapshot") != "first-motion" or episode.get("motion_files") != tree_hashes(folder / "first-motion"):
        raise ValueError("Raw motion receipt, session or pose capture changed")
    records = {name: evidence_file(folder, name, evidence[name]) for name in required}
    audit = records["model-audit.json"]
    expectation = records["expectation.json"]
    if expectation.get("source") != identity or expectation.get("limits") != LIMITS:
        raise ValueError("Frozen expectation mismatch")
    if expectation.get("command") != COMMAND or expectation.get("learned_prediction") is not False:
        raise ValueError("Unexpected action contract")
    if episode.get("intention") != expectation:
        raise ValueError("Saved intention differs from pre-action expectation")
    result = validate_receipt(records["first-receipt.json"], records["first-session.json"],
                              audit["source_contract"], "first", 1)
    observation = observation_of(result)
    if episode.get("observation") != observation:
        raise ValueError("Saved observation differs from raw receipt")
    return {"schema": "tadash-motion-evidence-decision/1", "decision": "execute_second_one_step",
            "rule": "continue_only_after_verified_completed_settled_first_step",
            "evidence_sha256": expected_episode_sha256, "source": identity,
            "checkpoint_sha256": result["checkpoint"]["sha256"],
            "recovered_observation": observation, "learned_policy": False,
            "quality_improvement_established": False, "cold_process_pid": os.getpid()}


def observation_of(result):
    fields = ("accepted_steps", "max_tilt_deg", "max_joint_limit_excess_rad", "final_max_generalized_speed",
              "pelvis_displacement_xyz_m", "start_time", "end_time", "max_motor_torque_fraction")
    return {**{key: result[key] for key in fields}, "checkpoint_sha256": result["checkpoint"]["sha256"]}


def continuity(first, second):
    return {"qpos_exact": first["final_qpos"] == second["initial_qpos"],
            "qvel_exact": first["final_qvel"] == second["initial_qvel"],
            "time_exact": first["end_time"] == second["start_time"],
            "integration_exact": digest(first["checkpoint"]["value"]["integration"]) == second["initial_integration_sha256"],
            "checkpoint_exact": first["checkpoint"]["sha256"] == second["continued_from"],
            "second_initialization_zero": second["initialization_seconds"] == 0,
            "opposite_feet": first["steps"][0]["swing_side"] != second["steps"][0]["swing_side"]}


def tree_hashes(folder):
    paths = sorted(Path(folder).rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Evidence tree contains symlink")
    return {str(path.relative_to(folder)): sha(path) for path in paths
            if path.is_file() and path.name != "session.lock"}


def capture_arguments(session):
    script = """import json, sys
from examples.nasuraya_research.articulated.render_motion_commands import load_records
records = load_records(sys.argv[1])
print(json.dumps(dict(commands=len(records), frames=[len(r['time']) for r in records],
                     start_time=float(records[0]['time'][0]), end_time=float(records[-1]['time'][-1]),
                     receipt_and_pose_boundaries_agree=True), allow_nan=False))
"""
    return ["-c", script, str(session)]


def snapshot_motion(source, destination):
    hashes = tree_hashes(source)
    destination.mkdir(exist_ok=False)
    for name in hashes:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write((source / name).read_bytes()); handle.flush(); os.fsync(handle.fileno())
    if tree_hashes(destination) != hashes:
        raise ValueError("Motion snapshot changed while copying")
    return hashes


def run_episode(source, output, command_timeout=300):
    source, output = Path(source).resolve(), Path(output).resolve()
    identity = source_identity(source)
    harness_sha256 = sha(Path(__file__))
    output.mkdir(parents=True, exist_ok=False)
    write(output / "status.json", {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat()})
    processes = []
    def child(name, arguments, *, cwd=source, timeout=command_timeout):
        started = time.monotonic()
        with (output / f"{name}.stdout.log").open("x") as stdout, (output / f"{name}.stderr.log").open("x") as stderr:
            process = subprocess.Popen([sys.executable, *arguments], cwd=cwd, env=clean_env(), stdout=stdout, stderr=stderr)
            try:
                code = process.wait(timeout=timeout)
            except BaseException as error:
                if process.poll() is None:
                    process.kill()
                process.wait()
                processes.append({"name": name, "pid": process.pid, "exit_code": process.returncode,
                                  "wall_seconds": time.monotonic() - started, "interrupted": type(error).__name__})
                if isinstance(error, subprocess.TimeoutExpired):
                    raise TimeoutError(f"{name} timed out; no retry or next motion is permitted") from error
                raise
        processes.append({"name": name, "pid": process.pid, "exit_code": code,
                          "wall_seconds": time.monotonic() - started})
        if code:
            raise RuntimeError(f"{name} failed with exit {code}; inspect its logs")
        return read(output / f"{name}.stdout.log")
    try:
        audit_script = """import json
from examples.nasuraya_research.articulated.canon_trial import audit, CANDIDATE
from examples.nasuraya_research.articulated.checkpoint import source_contract
print(json.dumps(dict(morphology=audit(CANDIDATE), source_contract=source_contract(model_dir=CANDIDATE, geometry_support=True)), allow_nan=False))
"""
        audit = child("audit", ["-c", audit_script], timeout=60)
        morphology = audit["morphology"]
        if (abs(morphology["mass_kg"] - 78) > 1e-8 or abs(morphology["crown_height_m"] - 1.7) > 1e-8
                or morphology["model_sha256"] != MODEL_SHA256
                or morphology["fingers_per_hand"] != {"L": 5, "R": 5}
                or morphology["toes_per_foot"] != {"L": 3, "R": 3}
                or morphology["positive_inertias"] is not True
                or morphology["initial_self_collisions"] != []):
            raise ValueError("Compiled v03 audit differs from required body")
        write(output / "model-audit.json", audit)
        expectation = {"schema": "tadash-motion-expectation/1", "source": identity, "command": COMMAND,
                       "limits": LIMITS, "learned_prediction": False,
                       "meaning": "Predeclared existing controller/checkpoint acceptance bounds, not a forecast of measured values.",
                       "source_of_bounds": "pinned stepping.py balance/joint guards and checkpoint.py settled boundary"}
        write(output / "expectation.json", expectation)
        frozen_expectation_sha = sha(output / "expectation.json")
        session = output / "motion"
        child("start", ["-m", MODULE, "start", "--session", str(session), "--max-steps", "2"], timeout=60)
        source_identity(source)
        first_output = child("first", ["-m", MODULE, "run", "--session", str(session), "--id", "first", "--command", COMMAND])
        if first_output.get("replayed") is not False:
            raise ValueError("First motion unexpectedly replayed")
        first_receipt, first_session = read(session / "first.json"), read(session / "session.json")
        first = validate_receipt(first_receipt, first_session, audit["source_contract"], "first", 1)
        write(output / "first-receipt.json", first_receipt)
        write(output / "first-session.json", first_session)
        capture_first = child("capture-first", capture_arguments(session), timeout=60)
        write(output / "capture-first.json", capture_first)
        if sha(output / "expectation.json") != frozen_expectation_sha:
            raise ValueError("Pre-action expectation changed")
        evidence = {name: sha(output / name) for name in ("first-receipt.json", "first-session.json", "model-audit.json", "expectation.json", "capture-first.json")}
        motion_files = snapshot_motion(session, output / "first-motion")
        episode = {"schema": EPISODE_SCHEMA, "source": identity, "intention": expectation,
                   "observation": observation_of(first),
                   "interpretation": "One successful bounded mechanical command; no muscle fatigue, emotional state or learned improvement inferred.",
                   "evidence": evidence, "motion_files": motion_files, "motion_snapshot": "first-motion",
                   "harness_sha256": harness_sha256}
        write(output / "episode.json", episode)
        anchor = sha(output / "episode.json")
        script = str(Path(__file__).resolve())
        decision = child("cold-recovery", [script, "--recover", "--motion-source", str(source), "--output", str(output),
                                           "--episode-sha256", anchor], cwd=output, timeout=60)
        if decision["cold_process_pid"] == os.getpid() or decision["decision"] != "execute_second_one_step":
            raise ValueError("Cold decision was not obtained in a new process")
        if sha(session / "session.json") != sha(output / "first-session.json"):
            raise ValueError("Live session changed after saved experience")
        if sha(session / "first.json") != sha(output / "first-receipt.json"):
            raise ValueError("Live receipt changed after saved experience")
        source_identity(source)
        second_output = child("second", ["-m", MODULE, "run", "--session", str(session), "--id", "second", "--command", COMMAND])
        if second_output.get("replayed") is not False:
            raise ValueError("Second motion unexpectedly replayed")
        second = validate_receipt(read(session / "second.json"), read(session / "session.json"), audit["source_contract"], "second", 2)
        checks = continuity(first, second)
        if not all(checks.values()):
            raise ValueError("Physical continuation mismatch")
        capture_final = child("capture-final", capture_arguments(session), timeout=60)
        write(output / "capture-final.json", capture_final)
        before_replay = tree_hashes(session)
        replay = child("replay", ["-m", MODULE, "run", "--session", str(session), "--id", "first", "--command", COMMAND], timeout=60)
        checks.update(replay_flag=replay.get("replayed") is True, replay_no_state_change=tree_hashes(session) == before_replay,
                      expectation_unchanged=sha(output / "expectation.json") == frozen_expectation_sha,
                      source_unchanged=source_identity(source) == identity,
                      harness_unchanged=sha(Path(__file__)) == harness_sha256)
        if not all(checks.values()):
            raise ValueError("Replay or immutability check failed")
        summary = {"schema": "tadash-motion-episode-summary/1", "source": identity,
                   "scope": "Two synthetic v03 mechanical commands, cold saved-evidence gate and old-ID replay.",
                   "morphology": morphology, "checks": checks, "accepted_steps": first["accepted_steps"] + second["accepted_steps"],
                   "peak_tilt_deg": max(first["max_tilt_deg"], second["max_tilt_deg"]),
                   "final_max_generalized_speed": second["final_max_generalized_speed"],
                   "total_pelvis_displacement_xyz_m": [b - a for a, b in zip(first["initial_qpos"][:3], second["final_qpos"][:3])],
                   "simulation_interval_s": [first["start_time"], second["end_time"]],
                   "simulation_span_s": second["end_time"] - first["start_time"],
                   "first_initialization_s": first["initialization_seconds"], "second_initialization_s": second["initialization_seconds"],
                   "max_motor_fraction": max(first["max_motor_torque_fraction"], second["max_motor_torque_fraction"]),
                   "cold_decision": decision, "episode_sha256": anchor, "processes": processes,
                   "harness_sha256": harness_sha256,
                   "capture_validation": capture_final,
                   "limitations": ["The second action is selected by a fixed verified-evidence gate; learning or decision-quality improvement is not established.",
                                   "No Hindsight, Graphiti, language model, GPU training or human data in this experiment.",
                                   "The 195 kg physiological subsystem is not executed or rescaled; this is the 78 kg mechanical body.",
                                   "Hashes are run-local integrity checks, not cryptographic identity signatures."]}
        write(output / "summary.json", summary)
        write(output / "status.json", {"status": "completed", "completed_utc": datetime.now(timezone.utc).isoformat()}, replace=True)
        write(output / "manifest.json", tree_hashes(output))
        return summary
    except BaseException as error:
        write(output / "status.json", {"status": "failed_or_unknown", "error": f"{type(error).__name__}: {error}",
                                       "no_automatic_retry": True, "completed_processes": processes}, replace=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--command-timeout", type=int, default=300)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--episode-sha256")
    args = parser.parse_args()
    if not 1 <= args.command_timeout <= 600:
        parser.error("command timeout must be 1..600 seconds")
    if args.recover:
        if not args.episode_sha256:
            parser.error("cold recovery requires the parent-held episode hash")
        result = recover_episode(args.output, args.episode_sha256, source_identity(args.motion_source))
        if sha(Path(__file__)) != read(args.output / "episode.json")["harness_sha256"]:
            raise ValueError("Cold recovery harness differs from episode code")
        capture = json.loads(subprocess.check_output([sys.executable, *capture_arguments(args.output / "first-motion")],
                                                    cwd=args.motion_source, env=clean_env(), timeout=60, text=True))
        if capture != read(args.output / "capture-first.json"):
            raise ValueError("Cold pose-capture verification differs from saved audit")
        result["cold_capture_verified"] = True
        write(args.output / "cold-decision.json", result)
    else:
        if args.episode_sha256:
            parser.error("episode hash applies only to cold recovery")
        result = run_episode(args.motion_source, args.output, args.command_timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
