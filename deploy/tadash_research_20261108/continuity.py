"""Read-only metrics for one evening slot. No network, task control or model calls."""
from contextlib import closing
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import time


def sample(worker_root=None, now=None):
    now = time.time() if now is None else now
    result = dict(sampled_at_host_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  ok=False, heartbeat_fresh=None, worker_state=None, native_revision=None,
                  native_cycles=None, unresolved=None, issues=[])
    phase = "worker_config"
    try:
        root = Path(worker_root) if worker_root is not None else Path(os.environ["PROGRAMDATA"]) / "NasurayaModelWorker"
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        native = Path(config["tadash_root"])
        if not native.is_absolute() or native.name != "NasurayaTadashV1":
            raise ValueError("unexpected native location")
        phase = "heartbeat"
        try:
            health = json.loads((root / "health.json").read_text(encoding="utf-8"))
            state = health["state"]
            age = now - float(health["updated_epoch"])
            if not math.isfinite(age):
                raise ValueError("invalid heartbeat")
            result["heartbeat_fresh"] = -5 <= age <= 45
            result["heartbeat_age_s"] = round(age)
            result["worker_state"] = state if state in ("idle", "running", "starting", "paused") else "other"
            if not result["heartbeat_fresh"]:
                result["issues"].append("stale_heartbeat")
            if state not in ("idle", "running"):
                result["issues"].append("worker_state")
            if not config.get("installation_id") or health.get("installation_id") != config["installation_id"]:
                result["issues"].append("worker_identity")
        except (KeyError, ValueError, OSError, TypeError) as error:
            result["issues"].append("heartbeat_" + type(error).__name__)
        phase = "native_ledger"
        uri = (native / "state" / "session.sqlite").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            row = db.execute("SELECT json_extract(value,'$.payload.revision') FROM runtime WHERE key=?",
                             ("nasuraya-vps-body",)).fetchone()
            if row is None or type(row[0]) is not int or row[0] < 0:
                raise ValueError("missing revision")
            cycles, pending = db.execute(
                "SELECT count(CASE WHEN json_type(record,'$.actual_outcome.body_checkpoint') "
                "NOT IN ('null') "
                "AND json_extract(record,'$.status')='complete' THEN 1 END), "
                "count(CASE WHEN json_extract(record,'$.status')='running' THEN 1 END) FROM decisions"
            ).fetchone()
            result.update(native_revision=row[0], native_cycles=cycles, unresolved=pending)
            if pending:
                result["issues"].append("unresolved_native")
    except (KeyError, ValueError, OSError, TypeError, sqlite3.Error) as error:
        result["issues"].append(phase + "_" + type(error).__name__)
    result["ok"] = not result["issues"]
    return result
