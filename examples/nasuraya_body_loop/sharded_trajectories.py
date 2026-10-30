"""Run independently seeded body trajectories on one worker or across ten workers."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .__main__ import ROOT, SOURCE, verified_sources
from .multistep_breath_audit import DURATION, FIT_SHA256, cases, feedback_gate
from .rare_breath_audit import bracket

STEPS = 15


def panel():
    original = cases()
    for ident, fatigue in (("trajectory-09", .512), ("trajectory-10", .548)):
        original.append(dict(id=ident, initial=dict(fatigue=fatigue, pain=.08, sleep=.49)))
    return original


def trajectory(index, case, origin, fit):
    from .continuous_self_eval import make_body, start_session
    from .continuous_self_knowledge import native_feedback
    from .experience import metrics
    from .host import executed_body
    from .self_knowledge_eval import _append

    name = case["id"]
    records = []
    previous = None
    next_checkpoint = None
    prior_ids = set()
    with start_session(Path(name + ".sqlite"), name, make_body(origin, case["initial"]), STEPS) as loop:
        for step in range(1, STEPS + 1):
            ident = f"{name}-step-{step}"
            snapshot = loop.observe()
            checkpoint = snapshot["checkpoint_sha256"]
            if next_checkpoint is not None and checkpoint != next_checkpoint:
                raise ValueError(f"trajectory continuity failure at {ident}")
            before = metrics(snapshot)
            recalled = native_feedback(loop, snapshot, DURATION)
            if any(i is not None and i not in prior_ids for i in recalled["source_ids"].values()):
                raise ValueError(f"non-causal feedback at {ident}")
            guess = feedback_gate(bracket(fit, before), previous, recalled["state"])
            row = dict(id=ident, step=step, clock=snapshot["simulated_wall_utc"], before=before,
                       previous=previous, feedback=recalled["state"], forecast=guess)
            # Freeze the pre-action information in the private run directory.
            _append(Path(name + ".forecasts.jsonl"), row)
            receipt = loop.step(decision_id=ident, duration_s=DURATION, preferred_action="walk")
            native = loop.engine.get(ident)
            if (not executed_body(native) or receipt["replayed"]
                    or native["request"]["evidence"][0]["source_sha256"] != checkpoint):
                raise ValueError(f"missing fresh native receipt at {ident}")
            actual = native["actual_outcome"]["body_receipt"]["owner"]["selected_action"]
            after = receipt["self_model_after"]
            elapsed = datetime.fromisoformat(after["simulated_wall_utc"]) - datetime.fromisoformat(row["clock"])
            next_checkpoint = after["checkpoint_sha256"]
            if actual != receipt["actual_action"] or elapsed != timedelta(seconds=DURATION) or next_checkpoint == checkpoint:
                raise ValueError(f"native action, clock or checkpoint mismatch at {ident}")
            records.append(dict(row, native_request=receipt["requested_action"], actual=actual))
            previous = actual
            prior_ids.add(ident)
    return dict(shard=index, id=name, initial=case["initial"], steps=records)


def worker(shard, output):
    from synthetic_fixture import prepare_defaults, synthetic_origin

    encoded = (ROOT / "docs/evidence/cloud-breath-audit/fit.json").read_bytes()
    if hashlib.sha256(encoded).hexdigest() != FIT_SHA256:
        raise ValueError("frozen fit artifact changed")
    fit = json.loads(encoded)
    prepare_defaults()
    origin = synthetic_origin()
    cases_by_index = panel()
    indices = range(len(cases_by_index)) if shard == "all" else [int(shard)]
    trajectories = [trajectory(i, cases_by_index[i], origin, fit) for i in indices]
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(dict(schema="nasuraya-ten-trajectories/1", trajectories=trajectories), stream,
                  ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", required=True, choices=["all", *(str(i) for i in range(10))])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output must be a fresh path")
    with tempfile.TemporaryDirectory(prefix="nasuraya-sharded-") as directory:
        scratch = Path(directory)
        for name in verified_sources():
            target = scratch / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((directory, str(ROOT))))
        env.pop("OPENAI_API_KEY", None)
        launch = "from examples.nasuraya_body_loop.sharded_trajectories import worker; import sys; worker(*sys.argv[1:])"
        subprocess.run([sys.executable, "-c", launch, args.shard, str(output)], cwd=scratch, env=env, check=True)


if __name__ == "__main__":
    main()
