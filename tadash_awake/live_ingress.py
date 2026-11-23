"""Hourly, offline, source-pinned PR198 workshop -> Awake experimental ingress.

This is simulated sensory/DIOS evidence, NOT physical sensory input.
It never sends messages or uses network, model API, credentials, or actuators.
One bounded source action per allowed hour, with persistent cold recovery.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from . import bridge, core

SOURCE_COMMIT = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"
SOURCE_TREE = "6ba874c28bd8eec67dde94d6e66b0acc2c87223f"
STREAM = "vpsworkshop"
MAX_ACTIONS = 48
MIN_INGRESS_SECONDS = 3300
PINNED_FILE_COUNT_MIN = 550


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()


def checked_source(root):
    """Verify immutable git-blob identity for every source file before imports."""
    source = Path(root) / "source_pr198"
    manifest_path = Path(root) / "source_manifest.json"
    if not source.is_dir() or source.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("source package missing")
    if manifest_path.stat().st_size > 100000:
        raise ValueError("source manifest oversized")
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (type(record) is not dict or set(record) != {"commit", "tree", "blobs"}
            or record["commit"] != SOURCE_COMMIT or record["tree"] != SOURCE_TREE
            or type(record["blobs"]) is not dict
            or not PINNED_FILE_COUNT_MIN <= len(record["blobs"]) <= 700):
        raise ValueError("source manifest unsupported")
    for name, expected in record["blobs"].items():
        if (type(name) is not str or not name or name.startswith("/")
                or "\\" in name or any(segment in ("", ".", "..") for segment in name.split("/"))
                or type(expected) is not str or len(expected) != 40):
            raise ValueError("unsafe source manifest entry")
        file = source.joinpath(*name.split("/"))
        if file.is_symlink() or not file.is_file() or blob_sha(file.read_bytes()) != expected:
            raise ValueError("pinned source integrity mismatch")
    return source


def event_ids(snapshot):
    sid = snapshot["session_id"]
    source_id = snapshot["source_identity"]
    rev = snapshot["revision"]
    prefix = hashlib.sha256((STREAM + "|" + sid + "|" + source_id).encode()).hexdigest()[:16]
    return ["v3-" + prefix + "-" + str(rev) + "-" + metric for metric in bridge.METRICS]


def last_imported(root, snapshot, now):
    """Read the exact six event IDs; no approximate LIKE scans or offset resets."""
    db = core.connect(Path(root) / "state")
    try:
        ids = event_ids(snapshot)
        rows = [db.execute("SELECT payload FROM evidence WHERE id=?", (key,)).fetchone()
                for key in ids]
        count = sum(row is not None for row in rows)
        if count not in (0, len(ids)):
            raise ValueError("partial historic source revision")
        if not count:
            return None
        items = [json.loads(row[0]) for row in rows]
        # Fail closed if different imported values were recorded for a revision.
        for row, metric in zip(items, bridge.METRICS):
            if row["topic"] != "shared." + STREAM + "." + metric:
                raise ValueError("previous evidence topic mismatch")
        at = core.clock(items[0]["observed_at"])
        if any(item["observed_at"] != items[0]["observed_at"] for item in items):
            raise ValueError("inconsistent historical import timestamps")
        age = (core.clock(now) - at).total_seconds()
        if age < 0:
            raise ValueError("wall clock rollback")
        return age
    finally:
        db.close()


def exclusive_lock(root):
    path = Path(root) / "ingress.lock"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, b"locked\n")
    os.close(fd)
    return path


def run(root, now=None):
    """One limited, safely replayable research step. Never replaces existing data."""
    at = core.clock(now)
    root = Path(root).resolve()
    if not (root / "state" / "awake.sqlite3").is_file():
        raise ValueError("installed Awake database is missing")
    if core.status(root / "state")["paused"]:
        return {"status": "paused", "synthetic_only": True, "model_calls": 0}
    lock = exclusive_lock(root)
    try:
        source = checked_source(root)
        # This import requires the original verified Stage3 checkout and refuses
        # source/schema drift through Session.create()/Session() itself.
        sys.path.insert(0, str(source))
        from examples.nasuraya_runtime.__main__ import demo_frames
        from examples.nasuraya_runtime.session import Session

        session_folder = root / "workshop"
        if session_folder.exists():
            context = Session(session_folder)
        else:
            context = Session.create(
                session_folder, session_id="awakevps", backend="workshop",
                max_actions=MAX_ACTIONS, decoder_version="legacy",
                fixture="normal", at_utc=at.isoformat())
        with context as session:
            snap = session.snapshot()
            rev = snap["revision"]
            if rev:
                age = last_imported(root, snap, at)
                if age is None:
                    added = bridge.import_snapshot(root / "state", snap, stream=STREAM, observed_at=at)
                    result = {"status": "recovered_uningested", "revision": rev,
                              "imported": added["ingest"]["added"]}
                elif rev >= MAX_ACTIONS:
                    result = {"status": "capacity_review", "revision": rev, "imported": 0}
                elif age < MIN_INGRESS_SECONDS:
                    result = {"status": "deferred_hourly", "revision": rev, "imported": 0}
                else:
                    result = None
            else:
                result = None
            if result is None:
                if rev >= MAX_ACTIONS:
                    result = {"status": "capacity_review", "revision": rev, "imported": 0}
                else:
                    # Fixed public numerical fixture: no external sensor is assumed.
                    intensity = .95 if rev % 4 == 2 else 0.
                    session.step("awake" + str(rev + 1), demo_frames(rev, intensity),
                                 expected_revision=rev)
                    snap = session.snapshot()
                    added = bridge.import_snapshot(root / "state", snap,
                                                   stream=STREAM, observed_at=at)
                    if added["ingest"]["added"] != len(bridge.METRICS):
                        raise ValueError("unexpected number of imported observation fields")
                    result = {"status": "imported_simulation", "revision": snap["revision"],
                              "imported": added["ingest"]["added"]}
        if result["imported"]:
            result["awake_tick"] = core.tick(root / "state", now=at)["status"]
        counts = core.status(root / "state")["counts"]
        result.update(awake_events=counts["evidence"], awake_questions=counts["questions"],
                      source_kind="simulated_workshop_not_physical_sensors",
                      source_commit=SOURCE_COMMIT, network_calls=0, model_calls=0,
                      external_actions=0)
        staging = root / "last_ingress.tmp"
        staging.write_text(core.encode(result), encoding="utf-8")
        staging.replace(root / "last_ingress.json")
        return result
    finally:
        lock.unlink()


if __name__ == "__main__":
    try:
        home = Path(__file__).resolve().parents[1]
        receipt = run(home)
        print(core.encode(receipt))
    except BaseException:
        # Task Scheduler will report nonzero; do not publish raw paths or errors.
        print('{"status":"blocked","detail":"local_review_required"}')
        raise SystemExit(2)
