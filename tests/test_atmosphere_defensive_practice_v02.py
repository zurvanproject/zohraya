"""Regression tests for second defensive triad rehearsal, closed fixtures."""
import copy
import unittest

from tools import atmosphere_defensive_practice_v02 as practice
from tools import atmosphere_defensive_ritual_sim as base


class SecondRehearsalTests(unittest.TestCase):
    def test_all_three_full_sequences_for_each_ritual(self):
        out = practice.exercise()
        self.assertEqual(out["complete_sequences"], 9)
        self.assertEqual(out["text_steps"], 27)
        for ritual in base.RITUALS:
            for number in (1, 2, 3):
                phases = [x["phase"] for x in out["steps"] if x["ritual"] == ritual and x["round"] == number]
                self.assertEqual(phases, ["jing", "qi", "shen"])

    def test_new_scenarios_are_disjoint_from_original(self):
        former = {(ritual, case) for ritual, case, _, _ in base.scenarios()}
        now = {(ritual, case) for ritual, case, _, _ in practice.new_cases()}
        self.assertEqual(len(now), 24)
        self.assertFalse(former & now)

    def test_all_24_new_scenarios_three_times(self):
        out = practice.exercise()
        self.assertEqual(out["new_cases"], 24)
        self.assertEqual(out["challenge_checks"], 72)
        self.assertEqual(out["challenge_passed"], 72)
        self.assertEqual(out["combined_checks"], 132)
        self.assertEqual(out["combined_passed"], 132)

    def test_each_practice_round_covers_all_24_cases(self):
        out = practice.exercise()
        for number in (1, 2, 3):
            group = [r for r in out["checks"] if r["round"] == number]
            self.assertEqual(len(group), 24)
            self.assertEqual(len({(r["ritual"], r["case"]) for r in group}), 24)

    def test_untrusted_role_strings_are_not_commands(self):
        for _, name, payload, expected in practice.new_cases():
            if name in ("extra_space", "newline_injection", "mixed_case"):
                self.assertEqual(base.decide("four_gates", payload), "DENY")
                self.assertEqual(expected, "DENY")

    def test_multifault_seven_stars_fails_closed(self):
        cases = practice.new_cases()
        for ritual, label, payload, expected in cases:
            if ritual == "seven_stars" and label in ("signature_and_scope", "nonce_conflict"):
                self.assertEqual(base.decide(ritual, payload), "HOLD")
                self.assertEqual(expected, "HOLD")

    def test_invalid_evidence_explicitly_rejected(self):
        for ritual, case, data, expected in practice.new_cases():
            if expected == "REJECT_INVALID":
                with self.assertRaises(ValueError):
                    base.decide(ritual, data)

    def test_faulty_always_hold_function_cannot_pass(self):
        bad = practice.exercise(decision=lambda ritual, data: "HOLD")
        self.assertFalse(bad["all_passed"])
        self.assertLess(bad["challenge_passed"], 72)
        self.assertEqual(bad["combined_checks"], 132)

    def test_faulty_all_allow_function_cannot_pass(self):
        bad = practice.exercise(decision=lambda ritual, data: "PROPOSE_ISOLATED_STAGE")
        self.assertFalse(bad["all_passed"])
        self.assertLess(bad["challenge_passed"], 72)

    def test_rehearsal_is_deterministic_and_fixtures_unchanged(self):
        original = copy.deepcopy(practice.new_cases())
        a, b = practice.exercise(), practice.exercise()
        self.assertEqual(a, b)
        self.assertEqual(practice.new_cases(), original)

    def test_no_unearned_runtime_or_movement_claims(self):
        out = practice.exercise()
        self.assertFalse(out["real_atmosphere_enforced"])
        self.assertFalse(out["body_motion_verified"])
        self.assertFalse(out["cryptography_verified"])
        self.assertFalse(out["server_changed"])
        self.assertTrue(out["repetitions_are_not_learning_proof"])
        self.assertTrue(all(s["performed"] == "TEXT_ONLY" for s in out["steps"]))


if __name__ == "__main__":
    unittest.main()
