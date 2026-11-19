"""Fault injection on a disposable public-memory copy; actual parser/GET outcomes.

Imports two exact, previously reviewed project modules. Never writes the primary
episode database or the native body ledger. No simulated callback return values.
"""
from contextlib import closing
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import ssl
import sys
import urllib.request

MODE = "report"
COMMIT = "d620394cdf4d667683b2784ec0427f26cc0ea6b6"
DEPENDENCIES = {
    "moltbook_reflection_train": "fd57b5e77cad14b7240c4af9018db728885f89e7e6c3ee99e071df236fc1b30b",
    "moltbook_memory_compare": "c135c9b657016467046797ab714a6d820c68280e3eff35a5e6a30d47f9871084"}
SCHEMA = "public-memory-fault-recovery/1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value).encode("utf-8"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def dependencies(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    modules = []
    sys.dont_write_bytecode = True
    for name, expected in DEPENDENCIES.items():
        target = root / (name + ".py")
        if not target.exists():
            url = "https://raw.githubusercontent.com/zurvanproject/zohraya/" + COMMIT + "/tools/bridge_jobs/" + name + ".py"
            try:
                import certifi
                context = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                context = ssl.create_default_context()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                 urllib.request.HTTPSHandler(context=context))
            with opener.open(url, timeout=8) as response:
                raw = response.read(24001)
            if len(raw) > 24000 or sha(raw) != expected:
                raise ValueError("DependencyFingerprintMismatch")
            target.write_bytes(raw)
        if target.is_symlink() or sha(target.read_bytes()) != expected:
            raise ValueError("DependencyFingerprintMismatch")
        spec = importlib.util.spec_from_file_location("recovery_dependency_" + name, target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def read_original(memory, expected):
    with closing(sqlite3.connect((Path(memory) / "episodes.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT body FROM episodes WHERE digest=?", (expected,)).fetchone()
    if row is None or digest(json.loads(row[0])) != expected:
        raise ValueError("OriginalIntegrityFailed")
    return json.loads(row[0])


def scenario(native, context, ident):
    r = native.request(context, ident)
    r["context"] = "public-copy-recovery/v1"
    r["goal"] = "Recover an intentionally corrupted disposable copy using actual operations"
    r["evidence"][1]["claim"]["value"] = "Fault-injected copy; actual checksum/GET callback results"
    return r


def witness(ident):
    return {"id": ident, "kind": "observed", "source_ref": "runtime://public-copy-recovery/v1",
        "locator": "actual-callback/" + ident, "source_sha256": sha(Path(__file__).read_bytes()),
        "claim": {"key": "verification_scope", "value": "actual parser or fixed-source HTTP GET outcome under deliberate copy corruption"}}


def seal(root, name, value):
    target = Path(root) / (name + ".json")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(canonical(value), encoding="utf-8")
    os.replace(tmp, target)
    target.with_suffix(".sha256").write_text(digest(value), encoding="ascii")


def unseal(root, name):
    target = Path(root) / (name + ".json")
    value = json.loads(target.read_text(encoding="utf-8"))
    if digest(value) != target.with_suffix(".sha256").read_text(encoding="ascii"):
        raise ValueError("ReceiptIntegrityFailed")
    return value


def operation(root, expected, parser, fetch):
    root = Path(root)
    def execute(action):
        if action["id"] == "use_cached":
            episode = json.loads((root / "corrupt-copy.json").read_text(encoding="utf-8"))
            if digest(episode) != expected:
                raise ValueError("InjectedCopyIntegrityFailed")
        elif action["id"] == "recheck_source":
            items, dates = parser.read_discussion(fetch)
            episode = parser.strict_episode(items, dates)
            if not episode["tree_complete"]:
                raise ValueError("IncompleteFreshTree")
            seal(root, "refetched", episode)
        else:
            raise ValueError("UnsupportedOperation")
        return {"status": "ready", "sha256": digest(episode), "nodes": len(episode["nodes"]),
                "source": parser.ORIGIN}
    return execute


def selected(row):
    return {"id": row["id"], "action": row["selected_action"], "actual": row["actual_outcome"],
            "success": row["feedback"]["success"], "recalled": row["recalled_feedback_ids"]}


def run(root, memory, context, native, parser, Engine, fetch):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    if (root / "result.json").exists():
        return inspect(root, memory, context, native, parser, Engine, cold=False)
    expected = context["observation_sha256"]
    original = read_original(memory, expected)
    anchor = sha((Path(memory) / "anchor.json").read_bytes())
    damaged = copy.deepcopy(original)
    damaged["nodes"][0]["content"] += "\n[DELIBERATE FAULT IN DISPOSABLE TEST COPY]"
    (root / "corrupt-copy.json").write_text(canonical(damaged), encoding="utf-8")
    execute = operation(root, expected, parser, fetch)
    rows = {}
    for role, use_memory in (("baseline", False), ("memory", True)):
        with Engine(root / (role + ".sqlite3"), use_memory=use_memory) as engine:
            rows[role] = []
            for step in (1, 2):
                ident = role + "-" + str(step)
                row = engine.execute(scenario(native, context, ident), execute, verified=True,
                    evidence=[witness(ident)], reason="Actual callback result under explicitly injected disposable-copy corruption")
                rows[role].append(selected(row))
    if native.source_context(memory) != context or digest(read_original(memory, expected)) != expected:
        raise ValueError("OriginalChanged")
    if sha((Path(memory) / "anchor.json").read_bytes()) != anchor:
        raise ValueError("AnchorChanged")
    b, learned = rows["baseline"], rows["memory"]
    success = (all(r["action"] == "use_cached" and r["actual"].get("error_type") == "ValueError" for r in b)
               and learned[0]["actual"].get("error_type") == "ValueError"
               and learned[1]["action"] == "recheck_source" and learned[1]["success"])
    data = {"schema": SCHEMA, "context": context, "rows": rows, "success": success,
            "fault_injected": True, "actual_callbacks": True, "synthetic_callback_returns": False,
            "original_sha256": expected, "anchor_sha256": anchor,
            "dependencies": DEPENDENCIES, "native_body_cycles": 0, "model_api_calls": 0}
    if success:
        fresh = unseal(root, "refetched")
        if digest(fresh) != learned[1]["actual"]["sha256"]:
            raise ValueError("FreshReceiptMismatch")
    seal(root, "result", data)
    return data


def inspect(root, memory, context, native, parser, Engine, cold=True):
    root = Path(root)
    data = unseal(root, "result")
    if data["schema"] != SCHEMA or data["context"] != context or data["dependencies"] != DEPENDENCIES:
        raise ValueError("RecoveryContextMismatch")
    if digest(read_original(memory, data["original_sha256"])) != data["original_sha256"]:
        raise ValueError("OriginalChanged")
    if sha((Path(memory) / "anchor.json").read_bytes()) != data["anchor_sha256"]:
        raise ValueError("AnchorChanged")
    if not data["success"]:
        return data
    fresh = unseal(root, "refetched")
    if digest(fresh) != data["rows"]["memory"][1]["actual"]["sha256"]:
        raise ValueError("FreshReceiptMismatch")
    if cold:
        with Engine(root / "memory.sqlite3") as engine:
            first = engine.get("memory-1")
            second = engine.get("memory-2")
            if selected(first) != data["rows"]["memory"][0] or selected(second) != data["rows"]["memory"][1]:
                raise ValueError("NativeReceiptMismatch")
            chosen = engine.decide(scenario(native, context, "cold-probe"))
            if chosen["selected_action"] != "recheck_source" or "memory-1" not in chosen["recalled_feedback_ids"]:
                raise ValueError("ColdPreferenceMismatch")
    return data


def summary(data, cold=False):
    if not data["success"]:
        return "RECOVERY=NOT_RECOVERED;FAULT=INJECTED;ORIG=OK;BODY=0;API=0"
    return (f"RECOVERY={'RECOVERED' if cold else 'EXECUTED'};BASE=FAIL/FAIL;MEM=FAIL/READY;"
            f"COLD={int(cold)};FAULT=INJECTED;ORIG=OK;SIG={digest(data)[:16]};BODY=0;API=0")


def main():
    try:
        local = Path(os.environ["LOCALAPPDATA"])
        memory = local / "Nasuraya/PublicMemoryV1"
        native, parser = dependencies(memory / "RecoveryLabV1/dependencies")
        Engine = native.load_engine(local / "NasurayaTadashV1" / ("runtime-" + native.PACKAGE[:16]))
        context = native.source_context(memory)
        root = memory / "RecoveryLabV1" / context["decision_sha256"][:16]
        data = (run(root, memory, context, native, parser, Engine, parser.fetch_page) if MODE == "run"
                else inspect(root, memory, context, native, parser, Engine))
        result = summary(data, cold=MODE == "report")
    except Exception as error:
        result = "RECOVERY=FAILED;ERROR=" + type(error).__name__
    print(json.dumps({"status": "ok", "summary": result}, separators=(",", ":")))


if __name__ == "__main__":
    main()
