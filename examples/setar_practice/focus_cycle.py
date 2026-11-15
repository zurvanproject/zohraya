"""A bounded, opt-in Setar -> evidence review -> optional ritual-audit connector.

The existing native-body bridge remains the only owner of a lesson, its SQLite
checkpoint and curriculum. This module records a three-*stage* evidence review,
NOT three performances of a ritual or a physical motor skill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
PROTOCOL = "nasuraya.focus/setar-three-stage/1"


def _read_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError(f"missing, linked or oversized evidence: {path.name}")
    return path.read_bytes()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data: bytes):
    def no_duplicates(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate JSON key")
            result[k] = v
        return result
    def no_nonfinite(value):
        raise ValueError("nonfinite JSON value")
    return json.loads(data, object_pairs_hook=no_duplicates, parse_constant=no_nonfinite)


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _same_time(value, target):
    return _finite_number(value) and math.isclose(value, target, abs_tol=1e-6)


def _abs_mean(rows, name):
    values = [abs(m[name]) for m in rows if m.get("valid") is True
              and _finite_number(m.get(name))]
    return round(sum(values) / len(values), 4) if values else None


def _audit_external_ritual(path):
    if path is None:
        return {"state": "not_supplied", "source_sha256": None, "textual_completion_claimed": False,
                "vps_execution_verified": False, "embodied_ritual_verified": False}
    raw = _read_bytes(Path(path))
    v = _json_bytes(raw)
    if not isinstance(v, dict):
        raise ValueError("ritual audit must be a JSON object")
    required = {"session_id", "full_passes_completed", "required_full_passes",
                "session_complete_under_three_pass_rule", "mastered",
                "vps_execution_verified", "status"}
    if not required <= v.keys() or type(v["full_passes_completed"]) is not int \
            or type(v["required_full_passes"]) is not int or v["required_full_passes"] < 3 \
            or v["full_passes_completed"] < 0 or not isinstance(v["session_id"], str) \
            or not v["session_id"] or type(v["session_complete_under_three_pass_rule"]) is not bool \
            or v["mastered"] is not False or v["vps_execution_verified"] is not False:
        raise ValueError("unsupported ritual audit assertions")
    complete = v["full_passes_completed"] >= v["required_full_passes"]
    if v["session_complete_under_three_pass_rule"] is not complete or \
            v["status"] != ("COMPLETED_TEXTUAL" if complete else "IN_PROGRESS"):
        raise ValueError("inconsistent textual ritual completion assertion")
    return {"state": "external_textual_audit_attached", "source_sha256": _sha_bytes(raw),
            "ritual_session_id": v["session_id"], "full_passes_completed": v["full_passes_completed"],
            "textual_completion_claimed": complete, "vps_execution_verified": False,
            "embodied_ritual_verified": False,
            "limitations": "JSON audit is a supplied assertion, not an independent witness of ritual quality or duration"}


def build_report(lesson_dir, ritual_audit=None):
    lesson_dir = Path(lesson_dir)
    raw = _read_bytes(lesson_dir / "bridge_receipt.json")
    receipt = _json_bytes(raw)
    if not isinstance(receipt, dict) or receipt.get("state") != "completed" \
            or receipt.get("checkpoint_committed") is not True \
            or receipt.get("blockwise_clock_aligned") is not True \
            or receipt.get("physical_hand_control") is not False \
            or receipt.get("sample_rate_body_coupling") is not False:
        raise ValueError("lesson is not a fully committed, blockwise native-gated synthetic lesson")
    if not isinstance(receipt.get("run_id"), str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", receipt["run_id"]) is None:
        raise ValueError("invalid receipt identity")
    if type(receipt.get("native_cycles_caused")) is not int or receipt["native_cycles_caused"] != 12:
        raise ValueError("expected 12 native observe cycles")
    if not all(_same_time(receipt.get(field), 11.2) for field in
               ("approved_audio_seconds", "body_elapsed_seconds")) or \
            not _same_time(receipt.get("audio", {}).get("duration_s"), 11.2) or \
            not _same_time(receipt.get("clock_residual_seconds"), 0):
        raise ValueError("native and audio clocks disagree")
    if receipt.get("ten_minutes_wall_clock_verified") is not False:
        raise ValueError("unsupported elapsed-time claim")
    files = {}
    for name, target in (("audio", "practice.wav"), ("checkpoint", "checkpoint.json"),
                         ("events", "events.jsonl")):
        files[name] = _read_bytes(lesson_dir / target)
    if _sha_bytes(files["audio"]) != receipt.get("audio", {}).get("sha256") or \
            _sha_bytes(files["checkpoint"]) != receipt.get("checkpoint_sha256"):
        raise ValueError("lesson evidence SHA-256 mismatch")
    notes, feedback = {}, {}
    for raw_line in files["events"].splitlines():
        if not raw_line.strip():
            raise ValueError("empty event line")
        event = _json_bytes(raw_line)
        if not isinstance(event, dict):
            raise ValueError("invalid event")
        if event.get("kind") == "note":
            # The v0.5 renderer stores the note index inside event, whereas
            # delayed feedback stores the event_index at the top level.
            if not isinstance(event.get("event"), dict) or \
                    type(event["event"].get("index")) is not int:
                raise ValueError("note missing stable index")
            i = event["event"]["index"]
            if i in notes:
                raise ValueError("duplicate note")
            notes[i] = event
        elif event.get("kind") == "feedback":
            if type(event.get("event_index")) is not int:
                raise ValueError("feedback missing stable index")
            i = event["event_index"]
            if i in feedback or not isinstance(event.get("measurement"), dict):
                raise ValueError("duplicate or invalid feedback")
            if type(event.get("sample")) is not int or type(event.get("rendered_at_sample")) is not int \
                    or event["sample"] <= event["rendered_at_sample"]:
                raise ValueError("feedback must follow its note")
            feedback[i] = event
        else:
            raise ValueError("unexpected event kind")
    if notes.keys() != feedback.keys() or not notes or \
            len(notes) != receipt.get("note_events") or len(feedback) != receipt.get("released_feedback"):
        raise ValueError("missing or inconsistent feedback")
    for i in notes:
        if feedback[i]["rendered_at_sample"] != notes[i]["sample"] or \
                feedback[i]["sample"] != notes[i]["feedback_available_sample"]:
            raise ValueError("note/feedback timeline mismatch")
    measurements = [feedback[i]["measurement"] for i in sorted(feedback)]
    valid = sum(m.get("valid") is True for m in measurements)
    error = {"pitch_cents_mae": _abs_mean(measurements, "pitch_error_cents"),
             "onset_ms_mae": _abs_mean(measurements, "onset_error_ms"),
             "attack_percent_mae": _abs_mean(measurements, "attack_error_percent")}
    if valid == 0 or any(v is None for v in error.values()):
        raise ValueError("no measurable complete synthetic feedback")
    ritual = _audit_external_ritual(ritual_audit)
    # Three inspection stages are inspired by ritual review, not a ritual
    # performance. No new controller corrections occur in this review.
    review = [
        {"stage": "observe", "facts": {"notes": len(notes), "feedback": len(feedback),
                                        "valid_measurements": valid, "native_cycles": 12}},
        {"stage": "evaluate", "synthetic_audio_errors": error,
         "baseline_comparison": "not_performed", "transfer_to_unseen_tasks": "not_tested"},
        {"stage": "reflect", "next_test": "compare withheld frets and independently scored listening",
         "limits": ["physical fingers not simulated", "no acoustic validation",
                    "three review stages are not three ritual passes"]}
    ]
    return {"schema": PROTOCOL, "run_id": receipt["run_id"],
            "setar": {"state": "completed", "curriculum_index": receipt.get("curriculum_index"),
                      "next_curriculum_index": receipt.get("next_curriculum_index"),
                      "native_cycles": 12, "simulated_seconds": 11.2,
                      "accelerated": receipt.get("accelerated"),
                      "updates_total": receipt.get("total_updates"),
                      "physical_hand_control": False},
            "review": review, "ritual": ritual,
            "provenance_sha256": {"bridge_receipt": _sha_bytes(raw),
                                  **{k: _sha_bytes(v) for k, v in files.items()}},
            "controller_modified_by_review": False,
            "server_deployed": False,
            "overall": "setar_lesson_verified_with_evidence_review",
            "caution": "This is a deterministic reporting link, not ritual mastery, physical playing, GPT weight learning or autonomous VPS work."}


def publish_report(path, report):
    path = Path(path)
    payload = (json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    if path.exists() or path.is_symlink():
        if _read_bytes(path) != payload:
            raise ValueError("existing report differs; refusing to overwrite")
        return "verified_existing"
    # Exclusive creation; no authoritative SQLite change. An incomplete export
    # must not cause replay of the already committed native cycles.
    with path.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    return "created"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    for mode in ("run", "report"):
        p = command.add_parser(mode)
        p.add_argument("--output-dir", required=True, type=Path,
                       help="original lesson output directory")
        p.add_argument("--ritual-audit", type=Path,
                       help="optional verified textual audit from the separate ritual tool")
    runner = command.choices["run"]
    runner.add_argument("--session", type=Path, required=True)
    runner.add_argument("--run-id", required=True)
    runner.add_argument("--seed", type=int, default=4110000)
    clock = runner.add_mutually_exclusive_group(required=True)
    clock.add_argument("--realtime", action="store_true")
    clock.add_argument("--accelerated", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "run":
        invocation = [sys.executable, "-m", "examples.setar_practice.body_cli", "lesson",
                      "--session", str(args.session), "--run-id", args.run_id,
                      "--output-dir", str(args.output_dir), "--seed", str(args.seed),
                      "--realtime" if args.realtime else "--accelerated"]
        finished = subprocess.run(invocation, check=False)
        if finished.returncode:
            raise SystemExit(finished.returncode)
    report = build_report(args.output_dir, args.ritual_audit)
    status = publish_report(args.output_dir / "focused_review.json", report)
    print(json.dumps({"status": status, "report": str(args.output_dir / "focused_review.json"),
                      "run_id": report["run_id"], "ritual": report["ritual"]["state"]},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
