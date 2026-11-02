"""Contract tests use explicit doubles, not claims of native execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from .core import (METRICS, digest, encode, hindsight_items, inspect_mjcf,
                   motion_readiness, rehearsal_gate, review_pair, validate_hindsight_export)


def pair():
    state = dict(arousal=.4, pain=.1, fatigue=.1, energy=.8, hydration=.8)
    base = dict(synthetic=True, status="completed", duration_s=.1,
                initial_checkpoint_sha256=digest(state), before=state, after=state.copy())
    t = dict(copy.deepcopy(base), id="t", requested="slow_breath", actual_actions=["slow_breath"])
    c = dict(copy.deepcopy(base), id="c", requested="observe", actual_actions=["observe"])
    t["after"]["arousal"] = .39
    return t, c


class Contracts(unittest.TestCase):
    def test_effect_not_dispatch(self):
        t, c = pair(); t["after"]["arousal"] = .5
        self.assertEqual(review_pair(t, c)["verdict"], "not_met")

    def test_paired_improvement(self):
        self.assertEqual(review_pair(*pair())["verdict"], "met")

    def test_natural_decline_is_not_treatment_effect(self):
        t, c = pair(); c["after"]["arousal"] = .38
        self.assertEqual(review_pair(t, c)["verdict"], "not_met")

    def test_veto_is_inconclusive(self):
        t, c = pair(); t["actual_actions"] = ["protect"]
        self.assertEqual(review_pair(t, c)["verdict"], "inconclusive")

    def test_adverse_proxy(self):
        t, c = pair(); t["after"]["pain"] = .2
        self.assertEqual(review_pair(t, c)["verdict"], "not_met")

    def test_unmatched_initial_state(self):
        t, c = pair(); c["initial_checkpoint_sha256"] = "a" * 64
        with self.assertRaises(ValueError): review_pair(t, c)

    def test_unmatched_duration(self):
        t, c = pair(); c["duration_s"] = .2; c["actual_actions"] *= 2
        with self.assertRaises(ValueError): review_pair(t, c)

    def test_unknown_execution(self):
        t, c = pair(); t["status"] = "unknown"
        with self.assertRaises(ValueError): review_pair(t, c)

    def test_nonfinite(self):
        t, c = pair(); t["after"]["arousal"] = float("nan")
        with self.assertRaises(ValueError): review_pair(t, c)

    def test_real_data_not_exported(self):
        t, c = pair(); t["synthetic"] = False
        with self.assertRaises(ValueError): review_pair(t, c)

    def test_memory_is_three_distinct_documents(self):
        t, c = pair(); data = hindsight_items(t, c, review_pair(t, c))
        self.assertEqual(len({i["document_id"] for i in data["items"]}), 3)
        self.assertEqual({i["metadata"]["category"] for i in data["items"]},
                         {"intention", "observation", "interpretation"})
        self.assertTrue(all(i["timestamp"] == "unset" for i in data["items"]))

    def test_export_deterministic_and_allowlisted(self):
        t, c = pair(); r = review_pair(t, c)
        expected = hindsight_items(t, c, r)
        t["private_note"] = "SECRET_SHOULD_NOT_BE_EXPORTED"
        # Extra data changes source digest, so the prior review is rejected.
        with self.assertRaises(ValueError): hindsight_items(t, c, r)
        actual = hindsight_items(t, c, review_pair(t, c))
        self.assertNotIn("SECRET_SHOULD_NOT_BE_EXPORTED", encode(actual))
        self.assertEqual(expected, hindsight_items(*pair(), review_pair(*pair())))

    def test_review_tampering(self):
        t, c = pair(); r = review_pair(t, c); r["verdict"] = "not_met"
        with self.assertRaises(ValueError): hindsight_items(t, c, r)

    def test_fractional_native_tick_rejected(self):
        t, c = pair()
        t["duration_s"] = c["duration_s"] = .15
        t["actual_actions"] *= 2
        c["actual_actions"] *= 2
        with self.assertRaisesRegex(ValueError, "align"):
            review_pair(t, c)

    def test_unsupported_short_duration_rejected(self):
        t, c = pair()
        t["duration_s"] = c["duration_s"] = .09
        with self.assertRaises(ValueError):
            review_pair(t, c)

    def test_valid_two_ticks(self):
        t, c = pair()
        t["duration_s"] = c["duration_s"] = .2
        t["actual_actions"] *= 2
        c["actual_actions"] *= 2
        self.assertEqual(review_pair(t, c)["verdict"], "met")

    def test_valid_float_0_3_duration(self):
        t, c = pair()
        t["duration_s"] = c["duration_s"] = .1 + .2
        t["actual_actions"] *= 3
        c["actual_actions"] *= 3
        self.assertEqual(review_pair(t, c)["verdict"], "met")

    def test_hindsight_offline_contract(self):
        t, c = pair()
        batch = hindsight_items(t, c, review_pair(t, c))
        self.assertEqual(validate_hindsight_export(batch), 3)

    def test_hindsight_duplicate_rejected(self):
        t, c = pair()
        batch = hindsight_items(t, c, review_pair(t, c))
        batch["items"][1] = copy.deepcopy(batch["items"][0])
        with self.assertRaises(ValueError):
            validate_hindsight_export(batch)

    def test_hindsight_personal_field_rejected(self):
        t, c = pair()
        batch = hindsight_items(t, c, review_pair(t, c))
        obj = json.loads(batch["items"][0]["content"])
        obj["personal_secret"] = "not allowed"
        batch["items"][0]["content"] = json.dumps(obj)
        with self.assertRaises(ValueError):
            validate_hindsight_export(batch)

    def test_hindsight_bad_timestamp_rejected(self):
        t, c = pair()
        batch = hindsight_items(t, c, review_pair(t, c))
        batch["items"][0]["timestamp"] = "2026-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            validate_hindsight_export(batch)

    def test_hindsight_metadata_wrong_type_rejected(self):
        t, c = pair()
        batch = hindsight_items(t, c, review_pair(t, c))
        batch["items"][0]["metadata"]["synthetic"] = True
        with self.assertRaises(ValueError):
            validate_hindsight_export(batch)

    def test_bad_model_blocked(self):
        p = [[.9] * 5]; y = [[.5] * 5]; b = [[.49] * 5]
        r = rehearsal_gate(p, y, b, ["train"], ["eval"])
        self.assertFalse(r["rollout_authorized"])
        self.assertFalse(r["provisionally_better"])

    def test_good_pilot_still_not_authorization(self):
        r = rehearsal_gate([[.5]*5], [[.5]*5], [[.4]*5], ["train"], ["eval"])
        self.assertTrue(r["provisionally_better"])
        self.assertFalse(r["rollout_authorized"])

    def test_leakage_rejected(self):
        with self.assertRaises(ValueError):
            rehearsal_gate([[.5]*5], [[.5]*5], [[.4]*5], ["same"], ["same"])

    def test_duplicate_evaluation_rejected(self):
        with self.assertRaises(ValueError):
            rehearsal_gate([[.5]*5]*2, [[.5]*5]*2, [[.4]*5]*2, ["train"], ["x", "x"])

    def test_missing_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            rehearsal_gate([[.5]], [[.5]], [[.4]], ["train"], ["eval"])

    def test_mjcf_audit_not_compilation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"atlas.xml"
            p.write_text('<mujoco><worldbody><body><inertial mass="78"/></body></worldbody></mujoco>')
            r = inspect_mjcf(p)
            self.assertEqual(r["explicit_inertial_mass_sum_kg"], 78)
            self.assertIsNone(r["compiled_total_mass_kg"])
            self.assertFalse(r["compiled"])

    def test_xml_entities_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"x.xml"; p.write_text('<!DOCTYPE x><mujoco/>')
            with self.assertRaises(ValueError): inspect_mjcf(p)

    def test_missing_assets_are_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(motion_readiness(Path(d))["status"],
                             "blocked_missing_atlas_xml_on_base")

    def test_boolean_metric_rejected(self):
        t, c = pair(); t["after"]["arousal"] = True
        with self.assertRaises(ValueError): review_pair(t, c)


if __name__ == '__main__': unittest.main()
