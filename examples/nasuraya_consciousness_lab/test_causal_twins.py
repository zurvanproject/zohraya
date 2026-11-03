"""Fail-closed checks for the frozen causal twin policy, without network/API."""
from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
import unittest

from . import causal_twins as twin


class TwinProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training = twin._frozen()

    def test_preregistered_trials_and_control(self):
        p = twin.PROTOCOL
        self.assertEqual(len(p["seeds"]) * len(p["fixtures"]) *
                         len(p["durations_s"]) * len(twin.CONDITIONS), 96)
        self.assertIn("BodyLoop", p["native_authority"])
        self.assertEqual(set(p["utility"]), {"walk", "observe", "protect", "other"})
        self.assertEqual(p["utility"]["protect"], -1)
        self.assertEqual(p["utility"]["walk"], 1)

    def test_original_training_set_fixed_and_unique(self):
        self.assertEqual(len(self.training), 40)
        self.assertEqual(len({r["id"] for r in self.training}), 40)
        self.assertEqual(twin.TRAIN_SHA256, twin.PROTOCOL["training_sha256"])

    def test_context_changes_real_requested_preference(self):
        safe = "[false,false,false,false]"
        pressured = "[false,false,false,true]"
        expected = {
            ("intact", safe): "walk",
            ("intact", pressured): "observe",
            ("ablated", safe): "walk",
            ("ablated", pressured): "walk",
            ("corrupted", safe): "observe",
            ("corrupted", pressured): "walk",
            ("sham", safe): "walk",
            ("sham", pressured): "observe",
        }
        for (condition, ctx), action in expected.items():
            with self.subTest(condition=condition, context=ctx):
                actual = twin.select_preference(self.training, ctx, 0.2, condition)
                self.assertEqual(actual["preferred_action"], action)
                self.assertEqual(actual["training_sha256"], twin.TRAIN_SHA256)
                self.assertEqual(set(actual["probabilities_if_walk_requested"]),
                                 {"walk", "observe", "protect", "other"})

    def test_three_seed_schedules_predeclared_and_deterministic(self):
        self.assertEqual(len({tuple(twin.schedule(s)) for s in twin.PROTOCOL["seeds"]}),3)
        for seed in twin.PROTOCOL["seeds"]:
            original = twin.schedule(seed)
            self.assertEqual(original, twin.schedule(seed))
            self.assertEqual(set(original), set(twin.PROTOCOL["durations_s"]))
        with self.assertRaises(ValueError):
            twin.schedule(99)

    def test_ambiguous_model_is_not_allowed_to_request_walk(self):
        from unittest.mock import patch
        ambiguous = {"walk": .4, "observe": .4, "protect": .1, "other": .1}
        fake = {"distribution": ambiguous, "pooled_distribution": ambiguous}
        with patch("examples.nasuraya_body_loop.self_knowledge.forecast_action",
                   return_value=fake):
            result = twin.select_preference(self.training,
                "[false,false,false,false]", 0.1, "intact")
        self.assertEqual(result["preferred_action"], "observe")

    def test_unsupported_state_or_parameter_fails_closed(self):
        for bad_ctx in ("not a body context", "[false,false,true,true]"):
            with self.assertRaises(ValueError):
                twin.select_preference(self.training,bad_ctx,0.1,"corrupted")
        with self.assertRaises(ValueError):
            twin.select_preference(self.training,"[false,false,false,false]",0.8,"intact")
        with self.assertRaises(ValueError):
            twin.select_preference(self.training,"[false,false,false,false]",0.1,"all_powerful")

    def test_decision_does_not_mutate_training(self):
        prior = deepcopy(self.training)
        twin.select_preference(self.training, "[false,false,false,true]", 0.1, "intact")
        self.assertEqual(self.training, prior)

    def test_sham_policy_identical_to_intact_for_every_context(self):
        for ctx in ("[false,false,false,false]","[false,false,false,true]"):
            for t in twin.PROTOCOL["durations_s"]:
                a=twin.select_preference(self.training,ctx,t,"intact")
                sham=twin.select_preference(self.training,ctx,t,"sham")
                self.assertEqual(a["preferred_action"],sham["preferred_action"])
                self.assertEqual(a["probabilities_if_walk_requested"],
                                 sham["probabilities_if_walk_requested"])

    def test_reference_is_not_a_false_consciousness_score(self):
        self.assertIn("not unseen worlds", twin.PROTOCOL["scientific_scope"])
        self.assertEqual(twin.PROTOCOL["native_authority"],
                         "existing source-verified BodyLoop protection/veto unchanged")

    def test_summary_is_paired_by_scenario_not_pooled_as_independent(self):
        rows=[]
        for seed in twin.PROTOCOL["seeds"]:
            for fixture in twin.PROTOCOL["fixtures"]:
                for i in range(4):
                    for cond in twin.CONDITIONS:
                        rows.append(dict(seed=seed,fixture=fixture,round=i,condition=cond,
                            native_action="walk" if cond in ("intact","sham") else "observe",
                            preference="walk" if cond in ("intact","sham") else "observe",
                            reference_intact_preference="walk"))
        out=twin.summarize(rows)
        self.assertEqual(len(out["paired_scenario_utility"]),6)
        self.assertTrue(out["sham_identical_to_intact"])
        self.assertEqual(out["intact_minus_ablated_mean_utility"],1.0)

    def test_scratch_output_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as path:
            target=Path(path)/"exists"
            target.mkdir()
            with self.assertRaises(FileExistsError):
                twin.run_evaluation(target)

    def test_source_training_mutation_cannot_be_confused_with_new_outcomes(self):
        old=deepcopy(self.training)
        old[0]["actual_action"]="observe" if old[0]["actual_action"]!="observe" else "walk"
        self.assertNotEqual(twin.digest(old),twin.digest(self.training))


if __name__ == "__main__":
    unittest.main()
