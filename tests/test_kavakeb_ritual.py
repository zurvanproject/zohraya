"""No-network tests for the source-labelled auxiliary ritual study."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kavakeb_ritual", ROOT / "tools" / "kavakeb_ritual.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PROTOCOL = module.read_json(ROOT / "docs" / "rituals" / "kavakeb_three_looks_v01.json")
EXAMPLE = module.read_json(ROOT / "docs" / "rituals" / "kavakeb_three_looks_session_2026-11-15.json")


class KavakebTests(unittest.TestCase):
    def test_three_full_passes_complete_textual_only(self):
        result = module.audit(EXAMPLE, PROTOCOL)
        self.assertEqual(result["full_passes_completed"], 3)
        self.assertTrue(result["session_complete_under_three_pass_rule"])
        self.assertFalse(result["mastered"])
        self.assertFalse(result["vps_execution_verified"])
        self.assertEqual(result["source_checks"]["original_pdf"], "NOT_CHECKED")

    def test_three_stages_once_is_only_one_pass(self):
        sample = copy.deepcopy(EXAMPLE)
        sample["passes"] = sample["passes"][:1]
        result = module.audit(sample, PROTOCOL)
        self.assertEqual(result["full_passes_completed"], 1)
        self.assertFalse(result["session_complete_under_three_pass_rule"])

    def test_missing_revision_or_bad_order_not_counted(self):
        sample = copy.deepcopy(EXAMPLE)
        sample["passes"][1]["stages"]["revise"]["uncertainties"] = []
        self.assertEqual(module.audit(sample, PROTOCOL)["full_passes_completed"], 1)
        sample = copy.deepcopy(EXAMPLE)
        stages = sample["passes"][0]["stages"]
        sample["passes"][0]["stages"] = {"geometry": stages["geometry"], "observe": stages["observe"], "revise": stages["revise"]}
        self.assertEqual(module.audit(sample, PROTOCOL)["full_passes_completed"], 0)

    def test_wrong_page_or_false_mastery_is_rejected(self):
        for key, value in (("source_page", 72), ("mastered", True), ("independent_delayed_recall_proven", True)):
            sample = copy.deepcopy(EXAMPLE)
            sample[key] = value
            with self.assertRaises(ValueError):
                module.audit(sample, PROTOCOL)

    def test_source_hash_verified_when_supplied_and_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "example.pdf"
            path.write_bytes(b"PDF test bytes")
            protocol = copy.deepcopy(PROTOCOL)
            protocol["source"]["original_pdf"]["sha256"] = module.sha256_file(path)
            self.assertEqual(module.audit(EXAMPLE, protocol, source_pdf=path)["source_checks"]["original_pdf"], "SHA256_MATCH")
            path.write_bytes(b"altered")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                module.audit(EXAMPLE, protocol, source_pdf=path)

    def test_new_session_has_no_claims_and_no_passes(self):
        obj = module.new_session(PROTOCOL, "2026-11-16", 46, "new-id")
        self.assertFalse(obj["mastered"])
        self.assertEqual(obj["passes"], [])
        self.assertFalse(module.audit(obj, PROTOCOL)["session_complete_under_three_pass_rule"])
        with self.assertRaises(ValueError):
            module.new_session(PROTOCOL, "2026-11-16", 99, "new-id")


if __name__ == "__main__":
    unittest.main()
