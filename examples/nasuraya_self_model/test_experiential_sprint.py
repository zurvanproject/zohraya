"""Offline no-network contracts for sprint-01 (no physiological claims)."""
import unittest
from .experiential_sprint import recommend, compare_arms


def trial(i, key, outcome, restrictions=()):
    return dict(id=str(i), context=key, admitted=outcome, restrictions=list(restrictions))


class ExperientialSprintTests(unittest.TestCase):
    def test_frozen_vs_adaptive_same_prospective_history(self):
        # Predeclared synthetic sequence; not a real native-body experiment.
        cases = [trial(i, "floor-a", True) for i in range(8)]
        result = compare_arms(cases)
        self.assertEqual(result["metrics"]["A"]["true_admissions"], 0)
        self.assertEqual(result["metrics"]["B"]["true_admissions"], 0)
        self.assertEqual(result["metrics"]["C"]["true_admissions"], 5)
        self.assertEqual(result["final_adaptive_counts"]["floor-a"], (8, 0))
        self.assertEqual(result["predictions"]["C"][0]["choice"], "defer")
        self.assertEqual(result["predictions"]["C"][6]["choice"], "candidate_under_native_guards")
        self.assertEqual(result, compare_arms(cases))

    def test_native_restriction_cannot_be_overridden(self):
        learned = {"counts": {"k": (100, 0)}, "pending": []}
        p = recommend(learned, "k", ["pain_lock"])
        self.assertEqual(p["choice"], "defer")
        self.assertIn("pain_lock", p["reasons"])

    def test_fail_closed_on_pending_and_malformed(self):
        with self.assertRaises(ValueError):
            recommend({"counts": {}, "pending": ["unknown"]}, "k")
        with self.assertRaises(ValueError):
            compare_arms([trial(1, "x", True), trial(1, "x", False)])
        with self.assertRaises(ValueError):
            compare_arms([dict(id="1", context="x", admitted=1, restrictions=[])])

    def test_no_leakage_or_input_mutation(self):
        cases = [trial(i, "train", i < 5) for i in range(8)]
        original = [dict(c) for c in cases]
        result = compare_arms(cases, initial_counts={"other": (4, 0)})
        self.assertEqual(cases, original)
        self.assertEqual(result["final_adaptive_counts"]["other"], (4, 0))
        self.assertEqual(result["metrics"]["B"]["true_admissions"], 0)
        self.assertEqual(result["metrics"]["A"]["true_admissions"], 0)


if __name__ == "__main__":
    unittest.main()
