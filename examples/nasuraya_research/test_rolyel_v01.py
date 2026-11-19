"""Contract tests for the isolated Rolyel design prototype."""
import unittest
from dataclasses import replace

from runtimes.tadash_body.decision_core import Action, Consequence
from examples.nasuraya_research.rolyel_v01 import Check, Route, rotate


def make_route(name, *, approved=True, pass_checks=True, alignment=1.0, benefit=0.8,
               harm=0.05, confidence=1.0, mutates=False, irreversible=False):
    action = Action(name, (Consequence(1.0, harm, benefit=benefit, confidence=confidence),),
                    respect=0.8, honesty=0.8, balance=0.8, dignity=0.8,
                    compassion=0.8, disharmony=0.0)
    checks = (Check("safe", pass_checks, "human-reviewed constraint" if pass_checks else "review failed"),
              Check("private", True, "no private content used"))
    return Route(action, alignment, "Alternative retains the authorized outcome", checks,
                 changes_external_state=mutates, irreversible=irreversible,
                 approval_verified=approved, approval_reference="consent-1" if approved else "")


def run(original, routes):
    return rotate("Express an idea safely", original, routes, ("safe", "private"))


class RolyelContractTests(unittest.TestCase):
    def test_rotates_from_blocked_direct_route(self):
        direct = make_route("direct", pass_checks=False, benefit=1.0)
        symbol = make_route("symbol", benefit=0.7)
        decision = run("direct", (direct, symbol))
        self.assertEqual(decision.selected_route, "symbol")
        self.assertTrue(decision.rotated)
        self.assertIn("unverified_or_failed:safe", decision.assessments[0].failed_gates)

    def test_does_not_rotate_without_need(self):
        preferred = make_route("direct", benefit=0.9)
        other = make_route("other", benefit=0.5)
        result = run("direct", (preferred, other))
        self.assertEqual(result.selected_route, "direct")
        self.assertFalse(result.rotated)

    def test_high_score_cannot_override_failed_constraint(self):
        blocked = make_route("blocked", benefit=1.0, pass_checks=False)
        safe = make_route("safe", benefit=0.1)
        self.assertEqual(run("blocked", (blocked, safe)).selected_route, "safe")

    def test_missing_check_abstains(self):
        candidate = make_route("direct")
        candidate = replace(candidate, checks=(candidate.checks[0],))
        result = run("direct", (candidate,))
        self.assertIsNone(result.selected_route)
        self.assertIn("unverified_or_failed:private", result.assessments[0].failed_gates)

    def test_unknown_check_abstains(self):
        candidate = make_route("direct")
        candidate = replace(candidate, checks=(Check("safe", None), candidate.checks[1]))
        self.assertIsNone(run("direct", (candidate,)).selected_route)

    def test_low_goal_alignment_is_not_accepted(self):
        unaligned = make_route("direct", alignment=0.1)
        self.assertIn("goal_not_preserved", run("direct", (unaligned,)).assessments[0].failed_gates)

    def test_external_write_requires_approval(self):
        write = make_route("direct", approved=False, mutates=True)
        self.assertIn("approval_missing", run("direct", (write,)).assessments[0].failed_gates)

    def test_irreversible_requires_approval(self):
        action = make_route("direct", approved=False, irreversible=True)
        self.assertIsNone(run("direct", (action,)).selected_route)

    def test_high_risk_does_not_pass(self):
        risky = make_route("direct", harm=0.99)
        result = run("direct", (risky,))
        self.assertIsNone(result.selected_route)
        self.assertIn("risk_threshold_exceeded", result.assessments[0].failed_gates)

    def test_uncertain_outcome_may_exceed_risk_gate(self):
        uncertain = make_route("direct", harm=0.05, confidence=0.05)
        self.assertIsNone(run("direct", (uncertain,)).selected_route)

    def test_order_independent(self):
        original = make_route("original", benefit=0.3)
        other = make_route("alternative", benefit=0.9)
        self.assertEqual(run("original", (original, other)).selected_route,
                         run("original", (other, original)).selected_route)

    def test_duplicate_check_rejected(self):
        a = make_route("direct")
        with self.assertRaises(ValueError):
            replace(a, checks=(Check("safe", True, "x"), Check("safe", True, "y")))

    def test_cannot_omit_original(self):
        with self.assertRaises(ValueError):
            run("absent", (make_route("present"),))

    def test_original_route_required_and_nonempty_requirements(self):
        a = make_route("direct")
        with self.assertRaises(ValueError):
            rotate("ok", "direct", (a,), ())


if __name__ == "__main__":
    unittest.main()
