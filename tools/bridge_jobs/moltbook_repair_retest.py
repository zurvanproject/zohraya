"""Revalidate a repaired local copy on an isolated fork of the recovery ledger."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import sys
import tempfile
import urllib.request

PRIOR_COMMIT = "8da7df54e63d7ac7970f87f8457e322a6c0d7f05"
PRIOR_HASH = "a48f6a755326a02211cb72fd67399ad9836f8ca27fb1b784613c9b16464bcdc9"
SCHEMA = "local-repair-retest/1"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_recovery(depdir):
    depdir.mkdir(exist_ok=True, parents=True)
    target = depdir / "moltbook_recovery_run.py"
    if not target.exists():
        url = (f"https://raw.githubusercontent.com/zurvanproject/zohraya/{PRIOR_COMMIT}"
               "/tools/bridge_jobs/moltbook_recovery_run.py")
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                             urllib.request.HTTPSHandler(context=context))
        with opener.open(url, timeout=8) as response:
            raw = response.read(24001)
        if len(raw) > 24000 or hashlib.sha256(raw).hexdigest() != PRIOR_HASH:
            raise ValueError("PriorModuleMismatch")
        with tempfile.NamedTemporaryFile(dir=depdir, delete=False) as f:
            f.write(raw)
            temporary = f.name
        os.replace(temporary, target)
    if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != PRIOR_HASH:
        raise ValueError("PriorModuleMismatch")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("prior_recovery", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def db_readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)


def backup(source, destination):
    with closing(db_readonly(source)) as original, closing(sqlite3.connect(destination)) as clone:
        original.backup(clone)


def stored(db, ident):
    row = db.execute("SELECT record FROM decisions WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise ValueError("MissingNativeReceipt")
    return json.loads(row[0])


def prior_state(memory, context, recovery, native, parser, Engine):
    prior = memory / "RecoveryLabV1" / context["decision_sha256"][:16]
    receipt = recovery.inspect(prior, memory, context, native, parser, Engine, cold=False)
    if not receipt["success"]:
        raise ValueError("EarlierRecoveryIncomplete")
    first, second = receipt["rows"]["memory"]
    with closing(db_readonly(prior / "memory.sqlite3")) as db:
        for expected in (first, second):
            if recovery.selected(stored(db, expected["id"])) != expected:
                raise ValueError("PriorLedgerMismatch")
    fresh = recovery.unseal(prior, "refetched")
    if (fresh.get("source") != parser.ORIGIN or fresh.get("tree_complete") is not True or
            second["actual"]["sha256"] != recovery.digest(fresh)):
        raise ValueError("PriorFreshSnapshotMismatch")
    damaged = json.loads((prior / "corrupt-copy.json").read_text(encoding="utf-8"))
    if (recovery.digest(damaged) == receipt["original_sha256"] or
            recovery.digest(damaged) == recovery.digest(fresh)):
        raise ValueError("InvalidFaultFixture")
    return prior, receipt, fresh, damaged


def choice(row):
    local = next(option for option in row["options"] if option["action_id"] == "use_cached")
    return {"choice": row["selected_action"], "penalty": local["memory_penalty"],
            "feedback": local["recalled_feedback_id"]}


def probe(engine, recovery, native, context, ident):
    request = recovery.scenario(native, context, ident)
    if set(action["id"] for action in request["actions"]) != {"use_cached", "recheck_source"}:
        raise ValueError("BothCandidatesRequired")
    return choice(engine.decide(request))


def verified_local(path, snapshot_hash, recovery, origin):
    episode = json.loads(path.read_text(encoding="utf-8"))
    if (recovery.digest(episode) != snapshot_hash or episode.get("source") != origin
            or episode.get("tree_complete") is not True):
        raise ValueError("RepairedCopyInvalid")
    return {"status": "ready", "sha256": snapshot_hash, "source": origin, "nodes": len(episode["nodes"])}


def exercise(stage, prior, receipt, fresh, damaged, context, recovery, native, parser, Engine):
    ledger = stage / "ledger.sqlite3"
    backup(prior / "memory.sqlite3", ledger)
    copy_file = stage / "cache.json"
    copy_file.write_text(recovery.canonical(damaged), encoding="utf-8")
    expected = recovery.digest(fresh)
    def read_local(action):
        if action["id"] != "use_cached":
            raise ValueError("UnexpectedProbeAction")
        return verified_local(copy_file, expected, recovery, parser.ORIGIN)

    with Engine(ledger) as engine:
        before = probe(engine, recovery, native, context, "repair-before")
        copy_file.write_text(recovery.canonical(fresh), encoding="utf-8")
        control = probe(engine, recovery, native, context, "repair-bytes-only")
        request = recovery.scenario(native, context, "repair-explicit-validation")
        request["actions"] = [action for action in request["actions"] if action["id"] == "use_cached"]
        witness = {"id": "local-repair-validation", "kind": "observed",
                   "source_ref": "local://RepairRetestV1/cache.json", "locator": "verified-local-read",
                   "source_sha256": expected,
                   "claim": {"key": "verification_scope", "value": "checksum of independently stored refetched snapshot"}}
        checked = engine.execute(request, read_local, verified=True, evidence=[witness],
                                 reason="Operator-initiated local validation on the isolated repaired copy")
        after = probe(engine, recovery, native, context, "repair-after")
        # Free execution must actually use the newly preferred route with both candidates available.
        free = engine.execute(recovery.scenario(native, context, "repair-free-execution"),
                              read_local, verified=True, evidence=[witness],
                              reason="Normal two-option execution with a checksum-verified local return")
    negative = {"choice": "recheck_source", "penalty": .6, "feedback": "memory-1"}
    positive = {"choice": "use_cached", "penalty": 0., "feedback": "repair-explicit-validation"}
    if before != negative or control != negative or after != positive:
        raise ValueError("UnexpectedRepairTrajectory")
    for row in (checked, free):
        if (row["selected_action"] != "use_cached" or not row["feedback"]["success"] or
                not row["feedback"]["verified"] or row["actual_outcome"].get("sha256") != expected):
            raise ValueError("LocalReadDidNotSucceed")
    with Engine(ledger) as reopened:
        cold = probe(reopened, recovery, native, context, "repair-reopened")
    if cold != {"choice": "use_cached", "penalty": 0., "feedback": "repair-free-execution"}:
        raise ValueError("ColdSelectionMismatch")
    result = {"schema": SCHEMA, "context": context, "success": True,
              "prior_result_sha256": recovery.digest(receipt), "validated_sha256": expected,
              "before": before["choice"], "control": control["choice"], "after": after["choice"], "cold": cold["choice"],
              "choices": {"before": before, "control": control, "after": after, "cold": cold},
              "validation": recovery.selected(checked), "free_execution": recovery.selected(free),
              "forced_validation": True, "moltbook_gets": 0}
    recovery.seal(stage, "result", result)


def verify(directory, receipt, fresh, context, recovery, native, parser, Engine, replay):
    result = recovery.unseal(directory, "result")
    if (result.get("schema") != SCHEMA or result.get("context") != context or
            result.get("prior_result_sha256") != recovery.digest(receipt) or
            result.get("validated_sha256") != recovery.digest(fresh)):
        raise ValueError("RetestContextMismatch")
    verified_local(directory / "cache.json", result["validated_sha256"], recovery, parser.ORIGIN)
    with closing(db_readonly(directory / "ledger.sqlite3")) as db:
        for ident in ("memory-1", "memory-2"):
            source = next(row for row in receipt["rows"]["memory"] if row["id"] == ident)
            if recovery.selected(stored(db, ident)) != source:
                raise ValueError("InheritedReceiptMismatch")
        for key, ident in (("before", "repair-before"), ("control", "repair-bytes-only"),
                           ("after", "repair-after"), ("cold", "repair-reopened")):
            if choice(stored(db, ident)) != result["choices"][key]:
                raise ValueError("PreferenceRecordMismatch")
        for key in ("validation", "free_execution"):
            if recovery.selected(stored(db, result[key]["id"])) != result[key]:
                raise ValueError("ExecutionRecordMismatch")
    if replay:
        with tempfile.TemporaryDirectory(prefix="repair-replay-") as tmp:
            ephemeral = Path(tmp) / "ledger.sqlite3"
            backup(directory / "ledger.sqlite3", ephemeral)
            with Engine(ephemeral) as reopened:
                if reopened.get("repair-independent-replay") is not None:
                    raise ValueError("ReplayProbeAlreadyPresent")
                observed = probe(reopened, recovery, native, context, "repair-independent-replay")
            if observed != result["choices"]["cold"]:
                raise ValueError("IndependentReselectionMismatch")
    return dict(result, replay=replay)


def run(root, memory, context, recovery, native, parser, Engine):
    root, memory = Path(root), Path(memory)
    prior, receipt, fresh, damaged = prior_state(memory, context, recovery, native, parser, Engine)
    root.mkdir(parents=True, exist_ok=True)
    completed = root / "completed"
    created = False
    if not completed.exists():
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=root) as temporary:
            stage = Path(temporary) / "trial"
            stage.mkdir()
            exercise(stage, prior, receipt, fresh, damaged, context, recovery, native, parser, Engine)
            verify(stage, receipt, fresh, context, recovery, native, parser, Engine, replay=False)
            try:
                stage.rename(completed)
                created = True
            except OSError:
                if not completed.is_dir():
                    raise
    return verify(completed, receipt, fresh, context, recovery, native, parser, Engine, replay=not created)


def summary(data):
    replay = data["replay"]
    stable = {key: value for key, value in data.items() if key != "replay"}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()[:16]
    return (f"REPAIR={'REPLAY' if replay else 'RUN'};BEFORE=WEB;BYTES=WEB;PROBE=FORCED;AFTER=LOCAL;"
            f"COLD=LOCAL;LOCAL=OK;GET=0;SIG={digest}")


def main():
    try:
        local = Path(os.environ["LOCALAPPDATA"])
        memory = local / "Nasuraya/PublicMemoryV1"
        lab = memory / "RepairRetestV1"
        depdir = lab / "dependencies"
        recovery = load_recovery(depdir)
        for name, expected in recovery.DEPENDENCIES.items():
            filename = name + ".py"
            cached = memory / "RecoveryLabV1/dependencies" / filename
            if not (depdir / filename).exists() and cached.is_file():
                raw = cached.read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError("CachedDependencyMismatch")
                with tempfile.NamedTemporaryFile(dir=depdir, delete=False) as f:
                    f.write(raw)
                    temporary = f.name
                os.replace(temporary, depdir / filename)
        native, parser = recovery.dependencies(depdir)
        Engine = native.load_engine(local / "NasurayaTadashV1" / ("runtime-" + native.PACKAGE[:16]))
        context = native.source_context(memory)
        data = run(lab / context["decision_sha256"][:16], memory, context, recovery, native, parser, Engine)
        result = summary(data)
    except Exception as error:
        result = "REPAIR=FAILED;ERROR=" + type(error).__name__
    print(json.dumps({"status": "ok", "summary": result}, separators=(",", ":")))


if __name__ == "__main__":
    main()
