"""Train an upstream DreamerV3 RSSM on the Graphiti-recovered body trajectories."""
import argparse
import json
from pathlib import Path

import elements
import embodied.jax.nets as nn
import jax
import jax.numpy as jnp
import ninjax as nj
import numpy as np
import optax
from dreamerv3.rssm import RSSM

FEATURES = ("HR_bpm", "RR_per_min", "mean_muscle_fatigue", "myo_elbow_rad")
SCALE = np.array([100., 30., 1., 3.], dtype=np.float32)
ACTIONS = ("walk", "rest", "observe", "other_native_action")


def measurement(native, myo):
    return np.array([native["HR"], native["RR"], myo["mean_fatigue"], myo["elbow_rad"]]) / SCALE


def trajectories(rows):
    observations, actions = {}, {}
    for row in rows:
        case = row["case"]
        if case not in observations:
            observations[case] = [measurement(row["before_native"], row["before_myo"])]
            actions[case] = [np.zeros(len(ACTIONS), np.float32)]
        if row["second"] != len(actions[case]):
            raise ValueError("Episode order differs from simulation time")
        name = row["selected_action"]
        index = ACTIONS.index(name) if name in ACTIONS else len(ACTIONS) - 1
        actions[case].append(np.eye(len(ACTIONS), dtype=np.float32)[index])
        observations[case].append(measurement(row["after_native"], row["after_myo"]))
    return (jnp.asarray(list(observations.values()), dtype=jnp.float32),
            jnp.asarray(list(actions.values())), list(actions))


def train(rows, destination, updates=64):
    nn.COMPUTE_DTYPE = jnp.float32
    xs, actions, cases = trajectories(rows)
    batch, steps, size = xs.shape
    if steps < 4:
        raise ValueError("At least three executed cycles per case are required")
    holdout = max(1, (steps - 1) // 4)
    split = steps - holdout
    model = RSSM({"control": elements.Space(np.float32, (len(ACTIONS),))},
                 deter=32, hidden=32, stoch=4, classes=4, blocks=4, free_nats=0., name="body_rssm")
    readout = nn.Linear(size, name="body_readout")

    def reset_flags(x):
        return jnp.zeros(x.shape[:2], dtype=bool).at[:, 0].set(True)

    def decode(feat):
        deter, stoch = feat["deter"], feat["stoch"]
        return readout(jnp.concatenate([deter, stoch.reshape((*deter.shape[:-1], -1))], -1))

    def objective(x, a):
        _, entries, losses, feat, _ = model.loss(
            model.initial(len(x)), x, {"control": a}, reset_flags(x), training=True)
        n = x.shape[0] * (x.shape[1] - 1)
        starts = {k: v[:, :-1].reshape((n, *v.shape[2:])) for k, v in entries.items()}
        _, (imagined, _) = model.imagine(
            starts, {"control": a[:, 1:].reshape(n, -1)}, 1, training=True, single=True)
        forecast = jnp.square(decode(imagined) - x[:, 1:].reshape(n, -1)).mean()
        reconstruct = jnp.square(decode(feat) - x).mean()
        return forecast + .2 * reconstruct + .1 * (losses["dyn"].mean() + losses["rep"].mean())

    x_fit, a_fit = xs[:, :split], actions[:, :split]
    params = nj.init(objective)({}, x_fit, a_fit, seed=17)
    pure_loss = nj.pure(objective)
    def measure(p, key):
        return pure_loss(p, x_fit, a_fit, seed=key)[1]

    optimizer = optax.adam(.003)
    @jax.jit
    def step(p, state, key):
        _, gradients = jax.value_and_grad(measure)(p, key)
        delta, state = optimizer.update(gradients, state, p)
        return optax.apply_updates(p, delta), state

    diagnostic_loss = jax.jit(measure)
    initial = float(diagnostic_loss(params, jax.random.PRNGKey(99)))
    opt_state = optimizer.init(params)
    for idx in range(updates):
        params, opt_state = step(params, opt_state, jax.random.PRNGKey(1000 + idx))
    final = float(diagnostic_loss(params, jax.random.PRNGKey(99)))

    def forecast(x, a, next_action):
        carry, _, _ = model.observe(model.initial(len(x)), x, {"control": a}, reset_flags(x), False)
        _, (feat, _) = model.imagine(carry, {"control": next_action}, 1, False, single=True)
        return decode(feat)

    pure_forecast = jax.jit(nj.pure(forecast))
    np.savez_compressed(destination / "rssm_parameters.npz", **params)
    with np.load(destination / "rssm_parameters.npz", allow_pickle=False) as data:
        restored = {key: jnp.asarray(data[key]) for key in data.files}
    predictions, actual, persistence = [], [], []
    for t in range(split, steps):
        args = (xs[:, :t], actions[:, :t], actions[:, t])
        predicted = np.asarray(pure_forecast(restored, *args, seed=2000 + t)[1])
        np.testing.assert_array_equal(predicted, pure_forecast(params, *args, seed=2000 + t)[1])
        predictions.append(predicted)
        actual.append(np.asarray(xs[:, t]))
        persistence.append(np.asarray(xs[:, t-1]))
    error = np.abs(np.stack(predictions) - actual)
    baseline = np.abs(np.stack(persistence) - actual)
    if not np.isfinite([initial, final, error.max(), baseline.max()]).all():
        raise ValueError("Non-finite RSSM evidence")
    metrics = {"implementation": "dreamerv3.rssm.RSSM", "backend": jax.default_backend(),
               "cases": cases, "features": list(FEATURES), "updates": updates,
               "train_transitions": batch * (split-1), "held_out_transitions": batch * holdout,
               "parameters": sum(int(v.size) for v in params.values()), "checkpoint_reload_verified": True,
               "fit_objective_before": initial, "fit_objective_after": final,
               "held_out_scaled_mae": float(error.mean()), "persistence_scaled_mae": float(baseline.mean()),
               "held_out_mae_native_units": dict(zip(FEATURES, (error * SCALE).mean(axis=(0, 1)).tolist())),
               "persistence_mae_native_units": dict(zip(FEATURES, (baseline * SCALE).mean(axis=(0, 1)).tolist()))}
    (destination / "dream_result.json").write_text(json.dumps(metrics, indent=2, allow_nan=False) + "\n")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes", type=Path)
    parser.add_argument("destination", type=Path)
    opts = parser.parse_args()
    train(json.loads(opts.episodes.read_text()), opts.destination)
