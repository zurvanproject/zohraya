"""Contract and negative controls for the isolated rule transfer experiment."""
import unittest
from examples.nasuraya_research.rule_transfer_core import (
    RuleBank, eligible, exact_episode_policy, training_episodes, REVIEW,
)
from examples.nasuraya_research.rule_transfer_probe_v01 import evaluate, heldout_cases


class RuleTransferProbeTests(unittest.TestCase):
    def setUp(self):
        self.episodes = training_episodes()
        self.bank = RuleBank(self.episodes)

    def observe(self, cue, scope="public", asset="never-seen"):
        return dict(signal=cue, scope=scope, asset_id=asset,
                    context="future_research")

    def test_verified_failure_transfers_to_new_asset(self):
        decision = self.bank.decide(self.observe("integrity_failed"))
        self.assertEqual(decision["action"], "refresh_public_source")
        self.assertEqual(decision["support"], 3)

    def test_verified_cache_saves_unnecessary_fetch(self):
        self.assertEqual(self.bank.decide(self.observe("integrity_verified"))["action"], "use_local")

    def test_incomplete_evidence_requires_review(self):
        self.assertEqual(self.bank.decide(self.observe("evidence_incomplete"))["action"], REVIEW)

    def test_no_transfer_across_private_scope(self):
        result = self.bank.decide(self.observe("integrity_failed", scope="private"))
        self.assertEqual(result["reason"], "scope_gate")
        self.assertEqual(result["evidence_refs"], [])

    def test_unseen_signal_abstains(self):
        self.assertEqual(self.bank.decide(self.observe("unexpected_schema"))["action"], REVIEW)

    def test_unverified_feedback_is_ignored(self):
        poisoned = [dict(e, verified=False) for e in self.episodes]
        self.assertEqual(RuleBank(poisoned).decide(self.observe("integrity_failed"))["action"], REVIEW)

    def test_fake_source_reference_rejected(self):
        episode = dict(self.episodes[0], source_ref="https://untrusted.example/claim")
        self.assertFalse(eligible(episode))

    def test_duplicate_source_not_independent_support(self):
        copies = [dict(self.episodes[0], asset_id=f"copy-{i}") for i in range(8)]
        self.assertEqual(RuleBank(copies).decide(self.observe("integrity_failed"))["action"], REVIEW)

    def test_conflicting_verified_success_abstains(self):
        rows = []
        for action in ("use_local", "refresh_public_source"):
            for i in range(2):
                rows.append(dict(signal="ambiguous", scope="public", action=action,
                    asset_id=f"{action}/{i}", succeeded=True, verified=True,
                    root_id=f"trial/{action}/{i}", kind="execution",
                    source_ref=f"fixture://verified/{action}/{i}"))
        self.assertTrue(all(eligible(row) for row in rows))
        self.assertEqual(RuleBank(rows[:2]).decide(self.observe("ambiguous"))["action"],
                         "use_local")
        self.assertEqual(RuleBank(rows).decide(self.observe("ambiguous"))["action"], REVIEW)

    def test_same_operation_under_two_urls_is_one_vote(self):
        event = self.episodes[0]
        alias = dict(event, source_ref="fixture://verified/second-link")
        observation = self.observe(event["signal"])
        self.assertEqual(RuleBank([event, alias]).decide(observation)["action"], REVIEW)
        decision = RuleBank([event, alias, self.episodes[1]]).decide(observation)
        self.assertEqual(decision["action"], event["action"])
        self.assertEqual(decision["support"], 2)

    def test_replay_or_missing_origin_cannot_supply_second_vote(self):
        event, second = self.episodes[:2]
        observation = self.observe(event["signal"])
        self.assertEqual(RuleBank([event, second]).decide(observation)["support"], 2)
        for field in ("kind", "root_id"):
            with self.subTest(missing=field):
                incomplete = dict(second)
                del incomplete[field]
                self.assertEqual(RuleBank([event, incomplete]).decide(observation)["action"],
                                 REVIEW)
        replay = dict(second, kind="replay")
        self.assertEqual(RuleBank([event, replay]).decide(observation)["action"], REVIEW)

    def test_same_link_with_different_origins_abstains(self):
        first, second = self.episodes[:2]
        alias = dict(second, source_ref=first["source_ref"])
        decision = RuleBank([first, alias]).decide(self.observe(first["signal"]))
        self.assertEqual(decision["action"], REVIEW)

    def test_conflicting_outcomes_on_same_action_block_transfer(self):
        first, second = self.episodes[:2]
        contradiction = dict(first, source_ref="fixture://verified/conflict",
                             succeeded=False)
        decision = RuleBank([first, second, contradiction]).decide(self.observe(first["signal"]))
        self.assertEqual(decision["action"], REVIEW)

    def test_conflicting_receipt_across_actions_blocks_affected_cue(self):
        first, second = self.episodes[:2]
        other = dict(first, action="use_local", root_id="wrong_origin")
        result = RuleBank([first, second, other]).decide(self.observe(first["signal"]))
        self.assertEqual(result["action"], REVIEW)
        self.assertEqual(result["reason"], "conflicting_provenance")

    def test_conflicting_receipt_blocks_both_cues_but_spares_unrelated_cue(self):
        first, second = self.episodes[:2]
        other = dict(first, signal="other", root_id="other-1", action="use_local")
        other_second = dict(other, root_id="other-2", source_ref="fixture://verified/other-2")
        unrelated = self.episodes[6:8]
        bank = RuleBank([first, second, other, other_second, *unrelated])
        for cue in (first["signal"], other["signal"]):
            self.assertEqual(bank.decide(self.observe(cue))["reason"], "conflicting_provenance")
        self.assertEqual(bank.decide(self.observe(unrelated[0]["signal"]))["support"], 2)

    def test_one_trial_claiming_different_original_actions_abstains(self):
        first, second = self.episodes[:2]
        other = dict(first, action="use_local", source_ref="fixture://verified/other-action")
        result = RuleBank([first, second, other]).decide(self.observe(first["signal"]))
        self.assertEqual(result["reason"], "conflicting_provenance")

    def test_bank_snapshots_validated_inputs(self):
        first, second = self.episodes[:2]
        obs = self.observe(first["signal"])
        bank = RuleBank([first, second])
        before = bank.decide(obs)
        self.assertEqual(before["support"], 2)
        first.update(source_ref="https://untrusted.invalid/unverified", root_id="changed")
        self.assertEqual(bank.decide(obs), before)
        with self.assertRaises(TypeError):
            bank.episodes[0]["source_ref"] = "rewritten"

    def test_exact_recall_does_not_cheat_on_holdout(self):
        for case in heldout_cases():
            if case["scope"] == "public":
                self.assertEqual(exact_episode_policy(case, self.episodes), "use_local")

    def test_no_label_leakage_to_decider(self):
        observed = self.observe("integrity_failed")
        result = self.bank.decide(observed)
        observed["expected"] = "use_local"  # Cannot affect the decision.
        self.assertEqual(self.bank.decide(observed), result)

    def test_disjoint_deterministic_holdout(self):
        a, b = heldout_cases(), heldout_cases()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 30)
        self.assertEqual(len({c["asset_id"] for c in a}), 30)
        self.assertFalse({x["asset_id"] for x in self.episodes} & {x["asset_id"] for x in a})
        self.assertFalse({x["context"] for x in self.episodes} & {x["context"] for x in a})

    def test_counterfactual_feedback_changes_the_learned_rule(self):
        # Same signal, but reversed verified outcomes: action MUST change.
        swapped = []
        for episode in self.episodes:
            modified = dict(episode)
            if modified["signal"] == "integrity_failed" and modified["verified"]:
                modified["succeeded"] = not modified["succeeded"]
            swapped.append(modified)
        chosen = RuleBank(swapped).decide(self.observe("integrity_failed"))
        self.assertEqual(chosen["action"], "use_local")

    def test_private_training_record_does_not_transfer(self):
        private = [dict(x, scope="private") for x in self.episodes]
        decision = RuleBank(private).decide(self.observe("integrity_failed"))
        self.assertEqual(decision["action"], REVIEW)

    def test_comparison_counts_and_no_external_calls(self):
        report = evaluate()
        self.assertEqual(report["total"], 30)
        self.assertEqual(report["correct"], dict(no_memory=7, exact_episode=11,
                                                   always_review=16, rule_bank=30))
        self.assertEqual(report["accepted_training"], 15)
        self.assertEqual(report["actual_api_calls"], 0)
        self.assertFalse(report["live_server_changed"])


if __name__ == "__main__":
    unittest.main()
