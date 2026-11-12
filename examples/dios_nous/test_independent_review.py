"""Adversarial review by a separate agent; not independent human evaluation.

The historical-query and duck-typed event regressions were first reproduced
as failing behaviors during review, before these retained tests were written.
No held-out case or expected answer was consulted to author these checks.
"""
from dataclasses import make_dataclass
from pathlib import Path
import tempfile
import unittest

from examples.dios_nous.cognition import (
    AdvisoryGoalPlanner, CognitiveSession, EvidenceEvent, GoalOption,
    PreferenceProfile,
)
from examples.dios_nous.reused.epistemic_revision_v01 import Evidence


class IndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def session(self):
        return CognitiveSession(self.root / "review.sqlite", self.root / "review.anchor")

    def test_historical_query_does_not_rewrite_current_belief(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, "A", 1, 1))
            session.append(EvidenceEvent(2, 1, 1, "B", 2, 2))
            session.assess(1, 1, 2, "B")
            historical = session.assess(1, 1, 1, "A")
            self.assertTrue(historical["historical_query"])
            self.assertFalse(historical["revised"])
            current = session.assess(1, 1, 2, "B")
            self.assertEqual(current["previous_decision"], "B")
            self.assertFalse(current["revised"])

    def test_equal_view_at_later_time_still_advances_live_frontier(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, "A", 1, 1))
            session.assess(1, 1, 1, "A")
            session.assess(1, 1, 4, "A")
            historical = session.assess(1, 1, 3, "A")
            self.assertTrue(historical["historical_query"])
            self.assertFalse(historical["revised"])

    def test_duck_typed_event_cannot_bypass_private_text_boundary(self):
        class InjectedEvent:
            def evidence(self):
                return Evidence("PRIVATE_CANARY_668", "fixture:1", "fixture:1",
                                "A", 1, "PRIVATE_ROOT_669", "owner_observation", True)
        with self.session() as session:
            with self.assertRaises((TypeError, ValueError)):
                session.append(InjectedEvent())
            dump = "\n".join(session.memory.conn.iterdump())
            self.assertNotIn("PRIVATE_CANARY_668", dump)
            self.assertNotIn("PRIVATE_ROOT_669", dump)

    def test_unrecognized_preference_fields_cannot_be_persisted(self):
        ForgedProfile = make_dataclass("ForgedProfile", [
            ("benefit_weight", int), ("effort_weight", int),
            ("PRIVATE_PROFILE_FIELD_771", int),
        ])
        planner = AdvisoryGoalPlanner(self.root / "goals.json", self.root / "goals.anchor", 1)
        with self.assertRaises((TypeError, ValueError)):
            planner.plan((GoalOption(1, 2, 1),), ForgedProfile(1, 1, 1))
        if planner.path.exists():
            self.assertNotIn("PRIVATE_PROFILE_FIELD_771", planner.path.read_text())

    def test_stop_with_no_candidates_survives_restart(self):
        checkpoint, anchor = self.root / "goals.json", self.root / "goals.anchor"
        planner = AdvisoryGoalPlanner(checkpoint, anchor, 1)
        planner.plan((GoalOption(1, 2, 1),), PreferenceProfile())
        stopped = planner.plan((), PreferenceProfile(), stop=True)
        self.assertIsNone(stopped["selected_goal"])
        restored = AdvisoryGoalPlanner(checkpoint, anchor, 1)
        attempted = restored.plan((GoalOption(2, 999, 0),), PreferenceProfile(), revise=True)
        self.assertIsNone(attempted["selected_goal"])
        self.assertFalse(attempted["execution_performed"])


if __name__ == "__main__":
    unittest.main()
