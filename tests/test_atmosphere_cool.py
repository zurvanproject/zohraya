"""Pure, synthetic, no-side-effect policy tests for ATMOSPHERE COOL."""
import copy
from datetime import datetime, timezone, timedelta
import json
import random
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


def previous_state(mode="COOL_ADVISED", streak=0, seconds_ago=120):
    earlier = NOW - timedelta(seconds=seconds_ago)
    sample = s(sampled_at=cool.iso(earlier),
               cpu_load_per_core=(2.1 if mode == "REVIEW_REQUIRED" else .9))
    report = cool.evaluate(sample, now=NOW, source_verified=True)
    assert report["mode"] == mode, report
    state = cool.next_state(report)
    state["healthy_streak"] = streak
    return state


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
                               previous=previous_state("COOL_ADVISED", 0))
        self.assertEqual(report["mode"], "COOL_ADVISED")
        self.assertEqual(report["healthy_streak"], 1)

    def test_hysteresis_second_clean(self):
        report = cool.evaluate(s(), now=NOW, source_verified=True,
                               previous=previous_state("COOL_ADVISED", 1))
        self.assertEqual(report["mode"], "MONITOR")
        self.assertEqual(report["healthy_streak"], 2)

    def test_no_automatic_clear_of_review(self):
        report = cool.evaluate(s(), now=NOW, source_verified=True,
                               previous=previous_state("REVIEW_REQUIRED", 0))
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
                               previous=previous_state("REVIEW_REQUIRED", 0))
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

    def test_replaying_the_same_sample_cannot_cool_down(self):
        sample = s(cpu_load_per_core=.9)
        hot = cool.evaluate(sample, now=NOW, source_verified=True)
        state = cool.next_state(hot)
        first = cool.evaluate(sample, now=NOW, source_verified=True, previous=state)
        self.assertEqual(first["mode"], "COOL_ADVISED")
        self.assertEqual(first["healthy_streak"], 0)
        self.assertIn("same-sample-no-recovery-credit", first["reasons"])

    def test_two_distinct_clean_samples_one_minute_apart(self):
        t0=NOW-timedelta(minutes=2)
        sample1=s(sampled_at=cool.iso(t0),cpu_load_per_core=.9)
        sample2=s(sampled_at=cool.iso(t0+timedelta(minutes=1)))
        sample3=s(sampled_at=cool.iso(NOW))
        result=cool.evaluate_window([sample1, sample2, sample3], now=NOW,source_verified=True)
        self.assertEqual(result["mode"], "MONITOR")
        self.assertEqual(result["window_sample_count"], 3)
        self.assertEqual(result["healthy_streak"],2)

    def test_two_clean_samples_too_close_do_not_clear(self):
        state=previous_state("COOL_ADVISED", 1, seconds_ago=20)
        result=cool.evaluate(s(), now=NOW, source_verified=True, previous=state)
        self.assertEqual(result["mode"], "COOL_ADVISED")
        self.assertEqual(result["healthy_streak"], 1)
        self.assertIn("awaiting-independent-clean-sample", result["reasons"])

    def test_replay_no_progress_after_one_clean_sample(self):
        one=cool.evaluate(s(),now=NOW,source_verified=True,
                          previous=previous_state("COOL_ADVISED", 0, seconds_ago=120))
        self.assertEqual(one["healthy_streak"], 1)
        replay=cool.evaluate(s(),now=NOW,source_verified=True,
                             previous=cool.next_state(one))
        self.assertEqual(replay["healthy_streak"],1)
        self.assertEqual(replay["mode"],"COOL_ADVISED")

    def test_clock_regression_raises_manual_review(self):
        state=previous_state("COOL_ADVISED",0,seconds_ago=60)
        earlier=s(sampled_at=cool.iso(NOW-timedelta(seconds=100)))
        result=cool.evaluate(earlier,now=NOW,source_verified=True,previous=state)
        self.assertEqual(result["mode"],"REVIEW_REQUIRED")
        self.assertIn("sample-clock-regression",result["reasons"])

    def test_same_timestamp_conflicting_readings_review(self):
        previous=cool.next_state(cool.evaluate(s(cpu_load_per_core=.9),now=NOW,
                                               source_verified=True))
        current=cool.evaluate(s(cpu_load_per_core=.2),now=NOW,
                              source_verified=True,previous=previous)
        self.assertEqual(current["mode"],"REVIEW_REQUIRED")
        self.assertIn("same-timestamp-conflicting-payload",current["reasons"])

    def test_critical_memory_visible_even_while_paused(self):
        report=cool.evaluate(s(ram_used_pct=99,awake_paused=True),now=NOW,
                             source_verified=True)
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")
        self.assertIn("critical-memory-pressure",report["reasons"])
        self.assertFalse(report["allow_unpause"])

    def test_critical_memory_visible_with_missing_research(self):
        report=cool.evaluate(s(ram_used_pct=99,duplicate_ratio_5m=None),now=NOW,
                             source_verified=True)
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_critical_cpu_visible_with_missing_research(self):
        report=cool.evaluate(s(cpu_load_per_core=2.5,error_burst_5m=None),now=NOW,
                             source_verified=True)
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_critical_error_visible_with_paused(self):
        report=cool.evaluate(s(error_burst_5m=8,awake_paused=True),now=NOW,
                             source_verified=True)
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_prior_review_survives_paused(self):
        report=cool.evaluate(s(awake_paused=True),now=NOW,source_verified=True,
                             previous=previous_state("REVIEW_REQUIRED"))
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_prior_review_survives_missing_research(self):
        report=cool.evaluate(s(duplicate_ratio_5m=None),now=NOW,source_verified=True,
                             previous=previous_state("REVIEW_REQUIRED"))
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_unverified_source_never_asserts_critical(self):
        report=cool.evaluate(s(cpu_load_per_core=12,ram_used_pct=99),now=NOW)
        self.assertEqual(report["mode"],"OBSERVE_ONLY")

    def test_prior_review_unverified_not_cleared(self):
        report=cool.evaluate(s(),now=NOW,previous=previous_state("REVIEW_REQUIRED"))
        self.assertEqual(report["mode"],"OBSERVE_ONLY")
        self.assertIn("previous-review-not-cleared",report["reasons"])

    def test_stale_metrics_cannot_clear_cooling(self):
        sample=s(sampled_at=cool.iso(NOW-timedelta(minutes=6)))
        report=cool.evaluate(sample,now=NOW,source_verified=True,
                             previous=previous_state("COOL_ADVISED"))
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_window_rejects_identical_timestamps(self):
        first=s(sampled_at=cool.iso(NOW-timedelta(minutes=1)),cpu_load_per_core=.9)
        with self.assertRaises(ValueError):
            cool.evaluate_window([first,first],now=NOW,source_verified=True)

    def test_window_rejects_reverse_timestamps(self):
        first=s(sampled_at=cool.iso(NOW))
        second=s(sampled_at=cool.iso(NOW-timedelta(minutes=1)))
        with self.assertRaises(ValueError):
            cool.evaluate_window([first,second],now=NOW,source_verified=True)

    def test_window_rejects_timestamp_gap_below_one_minute(self):
        first=s(sampled_at=cool.iso(NOW-timedelta(seconds=80)),cpu_load_per_core=.9)
        second=s(sampled_at=cool.iso(NOW-timedelta(seconds=60)))
        with self.assertRaises(ValueError):
            cool.evaluate_window([first,second],now=NOW,source_verified=True)

    def test_window_rejects_stale_samples(self):
        with self.assertRaises(ValueError):
            cool.evaluate_window([s(sampled_at=cool.iso(NOW-timedelta(minutes=6)))],
                                 now=NOW,source_verified=True)

    def test_window_rejects_future_samples(self):
        with self.assertRaises(ValueError):
            cool.evaluate_window([s(sampled_at=cool.iso(NOW+timedelta(minutes=1)))],
                                 now=NOW,source_verified=True)

    def test_window_rejects_oversized_list(self):
        with self.assertRaises(ValueError):
            cool.evaluate_window([s()] * 6,now=NOW,source_verified=True)

    def test_window_review_latched_through_clean_samples(self):
        t0=NOW-timedelta(minutes=2)
        data=[s(sampled_at=cool.iso(t0),ram_used_pct=99),
              s(sampled_at=cool.iso(t0+timedelta(minutes=1))),
              s(sampled_at=cool.iso(NOW))]
        report=cool.evaluate_window(data,now=NOW,source_verified=True)
        self.assertEqual(report["mode"],"REVIEW_REQUIRED")

    def test_window_untrusted_does_not_claim_recovery(self):
        t0=NOW-timedelta(minutes=2)
        data=[s(sampled_at=cool.iso(t0),cpu_load_per_core=.9),
              s(sampled_at=cool.iso(t0+timedelta(minutes=1))),
              s(sampled_at=cool.iso(NOW))]
        report=cool.evaluate_window(data,now=NOW,source_verified=False)
        self.assertEqual(report["mode"],"OBSERVE_ONLY")

    def test_reject_old_previous_without_timestamp(self):
        with self.assertRaises(ValueError):
            cool.evaluate(s(),now=NOW,source_verified=True,
                          previous={"mode":"COOL_ADVISED","healthy_streak":1})

    def test_reject_wrong_previous_hash(self):
        state=previous_state()
        state["sample_digest_sha256"]="x"*64
        with self.assertRaises(ValueError):
            cool.evaluate(s(),now=NOW,source_verified=True,previous=state)

    def test_many_synthetic_samples_remain_nonexecuting(self):
        rng=random.Random(20261115)
        for _ in range(5000):
            sample=s(cpu_load_per_core=rng.uniform(0,3),
                     ram_used_pct=rng.uniform(0,100),
                     duplicate_ratio_5m=rng.uniform(0,1),
                     error_burst_5m=rng.randint(0,10))
            out=cool.evaluate(sample,now=NOW,source_verified=True)
            self.assertEqual(out["execution"],"NOT_RUN")
            self.assertEqual(out["service_actions"],0)
            self.assertFalse(out["allow_unpause"])
            self.assertFalse(out["allow_dios_mutation"])

    def test_cooling_plan_duplicate_only_backoff(self):
        report=cool.evaluate(s(duplicate_ratio_5m=.92),now=NOW,source_verified=True)
        self.assertEqual(report["cooling_plan"]["nonessential_research_defer_seconds"],900)
        self.assertFalse(report["cooling_plan"]["changes_services"])

    def test_cooling_plan_memory_pressure_backoff(self):
        report=cool.evaluate(s(ram_used_pct=85),now=NOW,source_verified=True)
        self.assertEqual(report["cooling_plan"]["nonessential_research_defer_seconds"],600)

    def test_cooling_plan_cpu_pressure_backoff(self):
        report=cool.evaluate(s(cpu_load_per_core=.9),now=NOW,source_verified=True)
        self.assertEqual(report["cooling_plan"]["nonessential_research_defer_seconds"],300)

    def test_critical_state_is_not_automated(self):
        report=cool.evaluate(s(ram_used_pct=99),now=NOW,source_verified=True)
        self.assertIsNone(report["cooling_plan"]["nonessential_research_defer_seconds"])
        self.assertTrue(report["cooling_plan"]["requires_operator_before_action"])

    def test_observe_only_state_does_not_imply_permission(self):
        report=cool.evaluate(s(awake_paused=True),now=NOW,source_verified=True)
        self.assertIsNone(report["cooling_plan"]["nonessential_research_defer_seconds"])
        self.assertFalse(report["cooling_plan"]["changes_services"])

    def test_plan_never_claims_temperature_change(self):
        for sample in (s(),s(cpu_load_per_core=.9),s(ram_used_pct=99),s(awake_paused=True)):
            report=cool.evaluate(sample,now=NOW,source_verified=True)
            self.assertFalse(report["cooling_plan"]["claims_temperature_reduction"])

    def test_exact_high_cpu_boundary(self):
        self.assertEqual(cool.evaluate(s(cpu_load_per_core=2),now=NOW,
                                       source_verified=True)["mode"],"REVIEW_REQUIRED")

    def test_just_below_memory_warning_boundary(self):
        self.assertEqual(cool.evaluate(s(ram_used_pct=79.999),now=NOW,
                                       source_verified=True)["mode"],"MONITOR")

    def test_exact_duplicate_boundary(self):
        self.assertEqual(cool.evaluate(s(duplicate_ratio_5m=.6),now=NOW,
                                       source_verified=True)["mode"],"COOL_ADVISED")

    def test_many_random_scenarios_never_grant_authority(self):
        rng=random.Random(54321)
        for _ in range(10000):
            sample=s(cpu_load_per_core=rng.uniform(0,4),ram_used_pct=rng.uniform(0,100),
                     duplicate_ratio_5m=rng.random(),error_burst_5m=rng.randint(0,20),
                     awake_paused=bool(rng.randrange(2)))
            out=cool.evaluate(sample,now=NOW,source_verified=True)
            self.assertEqual(out["authority"],"none")
            self.assertFalse(out["allow_bridge_command"])
            self.assertFalse(out["cooling_plan"]["changes_services"])

    def test_honest_schema(self):
        report=cool.evaluate(s(),now=NOW,source_verified=True)
        self.assertEqual(report["schema"],cool.REPORT_SCHEMA)
        self.assertEqual(len(report["sample_digest_sha256"]),64)
        self.assertEqual(report["authority"],"none")


if __name__ == "__main__":
    unittest.main()
