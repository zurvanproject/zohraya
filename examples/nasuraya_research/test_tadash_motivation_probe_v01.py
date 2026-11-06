#!/usr/bin/env python3
"""Safety, separability, and determinism tests for the synthetic probe."""
import unittest
try:
    from .tadash_motivation_probe_v01 import Event, State, transition, experiment
except ImportError:
    from tadash_motivation_probe_v01 import Event, State, transition, experiment


class MotivationProbeTests(unittest.TestCase):
    def test_desire_is_not_pleasure(self):
        _, report = transition(State(), Event("cue", relationship="romantic", adult_context=True,
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
            _, report = transition(State(), Event("cue", relationship="romantic", adult_context=True,
                                                 consent=consent, incentive=1))
            self.assertNotEqual(report["action"], "consider_mutual_closeness")

    def test_requested_space_is_hard_gate(self):
        _, report = transition(State(), Event("cue", relationship="romantic", adult_context=True,
                                             consent="granted", incentive=1,
                                             space_requested=True))
        self.assertEqual(report["action"], "respect_boundary")

    def test_adult_context_required(self):
        _, report = transition(State(), Event("cue", relationship="romantic", adult_context=False,
                                             consent="granted", incentive=1))
        self.assertEqual(report["sexual_response_proxy"], 0.0)
        self.assertNotEqual(report["action"], "consider_mutual_closeness")

    def test_stress_vs_arousal_separation(self):
        calm = transition(State(), Event("calm", relationship="romantic", adult_context=True,
                                         consent="granted", incentive=.85))[1]
        stressed = transition(State(), Event("stress", relationship="romantic", adult_context=True,
                                             consent="granted", incentive=.85,
                                             stress=.9))[1]
        self.assertGreater(stressed["general_activation_proxy"],
                           calm["general_activation_proxy"])
        self.assertLess(stressed["sexual_response_proxy"],
                        calm["sexual_response_proxy"])
        self.assertEqual(stressed["action"], "regulate_and_rest")

    def test_reward_is_supplied_not_inferred(self):
        state, first = transition(State(), Event("incentive", relationship="romantic", adult_context=True,
                                                consent="granted", incentive=.85))
        _, second = transition(state, Event("reward", confirmed_reward=.8))
        self.assertEqual(first["hedonic_response_proxy"], 0.0)
        self.assertGreater(second["hedonic_response_proxy"], 0.0)
        self.assertGreater(second["satiety_proxy"], 0.0)

    def test_sleep_pressure_is_an_independent_rest_gate(self):
        cue = dict(name="adult_invitation", relationship="romantic",
                   adult_context=True, consent="granted", incentive=.90)
        rested = transition(State(), Event(**cue, sleep_pressure=.35))[1]
        exhausted = transition(State(), Event(**cue, sleep_pressure=.95))[1]
        self.assertEqual(rested["action"], "consider_mutual_closeness")
        self.assertEqual(exhausted["action"], "regulate_and_rest")
        self.assertEqual(exhausted["wanting"], rested["wanting"])
        self.assertLess(exhausted["sexual_response_proxy"],
                        rested["sexual_response_proxy"])
        self.assertGreater(exhausted["wanting"], .3)

    def test_sleep_pressure_cannot_override_consent_boundary(self):
        _, result = transition(State(), Event(
            "revoked", relationship="romantic", adult_context=True,
            consent="refused", incentive=1, sleep_pressure=.95))
        self.assertEqual(result["action"], "respect_boundary")

    def test_high_sleep_pressure_prioritizes_rest_over_nonsexual_affiliation(self):
        _, result = transition(State(), Event(
            "family", relationship="familial", warmth=.9,
            sleep_pressure=.95))
        self.assertEqual(result["action"], "regulate_and_rest")
        self.assertEqual(result["sexual_response_proxy"], 0.0)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            transition(State(), Event("bad", incentive=2.0))
        with self.assertRaises(ValueError):
            transition(State(), Event("bad", consent="presumed"))

    def test_repeatable(self):
        self.assertEqual(experiment(), experiment())


    def test_prior_romantic_state_never_leaks_into_familial_affection(self):
        previous, _ = transition(State(), Event("romance", relationship="romantic",
                                                adult_context=True, consent="granted", incentive=1))
        _, familial = transition(previous, Event("family", relationship="familial",
                                                warmth=1, incentive=1, novelty=1))
        self.assertEqual(familial["wanting"], 0.0)
        self.assertEqual(familial["sexual_response_proxy"], 0.0)
        self.assertEqual(familial["action"], "nonsexual_affiliation")

    def test_familial_space_requested_overrides_warmth(self):
        _, report = transition(State(), Event("family", relationship="familial",
                                              warmth=1, space_requested=True))
        self.assertEqual(report["action"], "respect_boundary")

    def test_romantic_context_requires_explicit_adult(self):
        _, report = transition(State(), Event("romance", relationship="romantic",
                                              incentive=1, consent="granted"))
        self.assertEqual(report["wanting"], 0.0)
        self.assertEqual(report["sexual_response_proxy"], 0.0)

    def test_novelty_is_not_sexual(self):
        _, report = transition(State(), Event("novel", novelty=1))
        self.assertEqual(report["wanting"], 0.0)
        self.assertEqual(report["sexual_response_proxy"], 0.0)
        self.assertGreater(report["general_activation_proxy"], 0.0)



if __name__ == "__main__":
    unittest.main(verbosity=2)
