"""Synthetic-only tests for read-only body/ritual ↔ evidence handoff."""
from __future__ import annotations
import copy
import unittest
from tools import nasu_embodied_ritual_handoff as h


class HandoffContracts(unittest.TestCase):
    def setUp(self):
        self.journal = {"status": "ok", "records": 1, "latest": {
            "local_checks_passed": True, "states": {
                "continuity": "verified_history", "frontier": "verified_history",
                "cognition": "verified_history", "feedback": "verified_history",
                "awake": "structural_only"}, "PRIVATE_INPUT": "secret"},
            "PRIVATE_INPUT": "secret"}
        self.sim = {"schema": h.RITUAL_SCHEMA, "mode": "OFFLINE_STATIC_CONTACT_REHEARSAL",
            "repetitions_per_ritual": 3, "complete_ritual_runs": 9,
            "static_contact_checks": 27, "static_contact_passed": 27,
            "all_passed": True, "no_body_motion_executed": True,
            "not_dynamically_validated": True, "live_atmosphere_secured": False,
            "no_memory_changed": True, "no_keys_checked": True,
            "provenance": {"body_scale": "adult_scale_250cm_195kg_fixture_not_canon_claim",
              "toes_each": 3, "digitigrade": True,
              "design_sha256": "a"*64, "contact_sha256": "b"*64},
            "rounds": [{"ritual": name, "round": r, "passed": True,
                         "phases": [{"actuation":"NO_ACTUATION", "static_contact": {
                          "safe": True, "state": "STATIC_CANDIDATE"}} for i in range(3)]}
                        for name in h.RITUAL_IDS for r in (1,2,3)]}
        self.threat = {"schema": h.RITUAL_SCHEMA, "threats": 18, "passed": 18,
                       "all_passed": True, "motion_executes": False}

    def run_contract(self):
        return h.compose(self.journal, self.sim, self.threat)

    def test_good_fixture_only_research(self):
        r = self.run_contract()
        self.assertEqual(r["decision"], "RESEARCH_REVIEW_ONLY")
        self.assertEqual(r["next_experiment"], "dynamic_body_canon_validation")
        self.assertFalse(r["body_actuation"])
        self.assertFalse(r["live_dios_connected"])
        self.assertEqual(r["body_ritual"]["canon_geometry"], "UNVERIFIED")
        self.assertNotIn("secret", h._compact(r))

    def test_deterministic_no_memory_change(self):
        old = (copy.deepcopy(self.journal), copy.deepcopy(self.sim), copy.deepcopy(self.threat))
        self.assertEqual(self.run_contract(), self.run_contract())
        self.assertEqual(old, (self.journal, self.sim, self.threat))

    def test_missing_or_invalid_journal_blocks(self):
        for state in ("missing", "invalid"):
            self.journal = {"status": state, "private": "secret"}
            self.assertEqual(self.run_contract()["decision"], "HOLD_EVIDENCE")

    def test_unhealthy_component_blocks(self):
        self.journal["latest"]["states"]["frontier"] = "invalid"
        self.assertEqual(self.run_contract()["decision"], "HOLD_EVIDENCE")

    def test_partial_history_blocks(self):
        self.journal["latest"]["local_checks_passed"] = False
        self.assertEqual(self.run_contract()["decision"], "HOLD_EVIDENCE")

    def test_unknown_component_and_state_rejected(self):
        self.journal["latest"]["states"]["rogue"] = "verified_history"
        with self.assertRaises(ValueError): self.run_contract()
        del self.journal["latest"]["states"]["rogue"]
        self.journal["latest"]["states"]["awake"] = "externally_authenticated"
        with self.assertRaises(ValueError): self.run_contract()

    def test_no_fabricated_round_count(self):
        self.sim["rounds"] = self.sim["rounds"][:-1] + [copy.deepcopy(self.sim["rounds"][0])]
        with self.assertRaises(ValueError): self.run_contract()

    def test_failed_contact_blocks_even_if_summary_claims_pass(self):
        self.sim["rounds"][0]["phases"][0]["static_contact"]["safe"] = False
        with self.assertRaises(ValueError): self.run_contract()

    def test_actual_actuation_marker_rejected(self):
        self.sim["rounds"][2]["phases"][1]["actuation"] = "MOVE"
        with self.assertRaises(ValueError): self.run_contract()

    def test_bad_morphology_is_rejected(self):
        self.sim["provenance"]["body_scale"] = "170cm_canon_verified"
        with self.assertRaises(ValueError): self.run_contract()

    def test_missing_adversarial_checks_rejected(self):
        self.threat["passed"] = 17
        with self.assertRaises(ValueError): self.run_contract()

    def test_journal_must_contain_a_real_record(self):
        self.journal["records"] = 0
        with self.assertRaises(ValueError): self.run_contract()

    def test_bool_is_not_count(self):
        self.journal["records"] = True
        with self.assertRaises(ValueError): self.run_contract()

    def test_no_exception_private_text(self):
        self.sim["provenance"]["contact_sha256"] = "SECRET"*12
        with self.assertRaises(ValueError) as ctx: self.run_contract()
        self.assertNotIn("SECRET", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
