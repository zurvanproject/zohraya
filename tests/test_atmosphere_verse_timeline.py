"""ATMOSPHERE offline synchronized Shahnameh timeline tests."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from atmosphere_verse_timeline import SCHEMA, build_timeline, audit_timeline, dry_run
from atmosphere_policy import authorize


class VerseTimelineTests(unittest.TestCase):
    def test_complete_text_score_has_42_sync_anchors(self):
        score = build_timeline()
        self.assertEqual(score["schema"], SCHEMA)
        self.assertEqual(score["execution"], "NOT_RUN")
        self.assertEqual(score["mode"], "OFFLINE_TEXT_SCORE")
        self.assertEqual(score["phase_count"], 21)
        self.assertEqual(score["anchor_count"], 42)
        self.assertEqual([a["logical_tick"] for a in score["anchors"]], list(range(1, 43)))
        self.assertTrue(audit_timeline(score)["valid"])
        for i in range(0, len(score["anchors"]), 2):
            first, second = score["anchors"][i:i+2]
            self.assertEqual(first["beat_id"], second["beat_id"])
            self.assertEqual(first["same_tick"]["gesture"]["phase"], "BEGIN")
            self.assertEqual(second["same_tick"]["gesture"]["phase"], "RELEASE")
            self.assertIsNone(first["decision_after"])
            if second["pass"] == 3:
                self.assertIsInstance(second["decision_after"], str)
                self.assertTrue(second["decision_after"])
            else:
                self.assertIsNone(second["decision_after"])
            self.assertFalse(first["body_motion_executed"])
            self.assertFalse(first["audio_played"])

    def test_one_khan_has_six_anchors_and_3_passes(self):
        for khan in range(1, 8):
            score = build_timeline(khan)
            self.assertEqual(score["phase_count"], 3)
            self.assertEqual(score["anchor_count"], 6)
            self.assertTrue(audit_timeline(score)["valid"])
            self.assertEqual({a["khan"] for a in score["anchors"]}, {khan})
            self.assertEqual([a["pass"] for a in score["anchors"]], [1, 1, 2, 2, 3, 3])

    def test_dry_run_does_not_fake_performance(self):
        receipt = dry_run(3)
        self.assertEqual(receipt["mode"], "OFFLINE_DRY_RUN")
        self.assertTrue(receipt["audit"]["valid"])
        self.assertEqual(receipt["planned_sync_anchors"], 6)
        self.assertEqual(receipt["actual_voice_observations"], 0)
        self.assertEqual(receipt["actual_gesture_observations"], 0)
        self.assertEqual(receipt["physical_performance"], "UNVERIFIED")
        self.assertEqual(receipt["conscious_experience"], "UNVERIFIED")
        self.assertEqual(receipt["spiritual_effect"], "UNVERIFIED")

    def test_reject_changed_cues_and_false_live_claims(self):
        score = build_timeline(7)
        corrupted = copy.deepcopy(score)
        corrupted["anchors"][0]["same_tick"]["recitation"]["text"] = "متن جعلی"
        self.assertEqual(audit_timeline(corrupted)["reason"], "checksum-mismatch")
        corrupted = copy.deepcopy(score)
        corrupted["anchors"][3]["logical_tick"] = 77
        self.assertEqual(audit_timeline(corrupted)["reason"], "invalid-or-forged-anchor")
        corrupted = copy.deepcopy(score)
        corrupted["execution"] = "COMPLETE"
        self.assertEqual(audit_timeline(corrupted)["reason"], "execution-claim")
        corrupted = copy.deepcopy(score)
        corrupted["anchors"][0]["audio_played"] = True
        self.assertEqual(audit_timeline(corrupted)["reason"], "invalid-or-forged-anchor")
        corrupted = copy.deepcopy(score)
        corrupted["anchors"][0]["same_tick"].pop("gesture")
        self.assertEqual(audit_timeline(corrupted)["reason"], "missing-simultaneity")

    def test_non_authority_of_rehearsal(self):
        self.assertFalse(authorize(
            "poetic_ritual", "awake-activate", mode="bounded",
            source_verified=True, elevated_approved=True).allowed)
        self.assertFalse(authorize(
            "poetic_ritual", "memory_write", mode="bounded",
            source_verified=True, elevated_approved=True).allowed)
        score = build_timeline(3)
        for a in score["anchors"]:
            self.assertEqual(a["same_tick"]["recitation"]["mode"], "TEXT_CUE_ONLY")
            self.assertEqual(a["same_tick"]["gesture"]["mode"], "TEXT_CUE_ONLY")


if __name__ == "__main__":
    unittest.main()
