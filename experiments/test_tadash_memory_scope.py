"""Synthetic fixtures only, not Hindsight server tests."""
import copy
import hashlib
import json
import unittest
from experiments.tadash_memory_scope import (METRICS, CONTEXT, GOAL, _scoped_tags,
                                 verify_legacy_synthetic, scope_one_synthetic_comparison,
                                 exact_recall_scope, verify_exact_recall_scope)

SOURCE = hashlib.sha256(b"fake-native-synthetic-study").hexdigest()

def fixture():
    baseline = dict(arousal=.4, pain=.1, fatigue=.1, energy=.8, hydration=.8)
    after = dict(baseline, arousal=.39)
    control = dict(baseline)
    parts = {
        "intention": {"goal": GOAL, "requested": "slow_breath", "duration_s": .1},
        "observation": {"treatment_actual": ["slow_breath"], "control_actual": ["observe"],
                        "treatment_before": baseline, "treatment_after": after, "control_after": control},
        "interpretation": {"verdict": "met", "reason": "predeclared_paired_endpoint",
                           "effects_vs_control": {k: after[k] - control[k] for k in METRICS},
                           "not_a_general_rule": True, "not_subjective_experience": True},
    }
    return {"items": [{"content": json.dumps(v), "timestamp": "unset", "context": CONTEXT,
                       "document_id": f"tadash-{SOURCE}-{k}", "metadata": {
                           "category": k, "evidence_sha256": SOURCE,
                           "synthetic": "true", "schema": "tadash-memory-export/1"},
                       "tags": ["tadash-synthetic", k]} for k,v in parts.items()]}


def mutate(batch, kind, change):
    item = next(i for i in batch["items"] if i["metadata"]["category"] == kind)
    obj = json.loads(item["content"]); change(obj); item["content"] = json.dumps(obj)


class OfflineScope(unittest.TestCase):
    def test_valid_triple_and_determinism(self):
        batch = fixture()
        self.assertEqual(verify_legacy_synthetic(batch), SOURCE)
        output = scope_one_synthetic_comparison(batch)
        self.assertEqual(output, scope_one_synthetic_comparison(fixture()))
        self.assertEqual(batch, fixture())
        self.assertEqual(len(output["items"]), 3)
        for item in output["items"]:
            self.assertEqual(item["observation_scopes"], "combined")
            self.assertEqual(item["update_mode"], "replace")
            self.assertTrue(item["document_id"].startswith("tadash-v2-"))
            self.assertEqual(item["tags"], _scoped_tags(SOURCE, item["metadata"]["category"]))

    def test_exact_recall_excludes_default_any(self):
        query = exact_recall_scope(SOURCE, "interpretation")
        self.assertEqual(query["tags_match"], "exact")
        self.assertTrue(verify_exact_recall_scope(query, SOURCE, "interpretation"))
        for bad_match in ("any", "all", "all_strict", "any_strict", None):
            corrupted = dict(query, tags_match=bad_match)
            with self.assertRaises(ValueError): verify_exact_recall_scope(corrupted, SOURCE, "interpretation")

    def test_empty_or_incomplete_tags_rejected(self):
        query = exact_recall_scope(SOURCE, "intention")
        for tags in ([], ["tadash-synthetic"], ["tadash-synthetic", "intention"],
                     ["tadash-synthetic", f"tadash-evidence:{SOURCE}", "tadash-kind:interpretation"]):
            malformed = dict(query, tags=tags)
            with self.assertRaises(ValueError): verify_exact_recall_scope(malformed, SOURCE, "intention")

    def test_freeform_recall_query_rejected(self):
        query = exact_recall_scope(SOURCE, "intention")
        with self.assertRaises(ValueError):
            verify_exact_recall_scope(dict(query, query="user personal secret"), SOURCE, "intention")

    def test_arbitrary_text_goal_rejected_even_if_key_allowed(self):
        b = fixture()
        mutate(b, "intention", lambda x: x.__setitem__("goal", "test account password is xyz"))
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_nested_personal_field_rejected(self):
        b = fixture()
        mutate(b, "observation", lambda x: x["treatment_after"].__setitem__("patient_name", "Jane Doe"))
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_nested_malformed_numeric_rejected(self):
        for val in (True, None, "0.4", float('nan'), -1):
            b = fixture()
            mutate(b, "observation", lambda x: x["treatment_before"].__setitem__("arousal", val))
            with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_forged_interpretation_rejected(self):
        b = fixture()
        mutate(b, "interpretation", lambda x: x["effects_vs_control"].__setitem__("arousal", .88))
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_missing_category_rejected(self):
        b = fixture(); b["items"].pop()
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_mixed_source_rejected(self):
        b = fixture(); b["items"][0]["metadata"]["evidence_sha256"] = '0'*64
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_native_veto_semantics(self):
        b = fixture()
        mutate(b, "observation", lambda x: x.__setitem__("treatment_actual", ["protect"]))
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)
        mutate(b, "interpretation", lambda x: x.update(verdict="inconclusive", reason="native_veto"))
        self.assertEqual(verify_legacy_synthetic(b), SOURCE)

    def test_invalid_duration_and_action_count(self):
        b = fixture()
        mutate(b, "intention", lambda x: x.__setitem__("duration_s", .15))
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)
        b = fixture()
        mutate(b, "observation", lambda x: x.__setitem__("control_actual", ["observe", "observe"]))
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_metadata_and_scope_defaults_fail_closed(self):
        b = fixture(); b["items"][0]["tags"] = []
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)
        b = fixture(); b["items"][0]["timestamp"] = "2026-11-02"
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)
        b = fixture(); b["items"][0]["metadata"]["synthetic"] = "false"
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_no_raw_or_unexpected_fields(self):
        b = fixture(); b["items"][0]["private_note"] = "secret"
        with self.assertRaises(ValueError): scope_one_synthetic_comparison(b)

    def test_source_is_not_identity_signature(self):
        b = fixture()
        b["items"][0]["metadata"]["evidence_sha256"] = "0"*64
        with self.assertRaises(ValueError): verify_legacy_synthetic(b)
        # A fully fabricated but syntactically consistent triple can pass;
        # the raw native receipt hash MUST be authenticated separately.
        spoof = fixture()
        spoof_hash = "1"*64
        for i in spoof["items"]:
            i["metadata"]["evidence_sha256"] = spoof_hash
            i["document_id"] = f"tadash-{spoof_hash}-{i['metadata']['category']}"
        self.assertEqual(verify_legacy_synthetic(spoof), spoof_hash)


if __name__ == '__main__': unittest.main()
