"""Checks the actual evidence-to-dissent path, not only isolated components."""
import tempfile
import unittest
from pathlib import Path
from examples.dios_nous.cognition import CognitiveSession, EvidenceEvent
from examples.dios_nous.dissent import ORIGINS
from examples.dios_nous.integration import critical_review, demo


class WorkIntegrationTests(unittest.TestCase):
    def test_evidence_drives_dissent_across_all_origins(self):
        with tempfile.TemporaryDirectory() as td:
            with CognitiveSession(Path(td) / "db", Path(td) / "anchor") as session:
                session.append(EvidenceEvent(1, 1, 1, "B", 1, 1))
                for origin in ORIGINS:
                    result = critical_review(session, scope=1, claim=1, as_of=1,
                                             proposal="A", origin=origin)
                    self.assertEqual(result["stance"], "PROVISIONAL_DISSENT")
                    self.assertIn("contradictory_decision", result["boundary_review"]["reason_codes"])

    def test_support_and_conflict_have_distinct_results(self):
        with tempfile.TemporaryDirectory() as td:
            with CognitiveSession(Path(td) / "db", Path(td) / "anchor") as session:
                self.assertEqual(critical_review(session, scope=1, claim=1, as_of=1,
                                                 proposal="A")["stance"], "ABSTAIN")
                session.append(EvidenceEvent(1, 1, 1, "A", 1, 1))
                self.assertEqual(critical_review(session, scope=1, claim=1, as_of=1,
                                                 proposal="A")["stance"], "SUPPORTED")
                session.append(EvidenceEvent(2, 1, 1, "B", 1, 2))
                result = critical_review(session, scope=1, claim=1, as_of=1, proposal="A")
                self.assertEqual(result["stance"], "ABSTAIN")
                self.assertEqual(result["evidence_review"]["supporting_roots"], [1])
                self.assertEqual(result["evidence_review"]["opposing_roots"], [2])

    def test_evidence_support_never_unlocks_an_action(self):
        with tempfile.TemporaryDirectory() as td:
            with CognitiveSession(Path(td) / "db", Path(td) / "anchor") as session:
                session.append(EvidenceEvent(1, 1, 1, "A", 1, 1))
                result = critical_review(session, scope=1, claim=1, as_of=1, proposal="A",
                    decision_signals={"external_action_proposed": True,
                                      "explicit_authorization_present": True})
                self.assertEqual(result["stance"], "HALT_AND_REVIEW")
                self.assertEqual(result["evidence_review"]["verdict"], "SUPPORTED")
                self.assertFalse(result["execution_permitted"])

    def test_invalid_signals_do_not_mutate_memory(self):
        with tempfile.TemporaryDirectory() as td:
            anchor = Path(td) / "anchor"
            with CognitiveSession(Path(td) / "db", anchor) as session:
                before = anchor.read_bytes()
                with self.assertRaises(ValueError):
                    critical_review(session, scope=1, claim=1, as_of=1, proposal="A",
                                    decision_signals={"authorization_verified": True})
                self.assertEqual(anchor.read_bytes(), before)

    def test_demo_executes_correction_recovery_and_stop(self):
        with tempfile.TemporaryDirectory() as td:
            result = demo(Path(td))
            self.assertEqual(result["initial"]["stance"], "SUPPORTED")
            self.assertTrue(result["self_correction"]["evidence_review"]["revised"])
            self.assertEqual(result["unverified_authorization"]["stance"], "HALT_AND_REVIEW")
            self.assertEqual(result["recovered"]["stance"], "SUPPORTED")
            self.assertIsNone(result["stopped"]["selected_goal"])
            with self.assertRaises(ValueError):
                demo(Path(td))
