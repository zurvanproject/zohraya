"""Offline integration regressions: old native replay is not silently rescaled."""
from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import tail_foot_bridge as bridge


class TailFootIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=bridge.load_profile()

    def test_new_design_is_explicitly_not_legacy_body(self):
        c=self.profile["character"]
        n=self.profile["native_source_contract"]
        self.assertEqual((c["height_m"],c["mass_kg"],c["tail_length_m"]), (1.7,78,.85))
        self.assertEqual((n["old_reference_height_m"],
                          n["old_reference_mass_kg"],
                          n["old_reference_tail_length_m"]),(2.5,195,1.2))
        self.assertTrue(c["digitigrade"])
        self.assertEqual(c["toes_per_foot"],3)

    def test_previous_v01_pitch_numbers_are_reproducible_under_actual_assumed_limits(self):
        x=bridge.pitch_trial(self.profile)
        self.assertAlmostEqual(x["human_tailless_pitch_deg"],4.77464829275686,places=8)
        self.assertAlmostEqual(x["digitigrade_passive_tail_pitch_deg"],4.50350005997896,places=8)
        self.assertAlmostEqual(x["digitigrade_active_tail_pitch_deg"],0.5989655079772023,places=8)
        self.assertAlmostEqual(x["tail_peak_root_torque_Nm"],16.142010483620933,places=8)
        self.assertFalse(x["tail_sweep_limited_by_assumed_actuator"])
        self.assertLessEqual(x["tail_peak_root_torque_Nm"],
                             self.profile["motion"]["tail_root_torque_limit_assumed_Nm"])
        self.assertLessEqual(x["tail_peak_speed_rad_s"],
                             self.profile["motion"]["tail_speed_limit_assumed_rad_s"])

    def test_if_actuator_weaker_pitch_recovery_is_safely_clamped(self):
        p=deepcopy(self.profile)
        p["motion"]["tail_root_torque_limit_assumed_Nm"]=1.5
        p["motion"]["tail_speed_limit_assumed_rad_s"]=.5
        x=bridge.pitch_trial(p)
        self.assertTrue(x["tail_sweep_limited_by_assumed_actuator"])
        self.assertLessEqual(x["tail_peak_root_torque_Nm"],1.5+1e-9)
        self.assertLessEqual(x["tail_peak_speed_rad_s"],.5+1e-9)
        self.assertGreater(x["digitigrade_active_tail_pitch_deg"],.5989655)

    def test_convex_hull_not_rectangle_and_tail_moves_com_with_bounded_lever(self):
        x=bridge.footing_trial(self.profile)
        self.assertEqual(len(x["foot_polygon_centres_xy_m"]),4)
        self.assertAlmostEqual(x["digitigrade_signed_contact_centre_margin_m"],
                               .022411397951103893,places=10)
        self.assertAlmostEqual(x["human_rectangular_lateral_margin_m"],.0225,places=10)
        self.assertGreater(x["with_tail_lateral_shift_margin_m"],
                           x["digitigrade_signed_contact_centre_margin_m"])
        self.assertLessEqual(x["required_tail_lateral_sweep_deg"],55+1e-8)
        # Forefoot shape matters more than declared toe spread in an actual support hull.
        start=bridge.footing_trial(self.profile,com_x=0,com_y=0)
        self.assertLess(start["digitigrade_signed_contact_centre_margin_m"],.145/2)
        outside=bridge.footing_trial(self.profile,com_x=.08,com_y=.05)
        self.assertLess(outside["digitigrade_signed_contact_centre_margin_m"],0)
        self.assertEqual(bridge.coordination_advisory(
            self.profile,com_xy=[.08,.05])["foot_action_recommendation"],
            "hold_and_reassess")

    def test_landing_matches_old_analytical_assumption_but_is_not_native_result(self):
        l=bridge.landing_trial(self.profile)
        self.assertAlmostEqual(l["human"]["peak_spring_force_N"],4171.658009968654,places=6)
        self.assertAlmostEqual(l["digitigrade"]["peak_spring_force_N"],3597.67890245345,places=6)
        self.assertGreater(l["digitigrade"]["compression_m"],l["human"]["compression_m"])
        self.assertTrue(l["unvalidated_equivalent_linear_spring_only"])

    def test_native_legacy_mirror_is_really_read_and_morphology_checked(self):
        old=bridge.observe_legacy_native(self.profile)
        self.assertEqual(old["legacy_mass_kg"],195)
        self.assertEqual(old["legacy_tail_length_m"],1.2)
        self.assertEqual(old["native_contact_patch_count"],4)
        self.assertEqual(sum(v["frames"] for v in old["scenarios"].values()),24)
        self.assertGreater(old["scenarios"]["normal"]["native_actions"]["walk"],0)
        self.assertGreater(old["scenarios"]["sleep"]["native_actions"]["protect"],0)
        self.assertTrue(old["not_rescaled_to_new_body"])

    def test_change_to_old_native_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst=Path(tmp)
            paths=[self.profile["native_source_contract"][k] for k in (
                "contact_design_path","mirror_frames_path","phenotype_path")]
            paths.append("runtimes/tadash_body/PUBLIC_FILES_SHA256.json")
            for path in paths:
                target=dst/path
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((bridge.ROOT/path).read_bytes())
            with patch.object(bridge,"ROOT",dst):
                self.assertEqual(bridge.observe_legacy_native(self.profile)["legacy_mass_kg"],195)
                contact=dst/paths[0]
                content=json.loads(contact.read_text())
                content["tail_length_m"]=.85
                contact.write_text(json.dumps(content))
                with self.assertRaisesRegex(ValueError,"native design"):
                    bridge.observe_legacy_native(self.profile)

    def test_fresh_native_export_override_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            source=bridge.ROOT/"examples/nasuraya_body_mirror/frames.json"
            mirror=Path(temp)/"fresh-native.json"
            mirror.write_bytes(source.read_bytes())
            out=bridge.report(self.profile, native_mirror=mirror)
            self.assertEqual(out["native_V06_replay_observed_separately"]["source_hashes"]
                             ["V06_replay_sha256"],bridge._sha_file(mirror))
            self.assertEqual(out["new_profile_mass_kg"],78)
            self.assertEqual(out["native_V06_replay_observed_separately"]["legacy_mass_kg"],195)
            payload=json.loads(mirror.read_text())
            payload["scenarios"]["sleep"]["frames"][0]["actual"]="fabricated"
            mirror.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "native action"):
                bridge.report(self.profile, native_mirror=mirror)

    def test_profile_tampering_with_toes_mass_nan_and_stiffness_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for key,change in [
                ("toes",lambda p:p["character"].update(toes_per_foot=4)),
                ("mass",lambda p:p["character"].update(mass_kg=195)),
                ("nan",lambda p:p["motion"].update(body_pitch_inertia_assumed_kg_m2=float("nan"))),
                ("width",lambda p:p["geometry"].update(foot_support_width_m=.3)),
            ]:
                with self.subTest(case=key):
                    p=deepcopy(self.profile);change(p)
                    path=Path(tmp)/(key+".json")
                    path.write_text(json.dumps(p))
                    with self.assertRaises(ValueError):
                        bridge.load_profile(path)

    def test_report_no_native_new_body_claim_and_sensitivity_ready(self):
        r=bridge.report(self.profile)
        self.assertFalse(r["native_170cm_simulation_executed"])
        self.assertFalse(r["existing_native_controller_modified"])
        self.assertEqual(r["paid_api_calls"],0)
        self.assertEqual(len(r["tail_mass_sensitivity"]),5)
        self.assertEqual(len(r["foot_offset_sensitivity"]),5)
        self.assertEqual(len(r["landing_sensitivity"]),3)
        self.assertTrue(r["coordination_advice"]["safety_veto_unchanged"])
        self.assertFalse(r["coordination_advice"]["native_action_authorized"])

    def test_generated_json_and_trajectory_are_local_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"out"
            original=bridge._sha_file(
                bridge.ROOT/"runtimes/tadash_body/phenotype_v1.json")
            x=bridge.save(path)
            self.assertEqual(x["schema"],"nasuraya-tail-foot-motion-native-mirror-bridge/1")
            data=json.loads((path/"report.json").read_text())
            self.assertEqual(data,x)
            with (path/"tail_pitch.csv").open() as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),101)
            self.assertAlmostEqual(float(rows[-1]["tail_active_deg"]),
                                   x["analytical_pitch"]["digitigrade_active_tail_pitch_deg"])
            self.assertEqual(original,bridge._sha_file(
                bridge.ROOT/"runtimes/tadash_body/phenotype_v1.json"))
            with self.assertRaises(FileExistsError):
                bridge.save(path)


if __name__ == "__main__":
    unittest.main()
