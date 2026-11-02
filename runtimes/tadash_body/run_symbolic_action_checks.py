"""Run native parity checks in a disposable copy; never load saved user state."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def native_worker():
    if os.environ.get("TADASH_SYMBOLIC_SANDBOX") != str(ROOT):
        raise RuntimeError("native checks require the temporary sandbox launcher")
    from synthetic_fixture import prepare_defaults, synthetic_body
    from symbolic_action_v1 import Intention, NativeBodyPort, SymbolicCycle, prepare
    prepare_defaults()
    reports = []
    for purpose in ("settle", "explore"):
        wrapped = synthetic_body()
        direct = synthetic_body()
        port = NativeBodyPort(wrapped)
        intent = Intention("native-" + purpose, purpose, wrapped.revision,
                           "2026-01-01T00:00:08+00:00", duration_s=.1)
        before = port.snapshot()
        original = wrapped.checkpoint()
        plan = prepare(intent, before)
        assert original == wrapped.checkpoint(), "planning advanced native body"
        with SymbolicCycle(str(ROOT / (purpose + ".sqlite")), port) as host:
            receipt = host.run(intent, authorized=True)
            direct_result = direct.cycle(event_id="symbolic:" + intent.event_id,
                at_utc=intent.at_utc, duration_s=intent.duration_s,
                requested=plan["requested_action"], external={},
                expected_revision=intent.expected_revision)
            assert wrapped.checkpoint() == direct.checkpoint(), "sidecar changed native trajectory"
            after = wrapped.checkpoint()
            replay = host.run(intent, authorized=True)
            assert after == wrapped.checkpoint(), "replay advanced body"
            assert replay["native_calls_this_run"] == 0
            assert receipt["actual_action"] == direct_result["owner"]["selected_action"]
            audit = receipt["native_audit"]
            assert audit["energy_error_J"] <= 5e-5
            assert audit["water_error_L"] <= 1e-8
            assert audit["neural_clock_error_s"] <= 1e-7
        with SymbolicCycle(str(ROOT / (purpose + ".sqlite")), port) as reopened:
            replay = reopened.run(intent, authorized=True)
            assert replay["receipt_seal"] == receipt["receipt_seal"]
            assert after == wrapped.checkpoint()
        reports.append({"purpose": purpose, "requested": plan["requested_action"],
            "actual": receipt["actual_action"], "native_veto": receipt["native_veto"],
            "before": before, "after": receipt["after"],
            "native_audit": audit, "native_checkpoint_parity": True,
            "replay_extra_native_calls": 0, "reopen_extra_native_calls": 0})
    print(json.dumps({"schema": "tadash-symbolic-native-check/1",
        "native_comparisons_passed": len(reports),
        "wrapper_native_cycles": len(reports),
        "direct_comparison_cycles": len(reports),
        "fixture": "generated defaults, no saved user state",
        "empirical_validation": False, "canonical_state_modified": False,
        "reports": reports}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--native-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.native_worker:
        native_worker()
        return 0
    if not args.native:
        parser.error("choose --native; unit tests use python -m unittest test_symbolic_action_v1")
    if not (ROOT / "synthetic_fixture.py").is_file():
        parser.error("native runtime unavailable; apply this patch to a complete Zohraya checkout")
    with tempfile.TemporaryDirectory(prefix="tadash-symbolic-") as folder:
        work = Path(folder) / "runtime"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
            "__pycache__", "*.sqlite", "*.sqlite-*", "*.db", "*.db-*"))
        env = dict(os.environ, TADASH_SYMBOLIC_SANDBOX=str(work))
        run = subprocess.run([sys.executable, str(work / Path(__file__).name),
                              "--native-worker"], cwd=work, env=env,
                             capture_output=True, text=True, timeout=180)
        sys.stdout.write(run.stdout)
        sys.stderr.write(run.stderr)
        return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
