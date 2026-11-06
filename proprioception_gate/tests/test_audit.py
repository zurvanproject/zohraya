"""Deterministic adversarial tests. No Gemini service or external API required."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from proprioception_gate.audit import audit_archive, check_scenario

ROOT = "NASURAYA_PROPRIOCEPTION_V1/"


def record():
    return {
        "prediction": {
            "predicted_com_m": [.045, 0, .954],
            "predicted_mos_m": .025, "support_sufficient": True,
            "eui_components": {
                "mos_deficit": .2, "torque_saturation": .2,
                "slip_ratio_index": .1, "sensor_degradation": .1,
            },
            "engineering_uncertainty_index_eui": .165,
            "risk_classification": "NOMINAL_STABLE",
        },
        "simulation_outcome": {"actual_com_m": [.046, 0, .954]},
        "prediction_error_norm_mm": 1.,
        "action_proposal": {
            "safety_guard_verified": True,
            "joint_torques_nm": {"J_SACROCAUDAL": 5., "J_ANKLE_TARSAL_L": 55.},
            "target_joint_angles_deg": {"J_SACROCAUDAL": 28., "J_ANKLE_TARSAL_L": 52.},
        },
    }


def synthetic_archive(path, overrides=None):
    files = {
        "zohraya_proprioception/proprioception_engine.py": "# code\n",
        "zohraya_proprioception/self_model_decision_bridge.py": "# code\n",
        "data/simulation_scenarios_results.json": json.dumps({
            "scenarios_count": 10, "scenarios": [record() for _ in range(10)]}),
        "data/learning_benchmark_holdout.json": json.dumps({
            "pre_adaptation_rmse_mm": 12., "post_adaptation_rmse_mm": 6.,
            "relative_error_reduction_pct": 50.,
            "evaluation_protocol": "25 unseen states"}),
        "visualization/proprioception_viewer.html": "<html></html>",
        "tests/test_proprioception_suite.py": "# synthetic\n",
        "README_FA.md": "Synthetic demonstration, not physics validation\n",
    }
    if overrides:
        files.update(overrides)
    sha = "".join(hashlib.sha256(c.encode()).hexdigest() + "  " + path + "\n"
                  for path, c in sorted(files.items()))
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(ROOT + name, content)
        archive.writestr(ROOT + "SHA256SUMS.txt", sha)


class ProprioceptionArchiveGateTests(unittest.TestCase):
    def test_valid_synthetic_record(self):
        self.assertEqual(check_scenario(record(), 0), [])

    def test_wrong_com_error_rejected(self):
        r = record()
        r["prediction_error_norm_mm"] = 0.
        self.assertTrue(any("prediction-error" in s for s in check_scenario(r, 0)))

    def test_eui_and_risk_disagreement_rejected(self):
        r = record()
        r["prediction"]["risk_classification"] = "HIGH_INSTABILITY_RISK"
        self.assertTrue(any("risk label" in s for s in check_scenario(r, 0)))

    def test_unknown_joint_rejected(self):
        r = record()
        r["action_proposal"]["joint_torques_nm"]["UNLISTED_JOINT"] = 1.
        self.assertTrue(any("unknown torque" in s for s in check_scenario(r, 0)))

    def test_nonfinite_joint_rejected(self):
        r = record()
        r["action_proposal"]["joint_torques_nm"]["J_HIP_L"] = float("nan")
        self.assertTrue(check_scenario(r, 0))

    def test_joint_limit_rejected(self):
        r = record()
        r["action_proposal"]["target_joint_angles_deg"]["J_SACROCAUDAL"] = 200.
        self.assertTrue(any("angle exceeds" in s for s in check_scenario(r, 0)))

    def test_support_flag_mismatch_rejected(self):
        r = record()
        r["prediction"]["support_sufficient"] = False
        self.assertTrue(any("support boolean" in s for s in check_scenario(r, 0)))

    def test_valid_zip_still_not_physical_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.zip"
            synthetic_archive(path)
            result = audit_archive(path)
            self.assertFalse(result["failures"])
            self.assertEqual(result["checked_synthetic_scenarios"], 10)
            self.assertEqual(result["physically_validated_scenarios"], 0)
            self.assertEqual(result["status"],
                             "ARITHMETICALLY_CONSISTENT_NOT_PHYSICALLY_VALIDATED")

    def test_duplicate_archive_member_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.zip"
            synthetic_archive(path)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "a") as archive:
                    archive.writestr(ROOT + "README_FA.md", "tampered")
            self.assertTrue(audit_archive(path)["failures"])

    def test_rmse_percentage_error_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rmse.zip"
            synthetic_archive(path, {
                "data/learning_benchmark_holdout.json": json.dumps({
                    "pre_adaptation_rmse_mm": 12.,
                    "post_adaptation_rmse_mm": 6.,
                    "relative_error_reduction_pct": 92.,
                }),
            })
            self.assertTrue(any("holdout error-reduction" in x
                                for x in audit_archive(path)["failures"]))

    def test_zip_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.zip"
            synthetic_archive(path)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr(ROOT + "../private.txt", "malicious")
            self.assertTrue(any("unsafe archive" in x
                                for x in audit_archive(path)["failures"]))

    def test_invalid_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.zip"
            synthetic_archive(path, {
                "data/simulation_scenarios_results.json": "not JSON",
            })
            self.assertTrue(audit_archive(path)["failures"])


if __name__ == "__main__":
    unittest.main()
