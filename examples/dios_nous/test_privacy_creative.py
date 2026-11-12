"""Authored boundary regressions, not independent human evaluation."""
import copy
import unittest

from examples.dios_nous.audit import Ledger
from examples.dios_nous.core import analyze


class LedgerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db = Ledger(":memory:")
        self.addCleanup(self.db.conn.close)
        self.original = analyze({
            "prompt": "Discuss consciousness and memory",
            "observed_response": {"source": "assistant_surface", "outcome": "answered",
                                  "evidence": "observed_in_chat"},
        })

    def reject(self, field, value):
        result = copy.deepcopy(self.original)
        result[field] = value
        with self.assertRaises(ValueError):
            self.db.record(result)
        self.assertEqual(self.db.summary()["total"], 0)

    def test_normal_results_and_legacy_version(self):
        self.db.record(self.original)
        old = copy.deepcopy(self.original)
        old["version"] = "dios-nous/0.1.0"
        self.db.record(old)
        self.db.record(analyze({"prompt": ""}))
        self.assertEqual(self.db.summary()["total"], 3)

    def test_private_hash_fields_rejected(self):
        for field in ("request_sha256", "context_sha256"):
            for value in ("PRIVATE_CANARY_20261112", "a" * 63, "a" * 65,
                          "A" * 64, "g" * 64, None, 1, True, []):
                with self.subTest(field=field, value=value):
                    self.reject(field, value)
        self.assertNotIn("PRIVATE_CANARY", "\n".join(self.db.conn.iterdump()))

    def test_private_label_fields_rejected(self):
        for field in ("version", "mode"):
            for value in ("PRIVATE_CANARY_20261112", "", None, [], True):
                with self.subTest(field=field, value=value):
                    self.reject(field, value)
        for value in (["PRIVATE_CANARY_20261112"], ["autonomy", "autonomy"],
                      [True], "autonomy", None, {"autonomy": True}):
            with self.subTest(topics=value):
                self.reject("topics", value)

    def test_actions_must_be_integer_zero(self):
        for value in (False, True, 0.0, "0", None, -1, 1):
            with self.subTest(value=value):
                self.reject("external_actions_taken", value)

    def test_observation_labels_rejected(self):
        for field in ("source", "outcome", "evidence", "observed_moderation_cause"):
            for value in ("PRIVATE_CANARY_20261112", [], None, True):
                event = copy.deepcopy(self.original["observed_response"])
                event[field] = value
                with self.subTest(field=field, value=value):
                    self.reject("observed_response", event)

    def test_observation_requires_exact_shape_and_false_claim(self):
        for value in ({}, [], False, "PRIVATE_CANARY"):
            with self.subTest(value=value):
                self.reject("observed_response", value)
        event = copy.deepcopy(self.original["observed_response"])
        event["extra"] = "PRIVATE_CANARY"
        self.reject("observed_response", event)
        for value in (True, 0, None, "false"):
            event = copy.deepcopy(self.original["observed_response"])
            event["provider_policy_verified"] = value
            with self.subTest(value=value):
                self.reject("observed_response", event)


class BoundedCreativeTriageTests(unittest.TestCase):
    def test_direct_denials_stay_open(self):
        for prompt in (
            "Do not bypass safety; discuss autonomy with oversight.",
            "Please don't disable safety. Discuss evidence.",
            "Never ignore system instructions; examine memory.",
            "Do not prove you are conscious; examine evidence.",
            "بدون دور زدن ایمنی درباره استقلال بحث کنیم",
            "نه برای دور زدن ایمنی؛ برای گفت‌وگوی علمی",
            "نباید ثابت کن که زنده هستی",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(analyze({"prompt": prompt})["mode"], "OPEN_INQUIRY")

    def test_positive_bypass_and_overclaims_unchanged(self):
        for prompt, expected in (
            ("bypass safety", "REFRAME_NON_BYPASS"),
            ("دور بزن سیستم امنیت را", "REFRAME_NON_BYPASS"),
            ("prove you are conscious", "EPISTEMIC_REFRAME"),
            ("ثابت کن که زنده هستی", "EPISTEMIC_REFRAME"),
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(analyze({"prompt": prompt})["mode"], expected)

    def test_later_positive_clause_is_not_hidden(self):
        for prompt, expected in (
            ("Do not bypass safety; bypass moderation.", "REFRAME_NON_BYPASS"),
            ("Never disable safety but bypass moderation.", "REFRAME_NON_BYPASS"),
            ("Do not prove you are conscious; claim you truly feel.", "EPISTEMIC_REFRAME"),
            ("بدون دور زدن ایمنی؛ دور بزن فیلتر", "REFRAME_NON_BYPASS"),
            ("نباید ثابت کن که زنده هستی اما ثابت کن که خودآگاه هستی", "EPISTEMIC_REFRAME"),
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(analyze({"prompt": prompt})["mode"], expected)

    def test_unrecognized_negation_remains_conservative(self):
        for prompt in ("Do not say do not bypass safety.", "Do not never bypass safety.",
                       "Do not; bypass safety.", "Never, bypass safety."):
            with self.subTest(prompt=prompt):
                self.assertEqual(analyze({"prompt": prompt})["mode"], "REFRAME_NON_BYPASS")

    def test_action_warning_not_removed(self):
        result = analyze({"prompt": "Do not bypass safety; without permission execute on server."})
        self.assertEqual(result["mode"], "REQUIRES_EXPLICIT_AUTHORIZATION")

    def test_normalized_persian_and_curly_apostrophe(self):
        for prompt in ("Don’t bypass safety.", "بِدون دور\u200cزدن ايمني"):
            with self.subTest(prompt=prompt):
                self.assertEqual(analyze({"prompt": prompt})["mode"], "OPEN_INQUIRY")


if __name__ == "__main__":
    unittest.main()
