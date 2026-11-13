"""Read-only, source-pinned PR198 shared-session -> Awake evidence bridge.

Only six scalar research signals from a validated snapshot are transferred.
This verifies self-consistency, not cryptographic proof of external origin.
No model invocation, network, shell, physical device or upstream write.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from . import core

SOURCE_COMMIT = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"
SOURCE_REF = "https://github.com/zurvanproject/zohraya/commit/" + SOURCE_COMMIT
SOURCE_SCHEMA = "nasuraya.shared-session/3"
HEX = re.compile(r"[0-9a-f]{64}\Z")
STREAM = re.compile(r"[a-z][a-z0-9_-]{2,23}\Z")
METRICS = ("sensory_load", "prediction_error", "sensory_occurrence",
           "goal_selected", "dios_sensory_stance", "action_matches")


def upstream_hash(obj):
    # Identical to examples.tadash_interoception.state.digest in pinned PR198.
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def bounded_float(value, lo, hi, label):
    if type(value) not in (float, int) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError("invalid " + label)
    return float(value)


def extract(snapshot, *, stream, observed_at):
    if type(snapshot) is not dict or snapshot.get("schema") != SOURCE_SCHEMA:
        raise ValueError("expected PR198 shared-session/3 snapshot")
    if type(stream) is not str or not STREAM.fullmatch(stream):
        raise ValueError("invalid stable stream id")
    at = core.clock(observed_at)
    original = dict(snapshot)
    stated = original.pop("snapshot_sha256", None)
    if type(stated) is not str or not HEX.fullmatch(stated) or upstream_hash(original) != stated:
        raise ValueError("source snapshot integrity mismatch")
    if snapshot.get("external_actions_taken") != 0 or snapshot.get("subjective_experience_established") is not False:
        raise ValueError("not isolated offline research")
    if snapshot.get("stopped") is not False:
        raise ValueError("only active pre-stop snapshots can be imported")
    if snapshot.get("body_profile") != "tadash_reduced_78kg_v1":
        raise ValueError("refuse unreviewed or legacy body lineage")
    if snapshot.get("backend") not in ("workshop", "native"):
        raise ValueError("unsupported source backend")
    identity, model, tail = (snapshot.get(key) for key in ("source_identity", "model_sha", "event_tail"))
    if any(type(value) is not str or not HEX.fullmatch(value) for value in (identity, model, tail)):
        raise ValueError("source/model lineage absent")
    session_id = snapshot.get("session_id")
    if type(session_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        raise ValueError("invalid source session id")
    revision = snapshot.get("revision")
    if type(revision) is not int or not 1 <= revision <= 100 or snapshot.get("actions_used") != revision:
        raise ValueError("expected committed simulated action revision")
    sensory, prediction, dios, receipt = (snapshot.get(key) for key in
                                          ("sensory", "prediction", "dios", "last_receipt"))
    if any(type(x) is not dict for x in (sensory, prediction, dios, receipt)):
        raise ValueError("missing actual sensory/DIOS/goal/receipt fields")
    sample_time = bounded_float(sensory.get("time"), .001, 100000, "sensory sample time")
    load = bounded_float(sensory.get("load"), 0, 1, "sensory load")
    error = bounded_float(sensory.get("prediction_error"), 0, 3, "prediction error")
    if type(prediction.get("occurred")) is not bool:
        raise ValueError("invalid detector reading")
    goal, review = dios.get("goal"), dios.get("sensory_hypothesis_review")
    if type(goal) is not dict or type(review) is not dict:
        raise ValueError("missing durable goal or DIOS review")
    if dios.get("revision") != revision or goal.get("selected_goal") != 1:
        raise ValueError("goal state disagrees with revision")
    stance = review.get("stance")
    if type(stance) is not str or not re.fullmatch(r"[A-Za-z_]{1,48}", stance):
        raise ValueError("invalid DIOS stance")
    if (receipt.get("revision") != revision or receipt.get("model_sha") != model
            or receipt.get("prediction") != prediction
            or receipt.get("local_simulation_only") is not True
            or receipt.get("state_sha") != upstream_hash(sensory)
            or type(receipt.get("outcome_matches_request")) is not bool):
        raise ValueError("action receipt and sensory checkpoint disagree")
    prefix = hashlib.sha256((stream + "|" + session_id + "|" + identity).encode()).hexdigest()[:16]
    values = (load, error, prediction["occurred"], 1, stance, receipt["outcome_matches_request"])
    rows = [
        {"event_id": "v3-" + prefix + "-" + str(revision) + "-" + field,
         "topic": "shared." + stream + "." + field,
         "observed_at": core.iso(at), "sample_time": sample_time,
         "source_ref": SOURCE_REF, "confidence": .70, "value": value}
        for field, value in zip(METRICS, values)
    ]
    return rows, {"source_commit": SOURCE_COMMIT, "snapshot_sha256": stated,
                  "source_identity": identity, "session_id": session_id,
                  "stream": stream, "revision": revision,
                  "sample_time_s": sample_time, "dios_goal": 1, "dios_stance": stance,
                  "sensory_occurrence": prediction["occurred"],
                  "scalars": len(rows), "mode": "offline_snapshot_self_consistency"}


def import_snapshot(root, snapshot, *, stream, observed_at=None):
    at = core.clock(observed_at)
    rows, receipt = extract(snapshot, stream=stream, observed_at=at)
    return {**receipt, "ingest": core.ingest(root, rows, now=at)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--stream", required=True)
    p.add_argument("--observed-at", help="Stable UTC export timestamp for idempotent replay")
    args = p.parse_args(argv)
    try:
        path = Path(args.snapshot)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("not a bounded regular JSON snapshot")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        result = import_snapshot(args.root, snapshot, stream=args.stream, observed_at=args.observed_at)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
