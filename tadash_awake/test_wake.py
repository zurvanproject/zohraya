"""Offline regression tests with synthetic inputs only."""
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from . import core

T = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)

def observation(event_id="one", topic="unknown_palm", value=0, source="tadash://fixture/a",
                confidence=.8, at=T):
    return dict(event_id=event_id, topic=topic, value=value, source_ref=source,
                confidence=confidence, observed_at=core.iso(at))

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_starts_paused(self):
        self.assertEqual(core.tick(self.root, T)["status"], "paused")
        self.assertEqual(core.status(self.root)["counts"]["ticks"], 0)

    def test_idle_and_cooldown(self):
        core.set_paused(self.root, False, T)
        self.assertEqual(core.tick(self.root, T)["status"], "idle_no_evidence")
        self.assertEqual(core.tick(self.root, T + timedelta(minutes=5))["status"], "deferred_cooldown")
        self.assertEqual(core.tick(self.root, T + timedelta(minutes=15))["status"], "idle_no_evidence")

    def test_questions_persist_and_revision_is_not_duplicate(self):
        core.ingest(self.root, [observation()], T)
        core.set_paused(self.root, False, T)
        first = core.tick(self.root, T)
        self.assertEqual(first["kind"], "independent_check")
        self.assertEqual(core.status(self.root)["counts"]["questions"], 1)
        core.ingest(self.root, [observation("two", value=1, source="tadash://fixture/b",
                                            at=T + timedelta(minutes=15))], T + timedelta(minutes=15))
        later = core.tick(self.root, T + timedelta(minutes=15))
        self.assertEqual((later["status"], later["kind"], later["revision"]),
                         ("question_revised", "temporal_change", 2))
        self.assertEqual(first["question_id"], later["question_id"])
        self.assertEqual(core.status(self.root)["counts"]["questions"], 1)
        self.assertEqual(core.tick(self.root, T + timedelta(minutes=30))["status"], "idle_no_new_evidence")

    def test_discrepancy_precedes_other_questions(self):
        core.ingest(self.root, [
            observation("a", "aaa_topic"),
            observation("b", "bbb_topic", 0),
            observation("c", "bbb_topic", 1, "tadash://fixture/b")], T)
        core.set_paused(self.root, False, T)
        self.assertEqual(core.tick(self.root, T)["topic"], "bbb_topic")

    def test_same_time_two_sources_is_contradiction(self):
        core.ingest(self.root, [
            observation("a", "time_topic", 0, "tadash://fixture/a"),
            observation("b", "time_topic", 1, "tadash://fixture/b")], T)
        core.set_paused(self.root, False, T)
        self.assertEqual(core.tick(self.root, T)["kind"], "discrepancy")

    def test_same_source_sequential_change_is_not_contradiction(self):
        a = observation("a", "time_topic", 0)
        b = observation("b", "time_topic", 1)
        a["sample_time"] = 1.6
        b["sample_time"] = 3.2
        core.ingest(self.root, [a, b], T)
        core.set_paused(self.root, False, T)
        self.assertEqual(core.tick(self.root, T)["kind"], "temporal_change")

    def test_mixed_clock_domain_needs_review(self):
        a = observation("a", "time_topic", 0)
        b = observation("b", "time_topic", 1)
        a["sample_time"] = 1.6
        core.ingest(self.root, [a, b], T)
        core.set_paused(self.root, False, T)
        self.assertEqual(core.tick(self.root, T)["kind"], "time_scope_uncertain")

    def test_invalid_sample_clock(self):
        for bad in (float("nan"), -1, "1.6", 1000001):
            item = observation()
            item["sample_time"] = bad
            with self.assertRaises(ValueError):
                core.ingest(self.root, [item], T)

    def test_event_deduplication_and_atomic_rejection(self):
        self.assertEqual(core.ingest(self.root, [observation()], T)["added"], 1)
        self.assertEqual(core.ingest(self.root, [observation()], T)["duplicate"], 1)
        with self.assertRaisesRegex(ValueError, "conflicting event"):
            core.ingest(self.root, [observation("new"), observation(value=9)], T)
        self.assertEqual(core.status(self.root)["counts"]["evidence"], 1)

    def test_evidence_validation(self):
        invalid = [observation(topic="../a"), observation(confidence=float("nan")),
                   observation(value={"private": 1}), observation(source="https://evil.test/"),
                   observation(at=T + timedelta(days=1))]
        for record in invalid:
            with self.assertRaises(ValueError):
                core.ingest(self.root, [record], T)
        self.assertEqual(core.status(self.root)["counts"]["evidence"], 0)

    def test_pause_and_clock_rollback(self):
        core.set_paused(self.root, False, T)
        core.tick(self.root, T)
        with self.assertRaisesRegex(ValueError, "clock rollback"):
            core.tick(self.root, T - timedelta(seconds=1))
        core.set_paused(self.root, True, T)
        self.assertEqual(core.tick(self.root, T + timedelta(minutes=30))["status"], "paused")
        core.set_paused(self.root, False, T + timedelta(minutes=30))
        self.assertEqual(core.tick(self.root, T + timedelta(minutes=30))["status"], "idle_no_evidence")

    def test_rolling_budget_and_restart(self):
        core.set_paused(self.root, False, T)
        for i in range(core.DAILY_LIMIT):
            self.assertEqual(core.tick(self.root, T + timedelta(minutes=15 * i))["status"], "idle_no_evidence")
        self.assertEqual(core.tick(self.root, T + timedelta(hours=24))["status"], "idle_no_evidence")

    def test_schema_lock(self):
        db = core.connect(self.root)
        db.execute("UPDATE control SET value='future' WHERE name='schema'")
        db.close()
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            core.status(self.root)


class TemporalSourceProposeRegressionTests(unittest.TestCase):
    """Synthetic fixtures only; each fixture passes the real ingestion validator."""

    @staticmethod
    def sample(event_id, value, source="tadash://fixture/a",
               sample_time=None, at=T):
        item = observation(event_id, "time_topic", value, source, at=at)
        if sample_time is not None:
            item["sample_time"] = sample_time
        return core.checked(item, T + timedelta(hours=1))

    def test_pinned_propose_baseline_matrix(self):
        a = "tadash://fixture/a"
        b = "tadash://fixture/b"
        cases = [
            ("one_source_sequential", [
                self.sample("a1", 0, a, 1),
                self.sample("a2", 1, a, 2)], ("temporal_change", 4)),
            ("two_sources_sequential", [
                self.sample("a1", 0, a, 1),
                self.sample("b1", 1, b, 2)], ("temporal_change", 4)),
            ("two_sources_simultaneous", [
                self.sample("a1", 0, a, 1),
                self.sample("b1", 1, b, 1.05)], ("discrepancy", 5)),
            ("mixed_clock_domain", [
                self.sample("a1", 0, a, 1),
                self.sample("b1", 1, b)], ("time_scope_uncertain", 5)),
            ("one_source_sequential_utc", [
                self.sample("a1", 0, a, at=T),
                self.sample("a2", 1, a, at=T + timedelta(minutes=15))],
             ("temporal_change", 4)),
            ("two_sources_sequential_utc", [
                self.sample("a1", 0, a, at=T),
                self.sample("b1", 1, b, at=T + timedelta(minutes=15))],
             ("temporal_change", 4)),
            ("stable_source_plus_second_source", [
                self.sample("a1", 0, a, 1),
                self.sample("a2", 0, a, 1.5),
                self.sample("b1", 1, b, 2)], ("temporal_change", 4)),
            ("within_source_change_plus_second_source", [
                self.sample("a1", 0, a, 1),
                self.sample("a2", 1, a, 2),
                self.sample("b1", 1, b, 3)], ("temporal_change", 4)),
            ("cross_source_equal_value", [
                self.sample("a1", 0, a, 1),
                self.sample("b1", 0, b, 1.05)], ("falsification", 1)),
            ("one_source_same_time_difference", [
                self.sample("a1", 0, a, 1),
                self.sample("a2", 1, a, 1)], ("independent_check", 3))
        ]
        ambiguous = {"two_sources_sequential", "two_sources_sequential_utc",
                     "stable_source_plus_second_source"}
        for case, events, expected in cases:
            with self.subTest(case=case):
                p = core.propose("time_topic", events)
                print("AWAKE_SYNTHETIC_REGRESSION " + core.encode({
                    "case": case, "kind": p["kind"], "rank": p["rank"],
                    "interpretation": p.get("interpretation")}), flush=True)
                self.assertEqual((p["kind"], p["rank"]), expected)
                self.assertEqual(
                    p.get("interpretation"),
                    "cross_source_temporal_ambiguity" if case in ambiguous else None)
                self.assertEqual(p["evidence_count"], len(events))
                self.assertEqual(p["topic"], "time_topic")

    def test_invalid_sample_times_rejected_by_ingestion_validator(self):
        for bad in (float("nan"), float("inf"), -1, "1", 1000001, True):
            with self.subTest(bad=repr(bad)):
                e = observation("bad", "time_topic", 0)
                e["sample_time"] = bad
                with self.assertRaises(ValueError):
                    core.checked(e, T + timedelta(hours=1))

    def test_invalid_observed_at_rejected_by_ingestion_validator(self):
        for bad in ("2026-11-13T12:00:00", "invalid-clock"):
            with self.subTest(bad=bad):
                e = observation("bad", "time_topic", 0)
                e["observed_at"] = bad
                with self.assertRaises(ValueError):
                    core.checked(e, T + timedelta(hours=1))

    def test_discrepancy_precedes_temporal_interpretation(self):
        a = "tadash://fixture/a"
        b = "tadash://fixture/b"
        events = [self.sample("a1", 0, a, 1),
                  self.sample("a2", 1, a, 2),
                  self.sample("b1", 1, b, 1.05)]
        p = core.propose("time_topic", events)
        self.assertEqual((p["kind"], p["rank"]), ("discrepancy", 5))
        self.assertNotIn("interpretation", p)

    def test_tick_persistence_and_priority_unchanged_for_ambiguous_sources(self):
        a = "tadash://fixture/a"
        b = "tadash://fixture/b"
        events = [self.sample("a1", 0, a, 1),
                  self.sample("b1", 1, b, 2)]
        proposed = core.propose("time_topic", events)
        self.assertEqual(proposed["interpretation"], "cross_source_temporal_ambiguity")
        core.ingest(self.root, events, T + timedelta(hours=1))
        core.set_paused(self.root, False, T + timedelta(hours=1))
        outcome = core.tick(self.root, T + timedelta(hours=1))
        self.assertEqual(outcome["kind"], "temporal_change")
        self.assertNotIn("interpretation", outcome)
        stored = core.status(self.root)
        self.assertEqual(stored["schema"], core.SCHEMA)
        self.assertEqual(stored["questions"][0]["kind"], "temporal_change")
        self.assertNotIn("interpretation", stored["questions"][0])

    def test_propose_order_invariant(self):
        events = [self.sample("a1", 0, sample_time=1),
                  self.sample("b1", 1, source="tadash://fixture/b", sample_time=2)]
        normal = core.propose("time_topic", events)
        reverse = core.propose("time_topic", list(reversed(events)))
        self.assertEqual(normal, reverse)

if __name__ == "__main__":
    unittest.main()
