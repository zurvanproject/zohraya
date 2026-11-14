"""Cross-platform CI smoke: real pinned Stage3 creates hourly Awake evidence."""
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from . import core, live_ingress


def smoke(source_root):
    src = Path(source_root).resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src, text=True).strip()
    if head != live_ingress.SOURCE_COMMIT:
        raise ValueError("not the pinned PR198 source checkout")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "awake"
        mirror = root / "source_pr198"
        mirror.mkdir(parents=True)
        blobs = {}
        for path in src.rglob("*"):
            if any(part in (".git", "__pycache__") for part in path.relative_to(src).parts):
                continue
            if path.is_symlink():
                raise ValueError("source symlink rejected")
            if path.is_file():
                rel = path.relative_to(src)
                raw = path.read_bytes()
                destination = mirror / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                blobs[str(rel).replace("\\", "/")] = live_ingress.blob_sha(raw)
        if len(blobs) < live_ingress.PINNED_FILE_COUNT_MIN:
            raise AssertionError("source checkout incomplete")
        root.joinpath("source_manifest.json").write_text(
            core.encode({"commit": live_ingress.SOURCE_COMMIT,
                         "tree": live_ingress.SOURCE_TREE, "blobs": blobs}), encoding="utf-8")
        state = root / "state"
        db = core.connect(state)
        db.close()
        core.set_paused(state, False)
        T = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
        first = live_ingress.run(root, T)
        immediate = live_ingress.run(root, T + timedelta(minutes=10))
        second = live_ingress.run(root, T + timedelta(minutes=60))
        records = core.status(state)
        if (first["status"] != "imported_simulation" or first["imported"] != 6
                or immediate["status"] != "deferred_hourly"
                or second["status"] != "imported_simulation" or second["imported"] != 6
                or records["counts"]["evidence"] != 12 or records["counts"]["questions"] < 1
                or records["counts"]["ticks"] != 2):
            raise AssertionError("real source-derived sensor/DIOS import failed")
        with (mirror / "README.md").open("ab") as f:
            f.write(b"\nTAMPER\n")
        try:
            live_ingress.run(root, T + timedelta(hours=2))
            raise AssertionError("tampered source was not rejected")
        except ValueError as err:
            if "integrity" not in str(err):
                raise
        after = core.status(state)
        if after["counts"] != records["counts"]:
            raise AssertionError("invalid source must not alter Awake state")
        return {"result": "passed_pinned_simulation_live_ingress",
                "source_commit": head, "source_files_verified": len(blobs),
                "ingress_revisions": [first["revision"], second["revision"]],
                "imported_events": records["counts"]["evidence"],
                "awake_questions": records["counts"]["questions"],
                "awake_ticks": records["counts"]["ticks"],
                "early_repeat": immediate["status"], "tamper_rejected": True,
                "sensor_type": "synthetic_numeric_fixture",
                "physical_sensors": False, "model_api_calls": 0, "external_actions": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    args = parser.parse_args()
    print(json.dumps(smoke(args.source_root), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
