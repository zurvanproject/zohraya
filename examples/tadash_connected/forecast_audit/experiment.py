"""Fit on two training corpora; score sealed checkpoints separately on whole unseen runs."""
import argparse
import gzip
import hashlib
import inspect
import json
from pathlib import Path
import platform
import subprocess
import tempfile

import jax
import jax.numpy as jnp
import ninjax as nj
import numpy as np

from ..__main__ import write_json
from ..dream_worker import ACTIONS, FEATURES, RSSM, SCALE, fit_model, forecast_functions, measurement, trajectories

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "evidence"
PROTOCOL = HERE / "protocol.json"
PLAN = json.loads(PROTOCOL.read_text())
PANELS = ("panel_a", "panel_b")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_split(directory, split):
    raw = gzip.decompress((directory / (split + ".jsonl.gz")).read_bytes())
    receipt = json.loads((directory / "collection.json").read_text())[split]
    if hashlib.sha256(raw).hexdigest() != receipt["uncompressed_sha256"]:
        raise ValueError(f"{split}: trace checksum mismatch")
    rows = list(map(json.loads, raw.splitlines()))
    expected = [(case[0], second) for case in PLAN[split]
                for second in range(1, 1 + PLAN["cycles_per_case"])]
    if [(r["case"], r["second"]) for r in rows] != expected:
        raise ValueError(f"{split}: case or time differs from frozen plan")
    previous = {}
    for row in rows:
        before = measurement(row["before_native"], row["before_myo"])
        after = measurement(row["after_native"], row["after_myo"])
        if not np.isfinite([before, after]).all():
            raise ValueError("Non-finite body state")
        if row["case"] in previous:
            np.testing.assert_array_equal(before, previous[row["case"]])
        previous[row["case"]] = after
    return trajectories(rows)


def archived_rows():
    checks = json.loads((ORIGINAL / "SHA256.json").read_text())
    for filename, expected in checks.items():
        if digest(ORIGINAL / filename) != expected:
            raise ValueError("PR100 checksum mismatch: " + filename)
    return list(map(json.loads, (ORIGINAL / "episodes.jsonl").read_text().splitlines()))


def ridge_inputs(current, controls):
    current = np.asarray(current, dtype=np.float64)
    previous_change = np.diff(current, axis=1, prepend=current[:, :1])
    return np.concatenate([current, previous_change, controls], axis=-1)


def fit_ridge(x, a):
    design = ridge_inputs(x[:, :-1], a[:, 1:]).reshape(-1, 2 * len(FEATURES) + len(ACTIONS))
    change = np.diff(np.asarray(x, dtype=np.float64), axis=1).reshape(-1, len(FEATURES))
    center = design.mean(0)
    scale = np.maximum(design.std(0), 1e-6)
    z = (design - center) / scale
    bias = change.mean(0)
    weights = np.linalg.solve(z.T @ z + np.eye(z.shape[1]), z.T @ (change - bias))
    return dict(center=center, scale=scale, bias=bias, weights=weights)


def fit(traces, dest):
    old_rows = [r for r in archived_rows() if r["second"] <= 6]
    old_x, old_a, _ = trajectories(old_rows)
    x, a, _ = load_split(traces, "fit")
    corpora = {"old": (old_x, old_a), "fit": (x, a)}
    np.savez_compressed(dest / "ridge.npz", **fit_ridge(x, a))
    specs = [
        ("absolute_old_256", "old", "absolute", 256, 17),
        ("absolute_fit_64", "fit", "absolute", 64, 17),
        ("absolute_fit_256", "fit", "absolute", 256, 17),
        ("raw_fit_64", "fit", "raw", 64, 17),
        ("delta_fit_64", "fit", "rms", 64, 17),
        ("delta_old_256", "old", "rms", 256, 17),
    ]
    specs.extend((f"candidate_{seed}", "fit", "rms", PLAN["candidate_updates"], seed)
                 for seed in PLAN["candidate_seeds"])
    runs = {}
    for name, corpus, mode, steps, seed in specs:
        cx, ca = corpora[corpus]
        scale = None
        if mode == "raw":
            scale = jnp.ones(len(FEATURES))
        elif mode == "rms":
            scale = jnp.maximum(jnp.sqrt(jnp.mean(jnp.diff(cx, axis=1) ** 2, axis=(0, 1))), 1e-6)
        objective, _, _ = forecast_functions(len(FEATURES), scale)
        weights, before, after = fit_model(objective, cx, ca, steps, init_seed=seed)
        if not np.isfinite([before, after]).all():
            raise ValueError(name + ": non-finite training objective")
        checkpoint = dest / (name + ".npz")
        np.savez_compressed(checkpoint, **weights)
        runs[name] = dict(fit_corpus=corpus, transitions=int(cx.shape[0] * (cx.shape[1] - 1)),
                          init_seed=seed, updates=steps, scale=None if scale is None else scale.tolist(),
                          parameters=sum(v.size for v in weights.values()), checkpoint_sha256=digest(checkpoint),
                          fit_objective_before=before, fit_objective_after=after)
        print("Fitted", name, flush=True)
    write_json(dest / "fits.json", dict(protocol_sha256=digest(PROTOCOL), runs=runs,
                                       fit_trace_sha256=digest(traces / "fit.jsonl.gz"),
                                       ridge_sha256=digest(dest / "ridge.npz"),
                                       jax=jax.__version__, numpy=np.__version__, python=platform.python_version(),
                                       backend=jax.default_backend()))


def parameters(path):
    with np.load(path, allow_pickle=False) as data:
        return {key: jnp.asarray(data[key]) for key in data.files}


def stats(predicted, actual, cases):
    error = np.abs(np.asarray(predicted, dtype=np.float64) - np.asarray(actual, dtype=np.float64))
    if predicted.shape != actual.shape or not np.isfinite(error).all():
        raise ValueError("Invalid forecast tensor")
    return dict(scaled_mae=float(error.mean()),
                native_mae=dict(zip(FEATURES, (error * SCALE).mean(axis=(0, 1)).tolist(), strict=True)),
                case_scaled_mae=dict(zip(cases, error.mean(axis=(1, 2)).tolist(), strict=True)))


def original_predictions(dest, frozen):
    x, a, cases = trajectories(archived_rows())
    _, predict, _ = forecast_functions(len(FEATURES))
    forward = jax.jit(nj.pure(predict))
    expected = json.loads((ORIGINAL / "summary.json").read_text())["dreamer"]
    predictions = []
    for t in (7, 8):
        predictions.append(np.asarray(forward(frozen, x[:, :t], a[:, :t], a[:, t], seed=2000+t)[1]))
    prediction = np.stack(predictions, axis=1)
    metrics = stats(prediction, x[:, 7:], cases)
    np.testing.assert_allclose(metrics["scaled_mae"], expected["held_out_scaled_mae"], atol=1e-7, rtol=0)
    np.testing.assert_allclose(list(metrics["native_mae"].values()),
                               [expected["held_out_mae_native_units"][k] for k in FEATURES], atol=3e-6, rtol=0)
    records = [dict(case=case, second=t, predicted=(prediction[i,j] * SCALE).tolist(),
                    observed=(x[i,t] * SCALE).tolist(), persistence=(x[i,t-1] * SCALE).tolist())
               for i, case in enumerate(cases) for j, t in enumerate((7, 8))]
    write_json(dest / "archived_predictions.json", dict(features=FEATURES, native_units=True, rows=records,
                                                       published_metrics=expected))


def gate(panel, name):
    rule = PLAN["gate"]
    candidate = panel[name]
    misses = []
    for baseline, target in (("persistence", rule["maximum_fraction_of_persistence_and_frozen_mae"]),
                             ("frozen", rule["maximum_fraction_of_persistence_and_frozen_mae"]),
                             ("ridge", rule["maximum_fraction_of_ridge_mae"])):
        if candidate["scaled_mae"] > panel[baseline]["scaled_mae"] * target:
            misses.append("scaled_mae:" + baseline)
    for key, ref in panel["persistence"]["native_mae"].items():
        limit = ref * rule["maximum_per_channel_fraction_of_persistence"] if ref else rule["zero_baseline_absolute_tolerance_native_units"]
        if candidate["native_mae"][key] > limit:
            misses.append("channel:" + key)
    return misses


def score(traces, fits, dest):
    fitted = json.loads((fits / "fits.json").read_text())
    if (fitted["protocol_sha256"] != digest(PROTOCOL)
            or fitted["fit_trace_sha256"] != digest(traces / "fit.jsonl.gz")
            or fitted["ridge_sha256"] != digest(fits / "ridge.npz")):
        raise ValueError("Training inputs or protocol changed")
    frozen = parameters(ORIGINAL / "rssm_parameters.npz")
    original_predictions(dest, frozen)
    with np.load(fits / "ridge.npz", allow_pickle=False) as data:
        ridge = dict(data)
    networks = {"frozen": (frozen, None)}
    for name, run in fitted["runs"].items():
        path = fits / (name + ".npz")
        if digest(path) != run["checkpoint_sha256"]:
            raise ValueError("Checkpoint hash mismatch: " + name)
        scale = run["scale"]
        networks[name] = (parameters(path), None if scale is None else jnp.array(scale))
    compiled = {}
    scores, tests, records = {}, {}, []
    # Confirm split separation using actual measurements rather than case labels alone.
    signatures = set()
    old_x, old_a, _ = trajectories(archived_rows())
    fit_x, fit_a, _ = load_split(traces, "fit")

    def transition_keys(x, a):
        pairs = np.concatenate([x[:, :-1], a[:, 1:], x[:, 1:]], axis=-1)
        return {tuple(v) for v in pairs.reshape(-1, pairs.shape[-1])}

    signatures.update(transition_keys(old_x, old_a))
    signatures.update(transition_keys(fit_x, fit_a))
    for split in PANELS:
        x, a, cases = load_split(traces, split)
        keys = transition_keys(x, a)
        if keys & signatures:
            raise ValueError(split + ": duplicate measured transition across splits")
        signatures.update(keys)
        current, actual, controls = np.asarray(x[:, :-1]), np.asarray(x[:, 1:]), np.asarray(a[:, 1:])
        z = (ridge_inputs(current, controls) - ridge["center"]) / ridge["scale"]
        forecasts = {"persistence": current, "ridge": current + z @ ridge["weights"] + ridge["bias"]}
        for name, (weights, scale) in networks.items():
            key = None if scale is None else tuple(scale.tolist())
            if key not in compiled:
                _, _, evaluate = forecast_functions(len(FEATURES), scale)
                compiled[key] = jax.jit(nj.pure(evaluate))
            forecasts[name] = np.asarray(compiled[key](weights, x[:, :-1], a[:, :-1], a[:, 1:],
                                                       seed=PLAN["inference_seed"])[1])
        scores[split] = {name: stats(pred, actual, cases) for name, pred in forecasts.items()}
        tests[split] = {str(seed): gate(scores[split], f"candidate_{seed}") for seed in PLAN["candidate_seeds"]}
        for i, case in enumerate(cases):
            for t in range(actual.shape[1]):
                records.append(dict(case=case, second=t+1, panel=split, action=ACTIONS[controls[i,t].argmax()],
                                    measured_native=(actual[i,t] * SCALE).tolist(),
                                    predicted_native={k: (p[i,t] * SCALE).tolist() for k,p in forecasts.items()}))
    encoded = "".join(json.dumps(r, separators=(",", ":"), allow_nan=False) + "\n" for r in records).encode()
    (dest / "predictions.jsonl.gz").write_bytes(gzip.compress(encoded, mtime=0))
    write_json(dest / "scores.json", dict(features=FEATURES, unit_scales=SCALE.tolist(), panels=scores,
               gate_failures=tests, metric_gate_pass=all(not issues for panel in tests.values() for issues in panel.values()),
               policy_connected=False, protocol_sha256=digest(PROTOCOL)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["fit", "score"])
    parser.add_argument("traces", type=Path)
    parser.add_argument("output", type=Path, help="a new directory")
    parser.add_argument("--fits", type=Path, help="sealed fit directory for scoring")
    args = parser.parse_args()
    if (args.stage == "score") != bool(args.fits):
        parser.error("provide --fits only for score")
    upstream = Path(inspect.getfile(RSSM)).resolve().parents[1]
    def git(*args):
        return subprocess.check_output(["git", "-C", upstream, *args], text=True).strip()
    if git("rev-parse", "HEAD") != PLAN["dreamer_commit"] or git("status", "--porcelain", "--", "dreamerv3", "embodied"):
        parser.error("use the clean, pinned Dreamer checkout")
    if tuple(PLAN["features"]) != FEATURES or not np.array_equal(PLAN["unit_scales"], SCALE):
        parser.error("feature definitions differ from the frozen protocol")
    if args.output.exists():
        parser.error("output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temp:
        out = Path(temp) / "result"
        out.mkdir()
        if args.stage == "fit":
            fit(args.traces, out)
        else:
            score(args.traces, args.fits, out)
        out.rename(args.output)


if __name__ == "__main__":
    main()
