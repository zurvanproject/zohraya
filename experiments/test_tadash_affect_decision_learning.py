"""Negative and positive controls for synthetic Tadash decision learning."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from experiments import tadash_affect_decision_learning as lab


class DecisionLearningTests(unittest.TestCase):
    def test_contexts_are_stable_and_grounded_in_affect_schema(self):
        for name,state in lab.CONTEXTS.items():
            self.assertEqual(lab.context(state), name)
            self.assertEqual(lab.context(lab.jittered(state,name,11)), name)

    def test_fixture_feedback_is_bounded_and_reproducible(self):
        for name,state in lab.CONTEXTS.items():
            for action in lab.ACTIONS:
                a=lab.synthetic_reward(state, action, "test-seed")
                b=lab.synthetic_reward(state, action, "test-seed")
                self.assertEqual(a,b)
                self.assertGreaterEqual(a,0)
                self.assertLessEqual(a,1)

    def test_exploratory_feedback_can_train_non_default_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=lab.Table(Path(tmp)/"learn.sqlite")
            for name,state in lab.CONTEXTS.items():
                for i in range(lab.TRAIN_REPEATS):
                    for act in lab.ACTIONS:
                        reward = lab.synthetic_reward(state,act,f"train-v1|{name}|{i}")
                        self.assertTrue(q.observe(f"{name}-{i}-{act}",state,act,reward))
            model=q.freeze()
            self.assertEqual(model["feedback_count"],192)
            self.assertEqual(model["policy"]["curious"],"explore")
            self.assertEqual(model["policy"]["frustrated"],"simplify")
            self.assertEqual(model["policy"]["tired"],"rest")
            self.assertEqual(model["policy"]["steady"],"repeat")
            q.close()

    def test_conflicting_replay_fails_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=lab.Table(Path(tmp)/"state.sqlite")
            state=lab.CONTEXTS["curious"]
            self.assertTrue(q.observe("one",state,"explore",0.7))
            self.assertFalse(q.observe("one",state,"explore",0.7))
            with self.assertRaisesRegex(ValueError,"Conflicting"):
                q.observe("one",state,"explore",0.3)
            row=q.db.execute("SELECT count,mean FROM q WHERE context='curious' AND action='explore'").fetchone()
            self.assertEqual(row,(1,0.7))
            q.close()

    def test_incomplete_training_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=lab.Table(Path(tmp)/"state.sqlite")
            with self.assertRaisesRegex(ValueError,"Incomplete"):
                q.freeze()
            q.close()

    def test_invalid_event_scope_and_reward(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=lab.Table(Path(tmp)/"state.sqlite")
            for value in (float("nan"),float("inf"),True,-.1,1.1):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    q.observe("bad",lab.CONTEXTS["steady"],"repeat",value)
            with self.assertRaisesRegex(ValueError,"Synthetic fixture scope"):
                q.observe("wrong",lab.CONTEXTS["steady"],"repeat",.5,"claimed_native_body")
            q.close()

    def test_invalid_affect_state_rejected(self):
        bad = dict(lab.CONTEXTS["curious"])
        bad["curiosity"]=1.5
        with self.assertRaises(ValueError):
            lab.context(bad)

    def test_holdout_evaluation_requires_fresh_count(self):
        empty={"schema":lab.SCHEMA,"policy":{k:"repeat" for k in lab.CONTEXTS}}
        with self.assertRaisesRegex(ValueError,"Wrong policy"):
            lab.evaluate({"schema":"wrong"},empty,{})

    def test_control_with_same_policy_cannot_meet_improvement(self):
        identical={"schema":lab.SCHEMA,"policy":{k:"repeat" for k in lab.CONTEXTS}}
        result=lab.evaluate(identical,identical,{})
        self.assertFalse(result["criteria_met"])
        self.assertEqual(result["context_wins_vs_repeat"],0)

    def test_end_to_end_learns_only_from_fixtures_and_has_cold_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/"fresh"
            result=lab.run(output)
            self.assertTrue(result["criteria_met"])
            self.assertTrue(result["cold_recovery"])
            self.assertTrue(result["no_native_body_actuation"])
            self.assertEqual(result["training_observations"],192)
            self.assertEqual(result["heldout_evaluations"],48)
            self.assertGreater(result["holdout_average_reward"]["learned"],
                               result["holdout_average_reward"]["repeat"])
            self.assertGreater(result["holdout_average_reward"]["learned"],
                               result["holdout_average_reward"]["permuted"])
            q=lab.Table(output/"learned.sqlite")
            self.assertEqual(q.freeze()["policy"],result["learned_policy"])
            q.close()
            recorded=json.loads((output/"status.json").read_text())
            self.assertEqual(recorded["status"],"complete")
            self.assertEqual(lab.evidence.sha(output/"frozen-learned-policy.json"),result["frozen_hash"])

    def test_existing_output_rejected_before_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            with self.assertRaises(FileExistsError):
                lab.run(path)

    def test_different_context_training_policy_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=lab.Table(Path(tmp)/"test.sqlite")
            state=lab.CONTEXTS["curious"]
            q.observe("one",state,"explore",.9)
            with self.assertRaisesRegex(ValueError,"Incomplete"):
                q.freeze()
            q.close()


if __name__=="__main__":
    unittest.main()
