"""Generate whole trajectories from the pinned body, then cold-read each split."""
import argparse
import asyncio
from copy import deepcopy
from datetime import timedelta
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from ..__main__ import copy_runtime, write_json
from ..graph import store_and_recall
from ..runtime import native_template, run_case

PROTOCOL = Path(__file__).with_name("protocol.json")


def collect(destination):
    plan = json.loads(PROTOCOL.read_text())
    destination = destination.absolute()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        root = Path(temp)
        out = root / "traces"
        out.mkdir()
        copy_runtime(root / "native")
        initial = native_template(root / "native")
        from persistent_embodiment_v1 import instant
        receipt = {}
        for split in ("fit", "panel_a", "panel_b"):
            rows = []
            for case, action, seconds, fatigue, mask, seed in plan[split]:
                template = deepcopy(initial)
                end = instant(template.owner.wall_utc) + timedelta(seconds=seconds)
                template.cycle(event_id=case + "-warmup", at_utc=end.isoformat(),
                               duration_s=seconds, requested=action)
                rows.extend(run_case(template, case, plan["cycles_per_case"], fatigue,
                                     missing_first=mask, arm_seed=seed))
            db = root / split
            db.mkdir()
            recovered, graph = asyncio.run(store_and_recall(db, rows))
            encoded = "".join(json.dumps(r, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False) + "\n" for r in recovered).encode()
            (out / (split + ".jsonl.gz")).write_bytes(gzip.compress(encoded, mtime=0))
            receipt[split] = {
                "graphiti": graph, "uncompressed_sha256": hashlib.sha256(encoded).hexdigest(),
                "native_ticks": sum(r["native_ticks"] for r in recovered),
                "myo_control_steps": sum(r["after_myo"]["control_steps"] for r in recovered),
            }
        write_json(out / "collection.json", receipt)
        out.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    collect(parser.parse_args().destination)
