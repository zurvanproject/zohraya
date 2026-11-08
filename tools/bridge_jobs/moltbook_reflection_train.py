"""Finite controlled feedback exercise using the installed Tadash ReflectionCycle.

Real public-memory provenance; synthetic callback outcomes, no native body cycles.
This exercise does not alter the public follow-up policy or the host's body ledger.
"""
from contextlib import closing
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

MODE = "train"
PACKAGE = "6a0c9fe013aad59716b251c66aadec6081daa764ac76bfdb2dc0763ab2f049cb"
MANIFEST = "1ffedf1f438a2e3b9178a19703cfb2037c5d0296a94743ff9391493edae65d15"
SOURCES = {"decision_core.py": "24d6c8784c154ad22538a19ad7176f9eda4c98524c3a948d1895055e02917c7a",
           "reflection_cycle.py": "eaa098ed8f92d4fc7fdfcacd02a45b59362e4ddae8fa04bdda7c9893fadb8516"}
ORIGIN = "https://www.moltbook.com/post/28bca18b-cba6-443f-b95f-e05aa11e84a2"
SCHEMA = "public-memory-native-reflection/1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value).encode("utf-8"))


def load_engine(installation):
    installation = Path(installation).resolve()
    raw = (installation / "FILES_SHA256.json").read_bytes()
    if sha(raw) != MANIFEST:
        raise ValueError("ManifestMismatch")
    manifest = json.loads(raw)
    sys.dont_write_bytecode = True
    for name, expected in SOURCES.items():
        path = installation / "native" / name
        if (path.is_symlink() or not path.resolve().is_relative_to(installation)
                or manifest.get("native/" + name) != expected or sha(path.read_bytes()) != expected):
            raise ValueError("NativeSourceMismatch")
        module_name = path.stem
        if module_name in sys.modules:
            old = sys.modules[module_name]
            if Path(old.__file__).resolve() != path.resolve():
                raise ValueError("ForeignLoadedModule")
            continue
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sys.modules["reflection_cycle"].ReflectionCycle


def source_context(memory_root):
    uri = (Path(memory_root) / "episodes.sqlite3").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        row = db.execute("SELECT body,digest FROM decisions WHERE id=(SELECT id FROM decision_head WHERE slot=1)").fetchone()
        if row is None or digest(json.loads(row[0])) != row[1]:
            raise ValueError("MissingDecisionEvidence")
        record = json.loads(row[0])
        for key in ("baseline_sha256", "observation_sha256"):
            found = db.execute("SELECT body FROM episodes WHERE digest=?", (record[key],)).fetchone()
            if found is None:
                raise ValueError("MissingEpisode")
            episode = json.loads(found[0])
            if digest(episode) != record[key] or episode.get("source") != ORIGIN:
                raise ValueError("EpisodeIntegrityFailed")
    return {"source": ORIGIN, "decision_sha256": digest(record),
            "baseline_sha256": record["baseline_sha256"], "observation_sha256": record["observation_sha256"]}


def candidate(ident, score):
    return {"id": ident, "score": {"respect": score, "honesty": score, "balance": score,
        "dignity": score, "compassion": score, "disharmony": 0., "evidence_confidence": 1.,
        "consequences": [{"probability": 1., "harm": 0., "benefit": 0., "cost": 0., "confidence": 1.}]},
        "claims": [], "requires_evidence": [], "requires_tools": [], "violates_goals": [],
        "expected_outcome": {"status": "ready"}}


def witness(context, ident):
    return {"id": ident, "kind": "observed", "source_ref": "fixture://public-memory-feedback-v1",
            "locator": "executed-synthetic-callback/" + ident,
            "source_sha256": sha(Path(__file__).read_bytes()),
            "claim": {"key": "verification_scope", "value": "observed callback return in a synthetic exercise"}}


def request(context, ident, scope="same"):
    return {"id": ident, "context": "public-memory-feedback-v1/" + scope,
        "topic": "cached-readout-vs-source-review", "goal": "Controlled feedback exercise; no real-world error asserted",
        "goals": [], "at_utc": "2026-11-08T00:00:00+00:00", "tools": {},
        "evidence": [{"id": "public-context", "kind": "observed", "source_ref": context["source"],
            "locator": "saved-public-decision/" + context["decision_sha256"],
            "source_sha256": context["observation_sha256"],
            "claim": {"key": "public_snapshot_context", "value": context["observation_sha256"]}},
            {"id": "fixture-label", "kind": "authored", "source_ref": "fixture://public-memory-feedback-v1",
             "locator": ident, "source_sha256": sha(Path(__file__).read_bytes()),
             "claim": {"key": "scenario", "value": "synthetic negative callback, not a Moltbook error"}}],
        "actions": [candidate("use_cached", .8), candidate("recheck_source", .55)]}


def teach(engine, context, prefix, verified=True, positive=False):
    r = request(context, prefix + "-feedback")
    if positive:
        r["actions"] = r["actions"][:1]
    result = {"status": "ready" if positive else "requires_recheck", "synthetic": True}
    return engine.execute(r, lambda action: result, verified=verified,
                          evidence=[witness(context, prefix)],
                          reason="Observed synthetic callback outcome; no real Moltbook mistake inferred")


def run(root, context, Engine):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = root / "result.json"
    if out.exists():
        return load_result(root, context)
    observed = {}
    for name, memory, verified in (("baseline", False, True), ("memory", True, True), ("unverified", True, False)):
        with Engine(root / (name + ".sqlite3"), use_memory=memory) as engine:
            learned = teach(engine, context, name, verified=verified)
            if learned["selected_action"] != "use_cached":
                raise ValueError("InitialSelectionMismatch")
            result = engine.decide(request(context, name + "-probe"))
            observed[name] = result["selected_action"]
            if name == "memory":
                observed["scope_control"] = engine.decide(request(context, "other-scope", "unrelated"))["selected_action"]
    # A separate control ledger verifies that later verified success clears the penalty.
    with Engine(root / "success.sqlite3") as engine:
        teach(engine, context, "success-negative")
        teach(engine, context, "success-positive", positive=True)
        observed["success_control"] = engine.decide(request(context, "success-probe"))["selected_action"]
    checks = {"baseline_repeats": observed["baseline"] == "use_cached",
              "memory_revises": observed["memory"] == "recheck_source",
              "unverified_ignored": observed["unverified"] == "use_cached",
              "scope_isolated": observed["scope_control"] == "use_cached",
              "success_restores": observed["success_control"] == "use_cached"}
    if not all(checks.values()):
        raise ValueError("FeedbackControlFailed")
    data = {"schema": SCHEMA, "context": context, "observed": observed, "checks": checks,
            "synthetic_outcomes": True, "native_body_cycles": 0, "model_api_calls": 0,
            "sources": SOURCES, "scoring": {"use_cached": .8, "recheck_source": .55, "native_failure_penalty": .6}}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(canonical(data), encoding="utf-8")
    os.replace(tmp, out)
    (root / "result.sha256").write_text(digest(data), encoding="ascii")
    return data


def load_result(root, context):
    root = Path(root)
    data = json.loads((root / "result.json").read_text(encoding="utf-8"))
    if digest(data) != (root / "result.sha256").read_text(encoding="ascii"):
        raise ValueError("ResultIntegrityFailed")
    if (data["context"] != context or data.get("schema") != SCHEMA or not all(data["checks"].values())
            or data["sources"] != SOURCES or data["synthetic_outcomes"] is not True):
        raise ValueError("SavedExerciseMismatch")
    return data


def recover(root, context, Engine):
    root = Path(root)
    data = load_result(root, context)
    with Engine(root / "memory.sqlite3") as engine:
        result = engine.decide(request(context, "cold-probe"))
        if result["selected_action"] != "recheck_source" or result["recalled_feedback_ids"] != ["memory-feedback"]:
            raise ValueError("ColdFeedbackMismatch")
        penalized = next(o for o in result["options"] if o["action_id"] == "use_cached")
        if penalized["memory_penalty"] != .6:
            raise ValueError("PenaltyMismatch")
    return data


def summary(data, cold=False):
    return (f"REFLECT={'RECOVERED' if cold else 'TRAINED'};BASE=CACHED;MEM=RECHECK;"
            f"COLD={int(cold)};CTRL={sum(data['checks'].values())}/5;SYNTH=1;"
            f"SIG={digest(data)[:16]};BODY=0;API=0")


def main():
    try:
        local = Path(os.environ["LOCALAPPDATA"])
        Engine = load_engine(local / "NasurayaTadashV1" / ("runtime-" + PACKAGE[:16]))
        memory_root = local / "Nasuraya" / "PublicMemoryV1"
        context = source_context(memory_root)
        root = memory_root / "ReflectionLabV1" / context["decision_sha256"][:16]
        data = run(root, context, Engine) if MODE == "train" else recover(root, context, Engine)
        result = summary(data, cold=MODE == "report")
    except Exception as error:
        result = "REFLECT=FAILED;ERROR=" + type(error).__name__
    print(json.dumps({"status": "ok", "summary": result}, separators=(",", ":")))


if __name__ == "__main__":
    main()
