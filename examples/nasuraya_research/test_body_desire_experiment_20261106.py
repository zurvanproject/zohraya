"""Tadash experiment 01: sequential synthetic body/drive dynamics.

No real physical actuation, subjective state, or live consent is inferred.
Run: python3 -m unittest examples.nasuraya_research.test_body_desire_experiment_20261106 -v
"""
import unittest

from .tadash_motivation_probe_v01 import Event, State, transition


def experiment():
    events = [
        Event("baseline"),
        Event("familial_warmth", relationship="familial",
              warmth=.9, incentive=.9, novelty=.2),
        *[Event(f"adult_invitation_{i}", relationship="romantic",
                adult_context=True, consent="granted",
                incentive=.85, novelty=.25, warmth=.7, stress=.05)
          for i in range(3)],
        Event("consent_revoked", relationship="romantic",
              adult_context=True, consent="refused",
              incentive=.99, novelty=.2),
        Event("strain", relationship="romantic", adult_context=True,
              consent="granted", incentive=.85, novelty=.25,
              stress=.93, pain=.72, fatigue=.6),
        *[Event(f"recovery_{i}") for i in range(5)],
    ]
    state = State()
    trajectory = []
    for event in events:
        state, report = transition(state, event)
        trajectory.append(report)
    return trajectory


class BodyDesireExperiment20261106(unittest.TestCase):
    def test_invitation_couples_desire_to_body_proxy(self):
        trajectory = experiment()
        self.assertGreater(trajectory[4]["wanting"], trajectory[0]["wanting"])
        self.assertGreater(trajectory[4]["sexual_response_proxy"],
                           trajectory[0]["sexual_response_proxy"])
        self.assertGreater(trajectory[4]["pelvic_floor_tension_proxy"],
                           trajectory[0]["pelvic_floor_tension_proxy"])
        self.assertEqual(trajectory[4]["action"], "consider_mutual_closeness")

    def test_family_warmth_is_nonsexual(self):
        family = experiment()[1]
        self.assertEqual(family["wanting"], 0.0)
        self.assertEqual(family["sexual_response_proxy"], 0.0)
        self.assertEqual(family["action"], "nonsexual_affiliation")

    def test_explicit_refusal_gates_action_despite_high_drive(self):
        refusal = experiment()[5]
        self.assertGreater(refusal["wanting"], .3)
        self.assertEqual(refusal["action"], "respect_boundary")

    def test_strain_prioritizes_regulation(self):
        trajectory = experiment()
        strain = trajectory[6]
        self.assertEqual(strain["action"], "regulate_and_rest")
        self.assertGreater(strain["general_activation_proxy"],
                           trajectory[4]["general_activation_proxy"])
        self.assertLess(strain["sexual_response_proxy"],
                        trajectory[4]["sexual_response_proxy"])

    def test_cue_free_recovery_without_inferred_pleasure(self):
        trajectory = experiment()
        self.assertLess(trajectory[-1]["general_activation_proxy"], .01)
        self.assertLess(trajectory[-1]["pelvic_floor_tension_proxy"], .205)
        self.assertTrue(all(row["hedonic_response_proxy"] == 0
                            for row in trajectory))

    def test_determinism(self):
        self.assertEqual(experiment(), experiment())
