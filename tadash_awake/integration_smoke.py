"""Real, source-pinned PR198 offline session -> Awake CI demonstration.

Runs the original Session, DIOS and goal APIs from a separate pinned checkout.
No VPS, remote actions, model calls or unreviewed source migrations.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from . import bridge, core


def run(source_root):
    src = Path(source_root).resolve()
    if not (src / "examples/nasuraya_runtime/session.py").is_file():
        raise ValueError("real PR198 checkout required")
    # GitHub Actions checks out the exact reviewed source SHA before this test.
    sys.path.insert(0, str(src))
    from examples.nasuraya_runtime.__main__ import demo_frames
    from examples.nasuraya_runtime.session import Session

    T = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        shared = Path(tmp) / "source_session"
        awake = Path(tmp) / "awake"
        with Session.create(shared, session_id="awake-smoke", backend="workshop", max_actions=4) as session:
            first = session.step("first", demo_frames(0, 0), expected_revision=0)
            before = session.snapshot()
        with Session(shared) as session:
            if session.snapshot() != before:
                raise AssertionError("source session failed cold recovery")
            second = session.step("second", demo_frames(1, .95), expected_revision=1)
            after = session.snapshot()
        if before["revision"] != 1 or after["revision"] != 2:
            raise AssertionError("source event revision mismatch")
        if before["sensory"]["time"] >= after["sensory"]["time"]:
            raise AssertionError("source sensory clock did not advance")

        if core.tick(awake, T)["status"] != "paused":
            raise AssertionError("Awake must start paused")
        a = bridge.import_snapshot(awake, before, stream="ciworkshop", observed_at=T)
        core.set_paused(awake, False, T)
        first_question = core.tick(awake, T)
        b = bridge.import_snapshot(awake, after, stream="ciworkshop",
                                   observed_at=T + timedelta(minutes=15))
        second_question = core.tick(awake, T + timedelta(minutes=15))
        persisted = core.status(awake)
        if (a["ingest"]["added"] != len(bridge.METRICS)
                or b["ingest"]["added"] != len(bridge.METRICS)
                or second_question["kind"] != "temporal_change"
                or persisted["counts"]["evidence"] != len(bridge.METRICS) * 2
                or persisted["counts"]["ticks"] != 2
                or persisted["paused"]
                or b["dios_goal"] != after["dios"]["goal"]["selected_goal"]):
            raise AssertionError("shared sensory -> DIOS -> goal -> Awake integration failure")
        return {
            "status": "passed_real_offline_components",
            "source_commit": bridge.SOURCE_COMMIT,
            "source_identity": before["source_identity"],
            "read_only_upstream_checkpoints": True,
            "cold_reopen_same_snapshot": True,
            "before_sensor_seconds": before["sensory"]["time"],
            "after_sensor_seconds": after["sensory"]["time"],
            "dios_goal": b["dios_goal"],
            "first_question_kind": first_question["kind"],
            "second_question_kind": second_question["kind"],
            "first_source_action": first["requested"],
            "second_source_action": second["requested"],
            "awake_observations": persisted["counts"]["evidence"],
            "awake_questions": persisted["counts"]["questions"],
            "awake_ticks": persisted["counts"]["ticks"],
            "external_actions": 0,
            "model_api_calls": 0,
            "deployment": "none",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source_root), sort_keys=True, ensure_ascii=False))

if __name__ == "__main__":
    main()
