"""Run a complete, headless demonstration with an isolated synthetic Tadash body."""
import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from examples.nasuraya_body_loop.__main__ import SOURCE, verified_sources
from . import CASES

HERE = Path(__file__).resolve().parent
DREAMER_REV = "e01491fad6434b2245a3b8ca201dd7faedcc458c"
GMR_REV = "25f56db79ac411258b377b6d4ccba0c8ff3372ac"
EXTRA_MODULES = ("neuropelvic.py", "neuropelvic_body.py", "interoceptive_trends.py",
                 "river_page_hinkley.py", "river_page_hinkley_support.py")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def copy_runtime(path):
    manifest = verified_sources()
    for name in (*manifest, *EXTRA_MODULES):
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, target)


def summary(rows):
    cases = {}
    for case, _, _ in CASES:
        sample = [r for r in rows if r["case"] == case]
        first, last = sample[0], sample[-1]
        cases[case] = {"requested": [r["decision"]["requested"] for r in sample],
                       "executed": [r["selected_action"] for r in sample],
                       "initial_ready_belief": first["decision"]["ready_posterior"],
                       "initial_myo_fatigue": first["before_myo"]["mean_fatigue"],
                       "final_myo_fatigue": last["after_myo"]["mean_fatigue"]}
    return {"cases": cases, "cycles": len(rows), "native_ticks": sum(r["native_ticks"] for r in rows),
            "myo_control_steps": sum(r["after_myo"]["control_steps"] for r in rows),
            "atlas_mass_kg": rows[0]["atlas_mass_kg"],
            "max_compartment_error": max(r["after_myo"]["max_compartment_error"] for r in rows),
            "max_hand_target_error_m": max(r["motion"]["hand_target_error_m"] for r in rows),
            "max_native_energy_error_J": max(abs(r["native_audit"]["energy_error_J"]) for r in rows),
            "max_native_water_error_L": max(abs(r["native_audit"]["water_error_L"]) for r in rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tadash connected-demo")
    parser.add_argument("--steps", type=int, default=8, help="simulated seconds per case (4 to 120)")
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory for a complete run")
    parser.add_argument("--dream-python", type=Path, required=True, help="interpreter with Dreamer dependencies")
    parser.add_argument("--dream-source", type=Path, required=True, help="checkout of the pinned Dreamer source")
    args = parser.parse_args(argv)
    if not 4 <= args.steps <= 120:
        parser.error("--steps must be between 4 and 120")
    # Preserve the virtualenv's interpreter path (resolve() would follow the python symlink).
    python = args.dream_python.absolute()
    upstream = args.dream_source.resolve()
    dest = args.output_dir.absolute()
    if dest.exists() or dest.is_symlink():
        parser.error("output directory already exists")
    revision = subprocess.check_output(["git", "-C", upstream, "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", upstream, "status", "--porcelain", "--",
                                     "dreamerv3", "embodied"], text=True)
    if revision != DREAMER_REV or dirty:
        parser.error("use a clean Dreamer checkout at " + DREAMER_REV)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The graph and the model are exposed together, only after validation succeeds.
    with tempfile.TemporaryDirectory(prefix=".tadash-connected-", dir=dest.parent) as tmp:
        root = Path(tmp)
        native, data = root / "native", root / "results"
        data.mkdir()
        copy_runtime(native)
        env = dict(os.environ, JAX_PLATFORMS="cpu", TERM="xterm",
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        env.pop("OPENAI_API_KEY", None)
        measured = root / "measured.json"
        subprocess.run([sys.executable, "-m", "examples.tadash_connected.runtime",
                        native, measured, str(args.steps)], env=env, cwd=HERE.parents[1], check=True)
        rows = json.loads(measured.read_text())
        from .graph import store_and_recall
        recovered, graph = asyncio.run(store_and_recall(data, rows))
        write_json(data / "episodes.json", recovered)
        env["PYTHONPATH"] = str(upstream)
        subprocess.run([python, HERE / "dream_worker.py", data / "episodes.json", data],
                       cwd=root, check=True, env=env)
        result = {"schema": "tadash-connected-demo/1", "steps_per_case": args.steps,
                  "packages": {p: version(p) for p in ("inferactively-pymdp", "MyoSuite", "mujoco",
                                                        "mink", "graphiti-core", "kuzu", "jax")},
                  "dreamerv3_revision": revision, "gmr_revision": GMR_REV,
                  "native": summary(rows), "graphiti": graph,
                  "dreamer": json.loads((data / "dream_result.json").read_text())}
        write_json(data / "summary.json", result)
        digests = {}
        for item in sorted(data.iterdir()):
            if item.is_file():
                with item.open("rb") as stream:
                    digests[item.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        write_json(data / "SHA256.json", digests)
        os.rename(data, dest)
    print(dest / "summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
