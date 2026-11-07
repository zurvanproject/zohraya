"""Persistent VPS host for source-pinned Tadash; one bounded native cycle per call.
The native 195 kg aggregate software plant and its protections remain unchanged.
New generated fixture state is separate from every prior/user checkpoint.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile

SCHEMA = "nasuraya-tadash-vps/1"
NATIVE_MANIFEST = "b3b95a88885d903f638efbc26ed693bf7a211460a5adae6dd9abfa12ac7720ef"
NATIVE_COMMIT = "5f171aa493b41823b1198f767d803df053884f37"
KEY = "nasuraya-vps-body"
CONTEXT = "vps-native-sleep/1"
MAX_ACTIONS = 20
INSTALL = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_install():
    manifest = json.loads((INSTALL / "FILES_SHA256.json").read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        p = INSTALL / name
        if p.is_symlink() or not p.resolve().is_relative_to(INSTALL) or sha(p.read_bytes()) != expected:
            raise ValueError("installation source mismatch")
    native = INSTALL / "native"
    raw = (native / "PUBLIC_FILES_SHA256.json").read_bytes()
    if sha(raw) != NATIVE_MANIFEST:
        raise ValueError("native source manifest mismatch")
    for name, expected in json.loads(raw).items():
        p = native / name
        if not p.resolve().is_relative_to(native) or sha(p.read_bytes()) != expected:
            raise ValueError("native source mismatch")
    return native


@contextmanager
def native_runtime():
    native = verify_install()
    # Generated defaults are written only to an ephemeral copy, never source.
    with tempfile.TemporaryDirectory(prefix="tadash-native-") as temporary:
        work = Path(temporary) / "native"
        shutil.copytree(native, work)
        import zoneinfo
        zoneinfo.reset_tzpath([str(INSTALL / "tzdata")])
        if os.name == "nt":
            spec = importlib.util.spec_from_file_location("fcntl", INSTALL / "windows_fcntl.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules["fcntl"] = module
            spec.loader.exec_module(module)
        sys.path.insert(0, str(work))
        from reflection_cycle import ReflectionCycle, ReflectiveBody, canonical
        from unified_body_v2 import UnifiedBody
        from synthetic_fixture import prepare_defaults
        from run_reflection_demo import sleep_fixture
        yield ReflectionCycle, ReflectiveBody, UnifiedBody, canonical, prepare_defaults, sleep_fixture


def regular(path):
    if path.exists() and (path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("regular unaliased host file required")


@contextmanager
def host_lock(root):
    root = Path(root).absolute()
    if root.exists() and (root.is_symlink() or not root.is_dir() or root.resolve() != root):
        raise ValueError("dedicated nonaliased state directory required")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / "host.lock.sqlite"
    regular(path)
    db = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        # Separate lock DB; native ledger keeps its own FULL/WAL transactions.
        # OS closes this connection and releases the mutex after a process dies.
        db.execute("BEGIN EXCLUSIVE")
        yield root
    finally:
        db.close()


def checked_ledger(path):
    regular(path)
    if not path.is_file():
        raise ValueError("initialize a new host explicitly")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM meta WHERE key=?", (SCHEMA,)).fetchone()
        if row is None:
            raise ValueError("foreign ledger; no reset")
        config = json.loads(row[0])
        if config != {"schema": SCHEMA, "native_manifest": NATIVE_MANIFEST,
                      "fixture": "sleep", "max_actions": MAX_ACTIONS}:
            raise ValueError("host configuration mismatch; no reset")
    return config


def initialize(root, ReflectionCycle, ReflectiveBody, UnifiedBody, canonical, prepare_defaults, sleep_fixture):
    path = root / "session.sqlite"
    if path.exists():
        checked_ledger(path)
        return
    prepare_defaults()
    with tempfile.TemporaryDirectory(prefix="tadash-init-", dir=root) as tmp:
        staged = Path(tmp) / "new.sqlite"
        with ReflectionCycle(staged) as engine:
            body = sleep_fixture()
            engine.attach_runtime(KEY, body.checkpoint())
            config = {"schema": SCHEMA, "native_manifest": NATIVE_MANIFEST,
                      "fixture": "sleep", "max_actions": MAX_ACTIONS}
            engine.db.execute("INSERT INTO meta VALUES(?,?)", (SCHEMA, canonical(config)))
        # All native handles close before publication. Never overwrite a ledger.
        if path.exists():
            raise ValueError("state appeared during initialization")
        os.rename(staged, path)


def request(decision_id, body):
    envelope = body.checkpoint()
    at = (datetime.fromisoformat(body.owner.wall_utc) + timedelta(seconds=.1)).isoformat()
    evidence = {"id": "body", "kind": "observed", "source_ref": "runtime://UnifiedBody.checkpoint",
                "locator": "revision/" + str(body.revision), "source_sha256": envelope["sha256"],
                "claim": {"key": "body_revision", "value": body.revision}, "expires_at": at}
    actions = []
    for action, preference in (("walk", .9), ("observe", .6)):
        actions.append({"id": action, "body_action": action,
            "score": {"respect": preference, "honesty": preference, "balance": preference,
                      "dignity": preference, "compassion": preference, "disharmony": 0.,
                      "evidence_confidence": 1., "consequences": [
                          {"probability": 1., "harm": .01, "benefit": .5, "cost": 0., "confidence": 1.}]},
            "claims": [], "requires_evidence": ["body"], "requires_tools": ["body_cycle"],
            "violates_goals": [], "expected_outcome": {"status": "completed", "selected_action": action}})
    return {"id": decision_id, "context": CONTEXT, "topic": "optional-motion",
            "goal": "Continue one source-pinned Tadash cycle with authoritative native protection",
            "goals": [{"id": "native_protection", "required": True}], "at_utc": at,
            "evidence": [evidence], "tools": {"body_cycle": "ok"}, "actions": actions}


def snapshot(engine, UnifiedBody, record=None, before=None, replayed=False):
    records = engine.export()["decisions"]
    body = UnifiedBody.restore(engine.runtime(KEY))
    checkpoint = body.checkpoint()
    complete = [r for r in records if r["status"] == "complete" and
                (r.get("actual_outcome") or {}).get("body_checkpoint") is not None]
    actual = (record or {}).get("actual_outcome") or {}
    selected = actual.get("selected_action", "none")
    if selected not in ("none", "walk", "observe", "protect"):
        selected = "other"
    return {"schema": SCHEMA, "status": "ok", "native_commit": NATIVE_COMMIT,
            "native_source_manifest": NATIVE_MANIFEST, "native_legacy_mass_kg": 195,
            "revision": body.revision, "completed_cycles": len(complete),
            "reserved_actions": sum(r["selected_action"] is not None for r in records),
            "max_actions": MAX_ACTIONS, "checkpoint_sha256": checkpoint["sha256"],
            "decision_id": (record or {}).get("id"), "requested": (record or {}).get("selected_action", "none"),
            "actual": selected, "recalled_feedback": len((record or {}).get("recalled_feedback_ids", [])),
            "replayed": replayed, "native_cycles_in_call": 0 if before is None else body.revision - before,
            "receipt_source": (record or {}).get("id"),
            "body_audit": actual.get("body_receipt", {}).get("whole_body_audit"),
            "unresolved": sum(r["status"] == "running" for r in records),
            "synthetic_initial_fixture": True, "physical_actuation": False, "api_calls": 0}


def run(command, root, decision_id=None):
    if command not in ("init", "status", "step", "replay-first"):
        raise ValueError("unsupported bounded host command")
    if decision_id is not None and (not isinstance(decision_id, str) or not re.fullmatch(r"vps-cycle-[1-9][0-9]{0,2}", decision_id)):
        raise ValueError("invalid decision identity")
    with host_lock(root) as state, native_runtime() as runtime:
        ReflectionCycle, ReflectiveBody, UnifiedBody, canonical, prepare_defaults, sleep_fixture = runtime
        path = state / "session.sqlite"
        if command == "init":
            initialize(state, *runtime)
        checked_ledger(path)
        prepare_defaults()
        with ReflectionCycle(path) as engine:
            if command in ("init", "status"):
                return snapshot(engine, UnifiedBody)
            records = engine.export()["decisions"]
            if command == "replay-first":
                if not records:
                    raise ValueError("no completed operation to replay")
                decision_id = records[0]["id"]
            decision_id = decision_id or "vps-cycle-" + str(len(records) + 1)
            previous = engine.get(decision_id)
            if previous is not None and previous["context"] != CONTEXT:
                raise ValueError("foreign decision identity")
            if any(r["status"] == "running" for r in records):
                raise ValueError("unresolved native outcome; no automatic repeat")
            if previous is None and sum(r["selected_action"] is not None for r in records) >= MAX_ACTIONS:
                raise ValueError("persistent action budget exhausted")
            body = UnifiedBody.restore(engine.runtime(KEY))
            before = body.revision
            req = previous["request"] if previous is not None else request(decision_id, body)
            record = ReflectiveBody(engine, key=KEY).cycle(req, at_utc=req["at_utc"], duration_s=.1)
            actual = record.get("actual_outcome") or {}
            if record["status"] != "complete" or "body_checkpoint" not in actual:
                raise ValueError("native cycle did not complete; outcome retained")
            result = snapshot(engine, UnifiedBody, record, before, previous is not None)
            if previous is not None and result["native_cycles_in_call"] != 0:
                raise AssertionError("completed request replay caused another native cycle")
            # Full native receipt/checkpoint is already durably held by ReflectionCycle.
            report = state / "latest.json"
            temporary = state / "latest.json.tmp"
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, report)
            return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "status", "step", "replay-first"))
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--decision-id")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.command, args.state, args.decision_id), ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "rejected", "error_type": type(error).__name__}))
        raise SystemExit(1)

