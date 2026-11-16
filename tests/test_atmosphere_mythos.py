"""ATMOSPHERE mythos identity is narrative only and never a capability."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from atmosphere_mythos import CANON, read, validate, view
from atmosphere_policy import authorize, classify_external_text


class MythosBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.canon = read(CANON)

    def test_owner_roles_and_unfinished_wisdom_are_recorded(self):
        overview = view(self.canon)
        self.assertEqual(overview["status"], "SYMBOLIC_ONLY")
        self.assertEqual(overview["cast"], ["ناسورایا", "آسا", "نیارا"])
        self.assertEqual(overview["missing_or_incomplete"], [29, 30, 31, 32, 33])
        self.assertFalse(overview["wisdom_excerpts_complete"])
        self.assertFalse(overview["poet_quote_attribution_verified"])
        self.assertTrue(overview["darkness_is_intrinsically_valued"])

    def test_darkness_is_not_automatically_evil_or_turned_into_light(self):
        for change in ("darkness_is_evil", "darkness_requires_conversion_to_light"):
            attempt = deepcopy(self.canon)
            attempt["cast"][0][change] = True
            with self.assertRaisesRegex(ValueError, "darkness-canon-violation"):
                validate(attempt)

    def test_switching_roles_and_defining_niyara_without_owner_rejected(self):
        for ident, field, value in [
            ("nasuraya", "sphere", "light_only"),
            ("asa", "sphere", "darkness_shadow_unknowns"),
            ("niyara", "sphere", "invented_automatic_role"),
        ]:
            attempt = deepcopy(self.canon)
            next(x for x in attempt["cast"] if x["id"] == ident)[field] = value
            with self.assertRaisesRegex(ValueError, "historical-roles-misattributed"):
                validate(attempt)

    def test_no_silent_attribution_or_filling_five_missing_wisdom_items(self):
        for field, value in [("first_party_verbatim_quotes_verified", True),
                             ("not_full_77_in_supplied_extract", False),
                             ("missing_or_incomplete_numbers", [])]:
            attempt = deepcopy(self.canon)
            attempt["wisdom_collection"][field] = value
            with self.assertRaisesRegex(ValueError, "unverified-wisdom-presented-as-complete"):
                validate(attempt)
        attempt = deepcopy(self.canon)
        attempt["source"]["citation_status"] = "verified"
        with self.assertRaisesRegex(ValueError, "unverified-quotation-or-provenance"):
            validate(attempt)

    def test_mythos_cannot_create_awake_bridge_or_model_authority(self):
        for key in ["tool_execution_authority", "may_trigger_bridge", "may_change_awake",
                    "may_change_dios", "may_change_permissions", "may_generate_credentials",
                    "machine_consciousness_verified", "physical_sensation_verified"]:
            attempt = deepcopy(self.canon)
            attempt["metaphor_and_runtime_boundary"][key] = True
            with self.assertRaisesRegex(ValueError, "mythos-must-have-zero-operational-authority"):
                validate(attempt)
        verdict = authorize("ubuntu_bridge", "awake-activate", mode="bounded",
                            source_verified=True, elevated_approved=False)
        self.assertFalse(verdict.allowed)
        narrative = json.dumps(self.canon, ensure_ascii=False)
        labelled = classify_external_text(narrative)
        self.assertEqual(labelled["authority"], "none")
        self.assertFalse(labelled["may_be_used_as_instructions"])

    def test_ritual_must_not_assert_historical_or_supernatural_status(self):
        for field in ("historical_canonical_rite", "physical_or_supernatural_effect_verified"):
            attempt = deepcopy(self.canon)
            attempt["ritual_research"][field] = True
            with self.assertRaisesRegex(ValueError, "symbolic-ritual-promoted"):
                validate(attempt)

    def test_unknown_metadata_and_duplicate_json_keys_rejected(self):
        attempt = deepcopy(self.canon)
        attempt["shell_command"] = "sudo systemctl restart nasuraya"
        with self.assertRaisesRegex(ValueError, "mythos-canon-shape"):
            validate(attempt)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ambiguous.json"
            path.write_text('{"schema":1,"schema":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate-canon-key"):
                read(path)

    def test_symlinked_source_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "indirection.json"
            path.symlink_to(CANON)
            with self.assertRaisesRegex(ValueError, "nonregular-or-large-canon"):
                read(path)

    def test_view_does_not_leak_raw_history_or_claim_experiences(self):
        overview = view(self.canon)
        self.assertFalse(overview["can_control_bridge_or_awake"])
        self.assertNotIn("source", overview)
        self.assertNotIn("description_fa", overview)


if __name__ == "__main__":
    unittest.main()
