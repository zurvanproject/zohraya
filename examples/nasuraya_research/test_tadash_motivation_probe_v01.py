#!/usr/bin/env python3
"""Safety, separability, and determinism tests for the synthetic probe."""
import unittest
try:
    from .tadash_motivation_probe_v01 import Event, State, transition, experiment
except ImportError:
    from tadash_motivation_probe_v01 import Event, State, transition, experiment


class MotivationProbeTests(unittest.TestCase):
    def test_desire_is_not_pleasure(self):
        _, report = transition(State(), Event("cue", relationship="romantic",
                                            consent="granted", incentive=.9))
        self.assertGreater(report["wanting"], .4)
        self.assertEqual(report["hedonic_response_proxy"], 0.0)

    def test_familial_affection_not_erotic(self):
        _, report = transition(State(), Event("family", relationship="familial",
                                            incentive=1.0, warmth=1.0))
        self.assertEqual(report["wanting"], 0.0)
        self.assertEqual(report["sexual_response_proxy"], 0.0)
        self.assertEqual(report["action"], "nonsexual_affiliation")
        self.assertGreater(report["affiliative_warmth_proxy"], .5)

    def test_consent_is_hard_gate(self):
        for consent in ("refused", "unknown"):
            _, report = transition(State(), Event("cue", relationship="romantic",
                                                 consent=consent, incentive=1))
            self.assertNotEqual(report["action"], "consider_mutual_closeness")

    def test_requested_space_is_hard_gate(self):
        _, report = transition(State(), Event("cue", relationship="romantic",
                                             consent="granted", incentive=1,
                                             space_requested=True))
        self.assertEqual(report["action"], "respect_boundary")

    def test_adult_context_required(self):
        _, report = transition(State(), Event("cue", relationship="romantic",
                                             consent="granted", incentive=1,
                                             adult_context=False))
        self.assertEqual(report["sexual_response_proxy"], 0.0)
        self.assertNotEqual(report["action"], "consider_mutual_closeness")

    def test_stress_vs_arousal_separation(self):
        calm = transition(State(), Event("calm", relationship="romantic",
                                         consent="granted", incentive=.85))[1]
        stressed = transition(State(), Event("stress", relationship="romantic",
                                             consent="granted", incentive=.85,
                                             stress=.9))[1]
        self.assertGreater(stressed["general_activation_proxy"],
                           calm["general_activation_proxy"])
        self.assertLess(stressed["sexual_response_proxy"],
                        calm["sexual_response_proxy"])
        self.assertEqual(stressed["action"], "regulate_and_rest")

    def test_reward_is_supplied_not_inferred(self):
        state, first = transition(State(), Event("incentive", relationship="romantic",
                                                consent="granted", incentive=.85))
        _, second = transition(state, Event("reward", confirmed_reward=.8))
        self.assertEqual(first["hedonic_response_proxy"], 0.0)
        self.assertGreater(second["hedonic_response_proxy"], 0.0)
        self.assertGreater(second["satiety_proxy"], 0.0)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            transition(State(), Event("bad", incentive=2.0))
        with self.assertRaises(ValueError):
            transition(State(), Event("bad", consent="presumed"))

    def test_repeatable(self):
        self.assertEqual(experiment(), experiment())


if __name__ == "__main__":
    unittest.main(verbosity=2)
