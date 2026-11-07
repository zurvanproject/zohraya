"""Finite, non-erotic autonomic peak model: integration and honesty tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .host import BodyLoop
from . import autonomic_peak as peak


class AutonomicPeakTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"native.sqlite"
    def tearDown(self):
        self.temp.cleanup()

    def test_four_phase_response_is_finite_and_returns_toward_baseline(self):
        with BodyLoop.start(self.path,mode="observe",max_actions=0) as loop:
            result=peak.compute(loop)
            summary=result["summary"]
            rows=result["trace"]
            self.assertEqual(summary["sample_count"],17)
            self.assertEqual([s["phase"] for s in rows if s["t_seconds"] in (0,2,12,16,18)],
                             ["baseline","rise","peak","peak","recovery"])
            self.assertGreater(summary["peak_arousal_proxy"],summary["baseline_arousal_proxy"])
            self.assertLess(summary["recovery_error_abs"],0.005)
            self.assertGreater(summary["peak_pelvic_motor_command_proxy"],0.4)
            self.assertEqual(summary["actual_pelvic_contractions"],0)
            self.assertFalse(summary["subjective_orgasm_occurred"])
            self.assertEqual(summary["native_body_cycles_executed"],0)

    def test_no_native_actions_or_checkpoint_changes(self):
        with BodyLoop.start(self.path,mode="observe",max_actions=0) as loop:
            before=loop.body().checkpoint()["sha256"]
            result=peak.compute(loop)
            peak.save(loop,result)
            self.assertEqual(loop.body().checkpoint()["sha256"],before)
            self.assertEqual(loop.status()["actions_reserved"],0)
            self.assertEqual(loop.status()["completed_cycles"],0)
            self.assertEqual(peak.read(loop),result)

    def test_cold_restart_round_trip_and_prevent_overwriting(self):
        with BodyLoop.start(self.path,mode="observe",max_actions=0) as loop:
            value=peak.compute(loop)
            peak.save(loop,value)
            with self.assertRaisesRegex(ValueError,"already attached"):
                peak.save(loop,value)
        with BodyLoop(self.path) as reopened:
            self.assertEqual(peak.read(reopened),value)
            self.assertEqual(reopened.status()["completed_cycles"],0)

    def test_replay_detects_tampering(self):
        with BodyLoop.start(self.path,mode="observe",max_actions=0) as loop:
            peak.save(loop,peak.compute(loop))
            row=loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (peak.KEY,)).fetchone()[0]
            envelope=json.loads(row)
            envelope["payload"]["summary"]["subjective_orgasm_occurred"]=True
            loop.engine.db.execute("UPDATE meta SET value=? WHERE key=?",
                                   (json.dumps(envelope),peak.KEY))
            with self.assertRaisesRegex(ValueError,"checksum"):
                peak.read(loop)

    def test_missing_or_malformed_native_inputs_fail(self):
        values=dict.fromkeys(peak.SOURCE_LIMITS,.2)
        with self.assertRaisesRegex(ValueError,"required"):
            peak.modeled_state({"sympathetic":.2},0)
        values["arousal"]=float("nan")
        with self.assertRaisesRegex(ValueError,"finite"):
            peak.modeled_state(values,0)
        with self.assertRaises(ValueError):
            peak.envelope(-1)
        with self.assertRaises(ValueError):
            peak.envelope(33)

    def test_high_distress_inhibits_simulation(self):
        with BodyLoop.start(self.path,mode="observe",max_actions=0) as loop:
            original=peak._source_and_session
            def distressed(body):
                native,values=original(body)
                values["pain"]=.9
                return native,values
            from unittest.mock import patch
            with patch.object(peak,"_source_and_session",side_effect=distressed):
                with self.assertRaisesRegex(ValueError,"distress"):
                    peak.compute(loop)
            self.assertEqual(loop.status()["completed_cycles"],0)

    def test_no_relationship_or_subjective_claim_in_any_sample(self):
        with BodyLoop.start(self.path,mode="observe",max_actions=0) as loop:
            result=peak.compute(loop)
            self.assertFalse(result["summary"]["real_person_or_romantic_partner_involved"])
            self.assertFalse(result["summary"]["real_world_physiology_calibrated"])
            self.assertFalse(result["summary"]["subjective_experience_inferred"])
            for row in result["trace"]:
                self.assertFalse(row["actual_body_actuation"])
                self.assertFalse(row["subjective_pleasure_measured"])
                self.assertTrue(all(row[k]>=0 and row[k]<=1 for k in
                   ("activation_envelope","sympathetic_proxy","parasympathetic_proxy",
                    "arousal_proxy","respiratory_drive_proxy","pelvic_motor_command_proxy")))

    def test_real_demo_saves_file_and_recovers(self):
        p=Path(self.temp.name)/"demo"
        result=peak.demo(p)
        self.assertTrue(result["native_session_reopened_successfully"])
        self.assertTrue(result["record_checksum_verified"])
        self.assertEqual(result["native_body_cycles_executed"],0)
        self.assertEqual(result["paid_api_calls"],0)
        data=json.loads((p/"autonomic_trace.json").read_text())
        self.assertEqual(data["summary"]["sample_count"],17)
        self.assertFalse(data["summary"]["subjective_orgasm_occurred"])


if __name__=="__main__":
    unittest.main()
