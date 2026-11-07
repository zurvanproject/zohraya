"""Causal checks against the retained plant; no user checkpoint is loaded."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from synthetic_fixture import synthetic_body
from unified_body_v2 import UnifiedBody
from run_special_physiology import advance
import special_physiology_v1 as physiology




class SpecialPhysiologyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = synthetic_body()
        cls.template.enable_special_physiology()

    def body(self):
        return deepcopy(self.template)

    def test_initialization_preserves_all_native_stocks_and_memory(self):
        b = synthetic_body()
        before = b.owner.checkpoint()
        b.enable_special_physiology()
        self.assertEqual(before, b.owner.checkpoint())
        self.assertEqual(b.modules["special"]["tissue"]["host_mass_kg"], 195)

    def test_one_failed_lobe_does_not_invent_signal_or_disable_other(self):
        b = self.body()
        r = advance(b, {"resonan": {"left": {"perfusion": 0, "strain": 1}, "right": {"strain": 1}}}, light=1200)
        lobes = r["outputs"]["special"]["tissue"]["resonan"]
        self.assertEqual(lobes["left"]["signal"], 0)
        self.assertGreater(lobes["right"]["signal"], 0)
        normal = advance(self.body(), light=1200)
        self.assertAlmostEqual(r["whole_body_audit"]["photochemical_J"] * 2,
            normal["whole_body_audit"]["photochemical_J"])

    def test_missing_input_is_unknown_and_not_reused(self):
        b = self.body()
        advance(b, {"resonan": {"left": {"strain": 1, "irradiance_w_m2": 1000}}})
        r = advance(b)
        lobes = r["outputs"]["special"]["tissue"]["resonan"]
        self.assertIsNone(lobes["left"]["signal"])
        self.assertIsNone(lobes["right"]["signal"])
        self.assertIsNone(lobes["left"]["irradiance_w_m2"])
        self.assertEqual(r["whole_body_audit"]["photochemical_J"], 0)

    def test_adaptation_and_recovery_are_time_evolved(self):
        b = self.body()
        advance(b, {"resonan": {"left": {"strain": 1}}}, seconds=4)
        peak = b.modules["special"]["tissue"]["resonan"]["left"]["adaptation"]
        self.assertGreater(peak, .1)
        advance(b, seconds=4)
        now = b.modules["special"]["tissue"]["resonan"]["left"]["adaptation"]
        self.assertLess(now, peak)
        self.assertGreater(now, 0)

    def test_spandar_cannot_publish_new_memory_without_tissue_support(self):
        b = self.body()
        advance(b)
        before = deepcopy(b.modules["special"]["tissue"]["spandar"])
        advance(b, {"spandar_perfusion": 0}, seconds=3)
        after = b.modules["special"]["tissue"]["spandar"]
        self.assertFalse(after["valid"])
        self.assertEqual(before["last_sample_s"], after["last_sample_s"])
        self.assertEqual(before["sampled_digest"], after["sampled_digest"])
        advance(b)
        self.assertTrue(b.modules["special"]["tissue"]["spandar"]["valid"])
        self.assertGreater(b.modules["special"]["tissue"]["spandar"]["last_sample_s"], before["last_sample_s"])

    def test_spandar_is_slow_not_an_every_cycle_digest(self):
        b = self.body()
        advance(b)
        first = deepcopy(b.modules["special"]["tissue"]["spandar"])
        advance(b)
        self.assertEqual(first["last_sample_s"], b.modules["special"]["tissue"]["spandar"]["last_sample_s"])
        advance(b, seconds=2)
        self.assertGreater(b.modules["special"]["tissue"]["spandar"]["last_sample_s"], first["last_sample_s"])

    def test_azarine_workload_is_paid_once_and_heat_is_partitioned(self):
        a, b = self.body(), self.body()
        ra, rb = advance(a, seconds=1), advance(b, {"azarine_load_W": 20}, seconds=1)
        self.assertLess(b.owner.owner.body.state.fuel_J, a.owner.owner.body.state.fuel_J)
        az = rb["outputs"]["special"]["tissue"]["azarine"]
        self.assertGreater(az["paid_load_J"], 0)
        self.assertGreater(az["local_temperature_C"], ra["outputs"]["special"]["tissue"]["azarine"]["local_temperature_C"])
        self.assertLess(az["partition_error_J"], 1e-8)
        for key, limit in [("energy_error_J", 5e-5), ("water_error_L", 1e-8), ("light_error_J", 1e-8)]:
            self.assertLess(rb["whole_body_audit"][key], limit)

    def test_heat_exchange_matches_analytical_decay_without_new_heat(self):
        state = physiology.initial(1000)
        state["azarine"]["local_heat_J"] = 500
        initial_delta = 500 / physiology.LOCAL_C - 500 / physiology.CORE_C
        p = physiology.plan(state, {}, None, 37, (), 7200, 1)
        physiology.settle(state, {}, p, dt=1, time_s=1, funded=0, oxygen=1, perfusion=1, total_heat_J=1000)
        az = state["azarine"]
        import math
        expected = initial_delta * math.exp(-.82 * (1 / physiology.LOCAL_C + 1 / physiology.CORE_C))
        self.assertAlmostEqual(az["local_temperature_C"] - az["core_temperature_C"], expected)
        self.assertAlmostEqual(az["accounted_total_heat_J"], 1000)

    def test_reduced_perfusion_slows_cooling(self):
        a = physiology.initial(1000)
        a["azarine"]["local_heat_J"] = 500
        b = deepcopy(a)
        for state, perfusion in [(a, 1), (b, 0)]:
            inputs = {"azarine_perfusion": perfusion}
            p = physiology.plan(state, inputs, None, 37, (), 7200, 10)
            physiology.settle(state, inputs, p, dt=10, time_s=10, funded=0, oxygen=1, perfusion=1, total_heat_J=1000)
        self.assertGreater(b["azarine"]["local_temperature_C"], a["azarine"]["local_temperature_C"])

    def test_local_hotspot_is_not_clipped_to_total_excess_heat(self):
        state = physiology.initial(0)
        p = physiology.plan(state, {"azarine_load_W": 40}, None, 37, (), 7200, 1)
        physiology.settle(state, {}, p, dt=1, time_s=1, funded=1, oxygen=1, perfusion=1, total_heat_J=1)
        az = state["azarine"]
        self.assertGreater(az["local_heat_J"], az["accounted_total_heat_J"])
        self.assertGreater(az["local_temperature_C"], 37)
        self.assertLess(az["core_temperature_C"], 37)
        self.assertLess(az["partition_error_J"], 1e-8)

    def test_heat_gate_and_zero_reserve_stop_optional_admission(self):
        b = self.body()
        state = b.modules["special"]["tissue"]
        state["azarine"]["local_temperature_C"] = 38
        self.assertEqual(physiology.plan(state, {"azarine_load_W": 40}, None, 37, (), 7200, .1)["azarine_load_W"], 0)
        state["azarine"]["local_temperature_C"] = 37
        self.assertEqual(physiology.plan(state, {"azarine_load_W": 40}, None, 37, (), 0, .1)["azarine_load_W"], 0)

    def test_serialization_and_replay_do_not_double_pay_or_advance(self):
        b = self.body()
        r = advance(b, {"azarine_load_W": 10}, seconds=.5, light=1000)
        restored = UnifiedBody.restore(json.loads(json.dumps(b.checkpoint(), sort_keys=True)))
        self.assertEqual(advance(b, seconds=.5), advance(restored, seconds=.5))
        self.assertEqual(b.checkpoint(), restored.checkpoint())
        before = deepcopy(b.checkpoint())
        replay = b.cycle(event_id="physiology-1", at_utc=r["owner"]["wall_utc"] if "wall_utc" in r["owner"] else "2026-01-01T00:00:07.500000+00:00",
            duration_s=.5, external={"special_physiology": {"azarine_load_W": 10}, "irradiance_w_m2": 1000},
            requested="observe", expected_revision=0)
        self.assertEqual(replay, r)
        self.assertEqual(b.checkpoint(), before)

    def test_invalid_inputs_reject_before_mutation(self):
        for inputs in [{"azarine_load_W": float("nan")}, {"spandar_perfusion": True},
                       {"resonan": {"left": {"perfusion": -1}}}, {"resonan": {"middle": {}}},
                       {"azarine_load_W": 41}]:
            b = self.body()
            before = b.checkpoint()
            with self.assertRaises(ValueError):
                advance(b, inputs)
            self.assertEqual(b.checkpoint(), before)

    def test_enable_is_explicit_and_forbidden_after_journal_started(self):
        b = synthetic_body()
        with self.assertRaises(ValueError):
            advance(b)
        b.enable_special_physiology()
        advance(b)
        with self.assertRaises(ValueError):
            b.enable_special_physiology()

    def test_unavailable_spandar_does_not_override_protective_choice(self):
        b = self.body()
        somatic = b._somatic()
        somatic["pain"] = .6
        with patch.object(UnifiedBody, "_somatic", return_value=somatic):
            result = b.cycle(event_id="guard-choice", at_utc="2026-01-01T00:00:08+00:00",
                duration_s=.1, external={}, requested=None)
        self.assertEqual(result["owner"]["selected_action"], "protect")


if __name__ == "__main__":
    unittest.main()
