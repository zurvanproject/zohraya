"""Bounded work and sample runner. One independent research shard per time slot."""
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

INTERVAL = 600
LIMIT = 48
SCHEMA = "tadash-research-20261108/1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def verify(root):
    config = read(root / "config.json")
    if config["schema"] != SCHEMA:
        raise ValueError("config_schema")
    for name, expected in config["hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("source_checksum")
    return config


def expected_slots(cfg):
    return min(LIMIT, max(1, math.ceil((cfg["deadline"] - cfg["started"]) / INTERVAL)))


def invoke_research(root, args):
    # Isolated mode omits the script directory. Only the source-verified private
    # release directory is added for the two upstream sibling modules.
    py = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
          "runpy.run_path(sys.argv.pop(1),run_name='__main__')")
    work = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", py, str(root),
         str(root / "research.py"), *args, "--out", str(root / "results")],
        cwd=root, capture_output=True, timeout=100, check=True)
    return json.loads(work.stdout)


def actual_system():
    result = subprocess.run(["whoami.exe", "/user", "/fo", "csv", "/nh"],
                            capture_output=True, timeout=8, check=True)
    return b"S-1-5-18" in result.stdout


def collect(root):
    spec = importlib.util.spec_from_file_location("nasu_continuity", root / "continuity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sample()


def run(root, mode, *, clock=time.time, system=actual_system, research=invoke_research, sample=collect):
    with closing(sqlite3.connect(root / "guard.sqlite", timeout=110, isolation_level=None)) as guard:
        guard.execute("BEGIN IMMEDIATE")
        return run_locked(root, mode, clock, system, research, sample)


def run_locked(root, mode, clock, system, research, sample):
    cfg = verify(root)
    if not system():
        raise PermissionError("system_scope")
    out = root / "results"
    out.mkdir(exist_ok=True)
    with closing(sqlite3.connect(root / "run.sqlite", timeout=110, isolation_level=None)) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS slots(slot INTEGER PRIMARY KEY, sampled TEXT NOT NULL)")
        now = clock()
        final = root / "final.json"
        if final.exists():
            return
        if mode == "final" and now < cfg["deadline"] - 1:
            raise ValueError("too_early")
        if now >= cfg["deadline"] - 1 or mode == "final":
            state = "FINAL"
        else:
            slot = min(LIMIT - 1, max(0, int((now - cfg["started"]) // INTERVAL)))
            if not db.execute("SELECT 1 FROM slots WHERE slot=?", (slot,)).fetchone():
                research(root, ["--slot", str(slot)])
                health = sample(root)
                db.execute("INSERT INTO slots VALUES(?,?)", (slot, json.dumps(health, allow_nan=False)))
            state = "ACTIVE"
        summary = research(root, ["--summary"])
        rows = [(i,json.loads(v)) for i,v in db.execute("SELECT slot,sampled FROM slots ORDER BY slot")]
        indices = [i for i, _ in rows]
        seen = len(indices)
        health_ok = sum(r.get("ok") is True for _,r in rows)
        expected = expected_slots(cfg)
        coherent = seen == summary["slots"]
        # First commit the samples. Status JSON is replaceable. If a crash occurs
        # between commit and publication the next invocation regenerates summary.
        db.commit()
        report = {"state":state, "system":True, "reference_deadline":cfg["reference_deadline"],
                  "slots":seen, "expected":expected, "health_ok":health_ok,"health_bad":seen-health_ok,
                  "last_slot":indices[-1] if indices else -1, "last_host_epoch":now,
                  "complete":state=="FINAL" and coherent and indices==list(range(expected)),
                  "scientific":summary,
                  "latest_health":rows[-1][1] if rows else None}
        atomic(root / "progress.json", report)
        if state == "FINAL":
            atomic(final, report)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    try:
        mode, = sys.argv[1:]
        if mode not in ("sample", "final"):
            raise ValueError("invalid_mode")
        run(root, mode)
    except Exception as exc:
        # Local file only. No server paths, environment or trace enter the relay.
        atomic(root / "last-error.json", {"at":time.time(),"error":type(exc).__name__})
        raise
