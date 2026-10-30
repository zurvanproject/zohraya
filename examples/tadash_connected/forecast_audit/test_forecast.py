import unittest

import jax
import jax.numpy as jnp
import ninjax as nj
import numpy as np

from ..dream_worker import FEATURES, fit_model, forecast_functions, trajectories
from .experiment import archived_rows, gate, ridge_inputs


class ForecastAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [r for r in archived_rows() if r["case"] == "masked" and r["second"] <= 5]
        cls.x, cls.a, _ = trajectories(rows)
        objective, _, roll = forecast_functions(len(FEATURES), jnp.ones(len(FEATURES)))
        cls.initial = nj.init(objective)({}, cls.x, cls.a, seed=17)
        cls.weights, _, _ = fit_model(objective, cls.x, cls.a, 4)
        cls.forward = staticmethod(jax.jit(nj.pure(roll)))

    def predict(self, params, x, a):
        return np.asarray(self.forward(params, x[:, :-1], a[:, :-1], a[:, 1:], seed=2001)[1])

    def test_zero_initialized_delta_head_is_exactly_persistence(self):
        np.testing.assert_array_equal(self.predict(self.initial, self.x, self.a), self.x[:, :-1])

    def test_target_and_future_changes_leave_earlier_forecasts_unchanged(self):
        reference = self.predict(self.weights, self.x, self.a)
        # Perturb state 3 (the target of forecast index 2) and all subsequent states.
        later = self.x.at[:, 3:].add(10.)
        later_actions = self.a.at[:, 4:].set(self.a[:, 1:2])
        changed = self.predict(self.weights, later, later_actions)
        np.testing.assert_array_equal(reference[:, :3], changed[:, :3])
        self.assertFalse(np.array_equal(reference[:, 3:], changed[:, 3:]))
        # At the same observation, changing the upcoming action can affect its forecast.
        different_action = self.a.at[:, 3].set(self.a[:, 1])
        self.assertFalse(np.array_equal(reference[:, 2],
                                        self.predict(self.weights, self.x, different_action)[:, 2]))
        np.testing.assert_array_equal(ridge_inputs(self.x[:, :-1], self.a[:, 1:])[:, :3],
                                      ridge_inputs(later[:, :-1], later_actions[:, 1:])[:, :3])

    def test_gate_rejects_single_channel_regression_or_missed_baseline(self):
        base = dict(scaled_mae=1., native_mae=dict.fromkeys(FEATURES, 1.))
        base["native_mae"]["myo_elbow_rad"] = 0.
        model = dict(scaled_mae=.80, native_mae=dict.fromkeys(FEATURES, .9))
        model["native_mae"]["myo_elbow_rad"] = 0.
        panel = dict(candidate=model, frozen=base, persistence=base, ridge=base)
        self.assertEqual(gate(panel, "candidate"), [])
        model["native_mae"]["myo_elbow_rad"] = 1e-5
        panel["ridge"] = dict(scaled_mae=.75)
        self.assertEqual(gate(panel, "candidate"), ["scaled_mae:ridge", "channel:myo_elbow_rad"])


if __name__ == "__main__":
    unittest.main()
