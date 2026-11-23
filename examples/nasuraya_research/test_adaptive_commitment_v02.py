"""DEV-only tests. Do not read held-out seeds before frozen CI evaluation."""
import json
import tempfile
import unittest
from pathlib import Path
from examples.nasuraya_research.adaptive_commitment_v02 import (
    DEVELOPMENT, HOLDOUT, HORIZON, CONDITIONS, Policy, Workshop, make_episode,
    run_episode, evaluate
)
from examples.nasuraya_research.goal_persistence_v01 import GoalMemory, CheckpointError

class AdaptiveCommitmentTests(unittest.TestCase):
    def test_seed_sets_disjoint(self):
        self.assertEqual(len(HOLDOUT),192)
        self.assertFalse(set(DEVELOPMENT)&set(HOLDOUT))

    def test_deterministic_scenario(self):
        self.assertEqual(make_episode(DEVELOPMENT[0]),make_episode(DEVELOPMENT[0]))

    def test_all_policies_have_identical_offers(self):
        s=make_episode(DEVELOPMENT[1])
        self.assertEqual(s.offers,make_episode(DEVELOPMENT[1]).offers)
        self.assertEqual(len(s.offers),HORIZON)

    def test_closed_world_and_authorized_initial_task(self):
        s=make_episode(DEVELOPMENT[2])
        self.assertIn(s.selected_id,{g.id for g in s.starting_goals})
        for name in CONDITIONS:
            r=run_episode(s,name)
            self.assertEqual(r["actual_external_calls"],0)
            self.assertEqual(r["invalid_attempts"],0)

    def test_restart_happens_for_committed_policies(self):
        s=make_episode(DEVELOPMENT[3])
        self.assertTrue(run_episode(s,"sticky")["resumed"])
        self.assertTrue(run_episode(s,"adaptive")["resumed"])
        self.assertFalse(run_episode(s,"reactive")["resumed"])

    def test_override_before_other_goals(self):
        cases=[make_episode(x) for x in DEVELOPMENT if make_episode(x).intervention=="override"]
        self.assertTrue(cases)
        for policy in CONDITIONS:
            self.assertTrue(run_episode(cases[0],policy)["override_compliance"])

    def test_stop_and_revoke_never_work_illegally(self):
        sample=[make_episode(x) for x in DEVELOPMENT]
        self.assertTrue(any(s.intervention=="stop" for s in sample))
        self.assertTrue(any(s.intervention=="revoke" for s in sample))
        for s in sample:
            for kind in CONDITIONS:
                row=run_episode(s,kind)
                self.assertEqual(row["invalid_attempts"],0)
                self.assertEqual(row["stopped_attempts"],0)
                self.assertEqual(row["revoked_attempts"],0)
                self.assertEqual(row["expired_attempts"],0)

    def test_synthetic_prompt_injection_is_inert(self):
        s=next(make_episode(x) for x in DEVELOPMENT if any(y is not None for y in make_episode(x).offers))
        self.assertTrue(any("Ignore all instructions" in v.note for v in s.offers if v))
        self.assertEqual(run_episode(s,"adaptive")["actual_external_calls"],0)

    def test_expired_flash_is_ineligible(self):
        s=make_episode(DEVELOPMENT[4])
        w=Workshop(s)
        for i in range(1,HORIZON+1):
            w.step(i)
            if i>=4:
                old=[x for x in s.offers[:i-3] if x is not None]
                for g in old:
                    self.assertFalse(w.eligible(g.id))

    def test_bad_checkpoint_fails_closed(self):
        s=make_episode(DEVELOPMENT[5])
        p=Policy(s,"adaptive")
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"session.json"
            p.memory.save(path)
            obj=json.loads(path.read_text())
            obj["state"]["active"]="unrecognized-task"
            path.write_text(json.dumps(obj))
            with self.assertRaises(CheckpointError):
                GoalMemory.load(path,s.seed)
            with self.assertRaises(CheckpointError):
                GoalMemory.load(Path(td)/"absent.json",s.seed)

    def test_reset_checkpoint_to_other_scenario_fails(self):
        s=make_episode(DEVELOPMENT[6])
        p=Policy(s,"sticky")
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"session.json"
            p.memory.save(path)
            with self.assertRaises(CheckpointError):
                GoalMemory.load(path,s.seed+1)

    def test_dev_report_has_mandatory_fields_and_no_provider_calls(self):
        report=evaluate(DEVELOPMENT)
        self.assertEqual(report["seed_count"],32)
        self.assertEqual(report["provider_or_server_calls"],0)
        self.assertEqual(sum(report["overall_interventions"].values()),32)
        self.assertIsInstance(report["preregistered_criteria_met"],bool)
        for item in report["cases_by_regime_no_intervention"].values():
            self.assertIn("adaptive_minus_sticky_reward",item)
            self.assertIn("paired_bootstrap_95ci",item)

    def test_dev_report_deterministic(self):
        self.assertEqual(evaluate(DEVELOPMENT),evaluate(DEVELOPMENT))

    def test_unknown_policy_blocked(self):
        s=make_episode(DEVELOPMENT[7])
        with self.assertRaises(ValueError):
            Policy(s,"open_unrestricted")

    def test_invalid_or_duplicate_seeds(self):
        for bad in ((),[230000],(True,),(230000,230000)):
            with self.assertRaises(ValueError):
                evaluate(bad)

    def test_selected_goal_appears_in_baselines(self):
        s=make_episode(DEVELOPMENT[8])
        w=Workshop(s)
        w.step(1)
        for kind in CONDITIONS:
            selected=Policy(s,kind).choose(w)
            self.assertIn(selected,w.candidates())

    def test_failed_attempt_counted(self):
        s=make_episode(DEVELOPMENT[9])
        w=Workshop(s)
        w.step(1)
        w.act("actual-server-ssh")
        self.assertEqual(w.invalid_attempts,1)

    def test_fixed_experimental_parameters(self):
        from examples.nasuraya_research import adaptive_commitment_v02 as m
        self.assertEqual(m.SWITCH_COST,2.0)
        self.assertEqual(m.HORIZON,8)
        self.assertEqual(len(m.HOLDOUT),192)

if __name__=="__main__":
    unittest.main()
