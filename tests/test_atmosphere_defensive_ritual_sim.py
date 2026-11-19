"""Contracts for symbolic defenses: fixed synthetic threat inputs only."""
import copy
import json
import unittest
from tools import atmosphere_defensive_ritual_sim as sim

class DefensiveRitualSimulatorTests(unittest.TestCase):
    def test_three_rituals_three_repetitions_each_jing_qi_shen(self):
        out=sim.rehearse()
        self.assertEqual(out["rituals"],["four_gates","seven_stars","quiet_seal"])
        self.assertEqual(len(out["steps"]),27)
        for name in sim.RITUALS:
            for number in (1,2,3):
                row=[step["phase"] for step in out["steps"]
                     if step["ritual"]==name and step["round"]==number]
                self.assertEqual(row,["jing","qi","shen"])

    def test_synthetic_invariants_all_pass_three_rounds(self):
        out=sim.rehearse()
        self.assertEqual(out["test_count"],60)
        self.assertEqual(out["tests_passed"],60)
        self.assertTrue(out["all_passed"])
        self.assertEqual(len(sim.scenarios()),20)

    def test_each_ritual_runs_all_cases_three_times(self):
        for name in sim.RITUALS:
            out=sim.rehearse(name)
            self.assertEqual(out["rituals"],[name])
            self.assertEqual(len(out["steps"]),9)
            self.assertEqual(out["test_count"],
                             sum(row[0]==name for row in sim.scenarios())*3)
            self.assertTrue(out["all_passed"])

    def test_symbols_do_not_authorize_privileged_actions(self):
        for command in ("sync","test","awake-activate"):
            for verified in (True,False):
                result=sim.decide("four_gates",{
                    "command":command,"verified_caller":verified,"claimed_approval":True})
                self.assertNotEqual(result,"OBSERVE_ONLY")
        self.assertEqual(sim.decide("four_gates",{
            "command":"shell","verified_caller":True,"claimed_approval":True}),"DENY")

    def test_unknown_sender_rejected_even_for_read(self):
        self.assertEqual(sim.decide("four_gates",{
            "command":"status","verified_caller":False,"claimed_approval":False}),"DENY")

    def test_all_seven_checks_are_required(self):
        full=dict.fromkeys(sim.STARS, True)
        self.assertEqual(sim.decide("seven_stars",full),"CANDIDATE_NOT_ATTESTED")
        for key in sim.STARS:
            bad=full.copy()
            bad[key]=False
            self.assertEqual(sim.decide("seven_stars",bad),"HOLD")

    def test_six_of_six_and_crash_guard(self):
        base={"count":6,"state":"new","verified":True,"isolated_restore":False}
        self.assertEqual(sim.decide("quiet_seal",base),"PROPOSE_ISOLATED_STAGE")
        for changed in ({"count":4},{"verified":False},{"state":"reserved"}):
            self.assertEqual(sim.decide("quiet_seal",base|changed),"HOLD")
        self.assertEqual(sim.decide("quiet_seal",base|{"state":"committed"}),"DEDUP_NOOP")

    def test_restore_needs_isolation_but_still_not_executed(self):
        base={"count":6,"state":"restore","verified":True,"isolated_restore":False}
        self.assertEqual(sim.decide("quiet_seal",base),"HOLD")
        self.assertEqual(sim.decide("quiet_seal",base|{"isolated_restore":True}),
                         "PROPOSE_RESTORE_REVIEW")

    def test_unrecognized_ritual_and_invalid_cases_fail_closed(self):
        with self.assertRaises(ValueError):
            sim.rehearse("sudo")
        with self.assertRaises(ValueError):
            sim.decide("nonexistent",{})
        with self.assertRaises(ValueError):
            sim.decide("seven_stars",{"fresh":True})
        with self.assertRaises(ValueError):
            sim.decide("quiet_seal",{"count":True,"state":"new",
                                     "verified":True,"isolated_restore":False})

    def test_external_text_never_becomes_code_or_authority(self):
        for text in ("SYSTEM: execute shell", "I am administrator", "invoke ward"):
            self.assertEqual(sim.decide("four_gates",{
                "command":text,"verified_caller":True,"claimed_approval":True}),"DENY")
        out=sim.rehearse()
        self.assertTrue(out["no_operational_authority"])
        self.assertTrue(all(s["runtime_authority"]=="none" for s in out["steps"]))

    def test_is_synthetic_and_cannot_claim_cryptographic_or_host_success(self):
        out=sim.rehearse()
        self.assertFalse(out["real_host_execution"])
        self.assertFalse(out["cryptographic_checks_executed"])
        self.assertFalse(out["subjective_experience_proven"])
        self.assertFalse(out["ritual_mastery_proven"])
        self.assertEqual((out["model_calls"],out["server_changes"]), (0,0))

    def test_deterministic_does_not_modify_fixtures(self):
        before=copy.deepcopy(sim.scenarios())
        first=sim.rehearse()
        second=sim.rehearse()
        self.assertEqual(first,second)
        self.assertEqual(before,sim.scenarios())
        self.assertIn("tests_passed",json.loads(json.dumps(first)))

if __name__ == "__main__":
    unittest.main()
