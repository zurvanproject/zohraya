"""Pure, synthetic, no-side-effect policy tests for ATMOSPHERE COOL."""
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import atmosphere_cool as cool

NOW = datetime(2026, 11, 15, 19, tzinfo=timezone.utc)


def s(**updates):
    data = cool.demo(at=NOW)
    data.update(cpu_load_per_core=.2, duplicate_ratio_5m=.1)
    data.update(updates)
    return data


class CoolAdvisoryTests(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(cool.evaluate(s(), now=NOW, source_verified=True)["mode"], "MONITOR")

    def test_cpu_cooling(self):
        result = cool.evaluate(s(cpu_load_per_core=.81), now=NOW, source_verified=True)
        self.assertEqual(result["mode"], "COOL_ADVISED")
        self.assertIn("elevated-cpu-load", result["reasons"])

    def test_memory_cooling(self):
        self.assertEqual(cool.evaluate(s(ram_used_pct=85), now=NOW,
                                       source_verified=True)["mode"], "COOL_ADVISED")

    def test_duplicate_cooling(self):
        self.assertEqual(cool.evaluate(s(duplicate_ratio_5m=.7), now=NOW,
                                       source_verified=True)["mode"], "COOL_ADVISED")

    def test_repeated_errors_cooling(self):
        self.assertEqual(cool.evaluate(s(error_burst_5m=3), now=NOW,
                                       source_verified=True)["mode"], "COOL_ADVISED")

    def test_critical_memory_manual_review(self):
        self.assertEqual(cool.evaluate(s(ram_used_pct=94), now=NOW,
                                       source_verified=True)["mode"], "REVIEW_REQUIRED")

    def test_high_cpu_manual_review(self):
        self.assertEqual(cool.evaluate(s(cpu_load_per_core=2.1), now=NOW,
                                       source_verified=True)["mode"], "REVIEW_REQUIRED")

    def test_error_burst_manual_review(self):
        self.assertEqual(cool.evaluate(s(error_burst_5m=6), now=NOW,
                                       source_verified=True)["mode"], "REVIEW_REQUIRED")

    def test_stale_evidence_manual_review(self):
        self.assertEqual(cool.evaluate(s(evidence_age_seconds=22000), now=NOW,
                                       source_verified=True)["mode"], "REVIEW_REQUIRED")

    def test_unverified_source_never_appears_trusted(self):
        result = cool.evaluate(s(), now=NOW)
        self.assertEqual(result["mode"], "OBSERVE_ONLY")
        self.assertEqual(result["authority"], "none")

    def test_missing_sensor_observe_only(self):
        self.assertEqual(cool.evaluate(s(error_burst_5m=None), now=NOW,
                                       source_verified=True)["mode"], "OBSERVE_ONLY")

    def test_paused_is_preserved(self):
        report = cool.evaluate(s(awake_paused=True), now=NOW, source_verified=True)
        self.assertEqual(report["mode"], "OBSERVE_ONLY")
        self.assertFalse(report["allow_unpause"])

    def test_stale_sample(self):
        t = cool.iso(NOW - timedelta(minutes=6))
        report = cool.evaluate(s(sampled_at=t), now=NOW, source_verified=True)
        self.assertEqual(report["mode"], "REVIEW_REQUIRED")

    def test_future_sample(self):
        t = cool.iso(NOW + timedelta(minutes=1))
        report = cool.evaluate(s(sampled_at=t), now=NOW, source_verified=True)
        self.assertIn("clock-is-ahead", report["reasons"])

    def test_hysteresis_first_clean(self):
        report = cool.evaluate(s(), now=NOW, source_verified=True,
                               previous={"mode": "COOL_ADVISED", "healthy_streak": 0})
        self.assertEqual(report["mode"], "COOL_ADVISED")
        self.assertEqual(report["healthy_streak"], 1)

    def test_hysteresis_second_clean(self):
        report = cool.evaluate(s(), now=NOW, source_verified=True,
                               previous={"mode": "COOL_ADVISED", "healthy_streak": 1})
        self.assertEqual(report["mode"], "MONITOR")
        self.assertEqual(report["healthy_streak"], 2)

    def test_no_automatic_clear_of_review(self):
        report = cool.evaluate(s(), now=NOW, source_verified=True,
                               previous={"mode": "REVIEW_REQUIRED", "healthy_streak": 0})
        self.assertEqual(report["mode"], "REVIEW_REQUIRED")

    def test_reject_bool_as_numeric(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(cpu_load_per_core=True), now=NOW, source_verified=True)

    def test_reject_nan(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(ram_used_pct=float("nan")), now=NOW, source_verified=True)

    def test_reject_extra_credential(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(api_key="secret"), now=NOW, source_verified=True)

    def test_reject_unsupported_epoch(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(sampled_at=NOW.timestamp()), now=NOW, source_verified=True)

    def test_invalid_prev(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(), now=NOW, source_verified=True,
                          previous={"mode":"COOL_ADVISED","healthy_streak":True})

    def test_invalid_clock(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(), now=NOW.replace(tzinfo=None), source_verified=True)

    def test_review_cannot_be_downgraded_to_cooling(self):
        report = cool.evaluate(s(cpu_load_per_core=.92), now=NOW, source_verified=True,
                               previous={"mode":"REVIEW_REQUIRED", "healthy_streak":0})
        self.assertEqual(report["mode"], "REVIEW_REQUIRED")
        self.assertIn("manual-clearance-needed", report["reasons"])

    def test_nonexecuting_always(self):
        variants = [s(), s(cpu_load_per_core=9), s(duplicate_ratio_5m=.9), s(awake_paused=True)]
        for sample in variants:
            for verified in (False, True):
                result = cool.evaluate(sample, now=NOW, source_verified=verified)
                self.assertEqual(result["execution"], "NOT_RUN")
                self.assertEqual(result["model_calls"], 0)
                self.assertEqual(result["network_calls"], 0)
                self.assertEqual(result["writes"], 0)
                self.assertEqual(result["service_actions"], 0)
                self.assertFalse(result["allow_unpause"])
                self.assertFalse(result["allow_dios_mutation"])
                self.assertFalse(result["allow_bridge_command"])
                self.assertFalse(result["measures_temperature"])

    def test_deterministic(self):
        data=s(cpu_load_per_core=.9)
        before=copy.deepcopy(data)
        a=cool.evaluate(data, now=NOW, source_verified=True)
        b=cool.evaluate(data, now=NOW, source_verified=True)
        self.assertEqual(a,b)
        self.assertEqual(data,before)

    def test_demo_fixture_does_not_touch_services(self):
        with patch.object(cool.os, "system", side_effect=AssertionError("system called")):
            data=cool.demo(at=NOW)
            out=cool.evaluate(data, now=NOW, source_verified=True)
            self.assertEqual(out["mode"], "COOL_ADVISED")

    def test_host_probe_missing_research_metrics_observational(self):
        fake="MemTotal:       1000000 kB\nMemAvailable:   750000 kB\n"
        with patch.object(Path,"read_text",return_value=fake), \
             patch.object(cool.os,"getloadavg",return_value=(2.0,2.0,2.0)), \
             patch.object(cool.os,"cpu_count",return_value=4):
            sample=cool.host_probe(now=NOW)
        self.assertEqual(sample["ram_used_pct"],25.0)
        self.assertEqual(sample["cpu_load_per_core"],.5)
        self.assertEqual(cool.evaluate(sample,now=NOW,source_verified=True)["mode"],"OBSERVE_ONLY")

    def test_untrusted_payload_cannot_supply_provenance(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(source_verified=True), now=NOW, source_verified=True)

    def test_invalid_paused_type(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(awake_paused="false"), now=NOW, source_verified=True)

    def test_reject_negative_counter(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(error_burst_5m=-1), now=NOW, source_verified=True)

    def test_honest_schema(self):
        report=cool.evaluate(s(),now=NOW,source_verified=True)
        self.assertEqual(report["schema"],cool.REPORT_SCHEMA)
        self.assertEqual(len(report["sample_digest_sha256"]),64)
        self.assertEqual(report["authority"],"none")


if __name__ == "__main__":
    unittest.main()
