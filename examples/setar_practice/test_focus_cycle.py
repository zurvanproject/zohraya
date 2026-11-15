"""Standalone focused integration evidence contracts, no native body needed."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy

from .focus_cycle import build_report, publish_report


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FocusCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Path(self.temp.name)
        audio = b"valid-synthetic-test-audio"
        checkpoint = b'{"total_updates":2878}\n'
        note = {"kind": "note", "event_index": 0, "sample": 100,
                "feedback_available_sample": 250, "event": {"string": 1}}
        feedback = {"kind": "feedback", "event_index": 0, "sample": 250,
                    "rendered_at_sample": 100, "measurement": {
                        "valid": True, "pitch_error_cents": 1.5,
                        "onset_error_ms": -3.0, "attack_error_percent": 2.5}}
        (self.p / "events.jsonl").write_text("\n".join(json.dumps(x) for x in (note, feedback)) + "\n")
        (self.p / "practice.wav").write_bytes(audio)
        (self.p / "checkpoint.json").write_bytes(checkpoint)
        self.receipt = {"run_id": "test-focus", "state": "completed", "checkpoint_committed": True,
                        "blockwise_clock_aligned": True, "physical_hand_control": False,
                        "sample_rate_body_coupling": False, "native_cycles_caused": 12,
                        "approved_audio_seconds": 11.2, "body_elapsed_seconds": 11.2,
                        "clock_residual_seconds": 0.0, "ten_minutes_wall_clock_verified": False,
                        "audio": {"duration_s": 11.2, "sha256": sha(audio)},
                        "checkpoint_sha256": sha(checkpoint), "note_events": 1,
                        "released_feedback": 1, "curriculum_index": 0,
                        "next_curriculum_index": 1, "total_updates": 2878,
                        "accelerated": True}
        self.save()

    def save(self):
        (self.p / "bridge_receipt.json").write_text(json.dumps(self.receipt))

    def test_report_has_verifiable_metrics_and_stages(self):
        r = build_report(self.p)
        self.assertEqual(r["setar"]["native_cycles"], 12)
        self.assertEqual(r["review"][1]["synthetic_audio_errors"]["pitch_cents_mae"], 1.5)
        self.assertEqual([x["stage"] for x in r["review"]], ["observe", "evaluate", "reflect"])
        self.assertFalse(r["controller_modified_by_review"])
        self.assertFalse(r["ritual"]["textual_completion_claimed"])
        self.assertEqual(publish_report(self.p / "focused_review.json", r), "created")
        self.assertEqual(publish_report(self.p / "focused_review.json", r), "verified_existing")
        self.assertEqual(self.receipt["total_updates"], 2878)

    def test_reject_uncommitted_deferred_and_unaligned(self):
        for patch in ({"state": "deferred"}, {"checkpoint_committed": False},
                      {"blockwise_clock_aligned": False}, {"native_cycles_caused": 11},
                      {"body_elapsed_seconds": 11.1}, {"ten_minutes_wall_clock_verified": True}):
            before = deepcopy(self.receipt)
            self.receipt.update(patch)
            self.save()
            with self.assertRaises(ValueError):
                build_report(self.p)
            self.receipt = before
        self.save()

    def test_hash_mismatch_fails_closed(self):
        (self.p / "checkpoint.json").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_report(self.p)

    def test_missing_or_early_feedback_is_not_a_success(self):
        (self.p / "events.jsonl").write_text(json.dumps({"kind": "note", "event_index": 0,
                                                         "sample": 100, "feedback_available_sample": 250,
                                                         "event": {"string": 1}}) + "\n")
        with self.assertRaises(ValueError):
            build_report(self.p)

    def test_optional_external_three_pass_audit_does_not_claim_embodiment(self):
        record = {"session_id": "rit-1", "full_passes_completed": 3, "required_full_passes": 3,
                  "session_complete_under_three_pass_rule": True,
                  "mastered": False, "vps_execution_verified": False, "status": "COMPLETED_TEXTUAL"}
        path = self.p / "audit.json"
        path.write_text(json.dumps(record))
        r = build_report(self.p, path)
        self.assertTrue(r["ritual"]["textual_completion_claimed"])
        self.assertFalse(r["ritual"]["embodied_ritual_verified"])
        record["mastered"] = True
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            build_report(self.p, path)

    def test_inconsistent_external_audit_rejected(self):
        path = self.p / "audit.json"
        path.write_text(json.dumps({"session_id": "rit-1", "full_passes_completed": 1,
            "required_full_passes": 3, "session_complete_under_three_pass_rule": True,
            "mastered": False, "vps_execution_verified": False, "status": "COMPLETED_TEXTUAL"}))
        with self.assertRaises(ValueError):
            build_report(self.p, path)

    def test_existing_report_cannot_be_silently_replaced(self):
        r = build_report(self.p)
        path = self.p / "focused_review.json"
        publish_report(path, r)
        r["server_deployed"] = True
        with self.assertRaises(ValueError):
            publish_report(path, r)


if __name__ == "__main__":
    unittest.main()
