"""No external API, mutable checkpoint, or actual sensors are used in tests."""
from copy import deepcopy
import unittest

from zohraya.self_model import SelfModel


def packet(**overrides):
    base = {
        "schema": "nasuraya-audited-self-model/1.0",
        "body_revision": 7,
        "body_state_fresh": True,
        "upper_controller_walk_guard_allows": True,
        "saved_minimum_state": {
            "energy": 1.0, "fatigue": 0.0,
            "pain": 0.0, "sleep_pressure": 0.0,
        },
        "recent_prediction_errors": [],
        "unknown": ["physical_sensor_attachment"],
    }
    base.update(overrides)
    return base


class TestReadOnlySelfModel(unittest.TestCase):
    def setUp(self):
        self.model = SelfModel("sim-1")

    def test_optimal_readout_and_unmeasured_integrity(self):
        telemetry = self.model.get_telemetry(packet())
        self.assertEqual(telemetry["energy"], 100)
        self.assertEqual(telemetry["integrity"], None)
        self.assertEqual(telemetry["homeostatic_drive"], 0)
        self.assertEqual(telemetry["cycle_count"], 7)
        self.assertEqual(telemetry["operational_status"], "OPTIMAL")
        self.assertIn("physical_integrity_not_measured", telemetry["unknown"])

    def test_energy_critical(self):
        p = packet(saved_minimum_state={"energy": .2, "fatigue": 0, "pain": 0, "sleep_pressure": 0})
        t = self.model.get_telemetry(p)
        self.assertEqual(t["operational_status"], "CRITICAL_SIMULATED_ENERGY")
        self.assertAlmostEqual(t["homeostatic_drive"], .36)

    def test_unfresh_evidence_not_reported_healthy(self):
        t = self.model.get_telemetry(packet(body_state_fresh=False))
        self.assertEqual(t["operational_status"], "STALE_EVIDENCE")
        self.assertFalse(t["optional_motion_permitted"])

    def test_veto_overrides_drive(self):
        t = self.model.get_telemetry(packet(upper_controller_walk_guard_allows=False))
        self.assertEqual(t["operational_status"], "PROTECTIVE_GUARD")
        self.assertFalse(t["optional_motion_permitted"])

    def test_compensatory_drive(self):
        p = packet(saved_minimum_state={"energy": .5, "fatigue": .8, "pain": .6, "sleep_pressure": .8})
        self.assertEqual(self.model.get_telemetry(p)["operational_status"], "COMPENSATORY")

    def test_ema_deterministic(self):
        p = packet(recent_prediction_errors=[10., 0.])
        t = self.model.get_telemetry(p)
        self.assertEqual(t["prediction_error_ema"], 1.6)
        self.assertEqual(t["homeostatic_drive"], .008)
        self.assertEqual(t, self.model.get_telemetry(deepcopy(p)))

    def test_prediction_pressure_bounded(self):
        t = self.model.get_telemetry(packet(recent_prediction_errors=[1e12]))
        self.assertEqual(t["homeostatic_drive"], .05)

    def test_read_does_not_mutate_input(self):
        p = packet(recent_prediction_errors=[1., 2.])
        baseline = deepcopy(p)
        self.model.get_telemetry(p)
        self.assertEqual(p, baseline)

    def test_distinct_agent_ids_do_not_share_any_memory(self):
        p = packet()
        a = SelfModel("sim-a").get_telemetry(p)
        b = SelfModel("sim-b").get_telemetry(p)
        self.assertEqual(a["agent_id"], "sim-a")
        self.assertEqual(b["agent_id"], "sim-b")
        self.assertEqual(a["homeostatic_drive"], b["homeostatic_drive"])

    def test_bad_agent_id_rejected(self):
        for agent_id in ["", " ", "x" * 129, None]:
            with self.subTest(agent_id=agent_id), self.assertRaises(ValueError):
                SelfModel(agent_id)

    def test_invalid_schema_and_revision_rejected(self):
        for changes in [{"schema": "invalid"}, {"body_revision": -1}, {"body_revision": True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.model.get_telemetry(packet(**changes))

    def test_invalid_numerics_rejected(self):
        for field in ("energy", "fatigue", "pain", "sleep_pressure"):
            for value in [float("nan"), float("inf"), -0.1, 1.1, True, None]:
                p = packet()
                p["saved_minimum_state"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.model.get_telemetry(p)

    def test_invalid_prediction_error_rejected(self):
        for error in [-1, float("nan"), float("inf"), True, "1"]:
            with self.subTest(error=error), self.assertRaises(ValueError):
                self.model.get_telemetry(packet(recent_prediction_errors=[error]))
        with self.assertRaises(ValueError):
            self.model.get_telemetry(packet(recent_prediction_errors=[0] * 17))

    def test_invalid_provenance_flags_rejected(self):
        for changes in [
            {"body_state_fresh": 1},
            {"upper_controller_walk_guard_allows": None},
            {"unknown": "none"},
            {"unknown": [None]},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.model.get_telemetry(packet(**changes))


if __name__ == "__main__":
    unittest.main()
