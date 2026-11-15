"""End-to-end source-scoped tests: COOL in original Awake package."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from . import cool_policy, cool_bridge, core

T = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def machine(**updates):
    x = cool_policy.demo(at=T)
    x.update(cpu_load_per_core=.12, ram_used_pct=30.0,
             error_burst_5m=None, duplicate_ratio_5m=None,
             evidence_age_seconds=None, awake_paused=None)
    x.update(updates)
    return x


def fixture(at=T):
    return dict(event_id="evt1", topic="sensory_load", value=.5,
                source_ref="tadash://fixture/a",
                confidence=.9, observed_at=core.iso(at))


class CoreCoolingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        db = core.connect(self.root)
        db.close()

    def inspect(self, **kw):
        return cool_bridge.observe(self.root, now=T,
                                   trusted_local_source=True,
                                   resource_sample=machine(), **kw)

    def test_no_writes_and_operator_authority(self):
        before = core.status(self.root)["counts"]
        r = self.inspect()
        self.assertEqual(before, core.status(self.root)["counts"])
        self.assertEqual(r["mode"], "OBSERVE_ONLY")
        self.assertTrue(r["operator_controls_actions"])
        self.assertEqual(r["execution"], "NOT_RUN")
        self.assertEqual(r["service_actions"], 0)
        self.assertEqual(r["dios_writes"], 0)

    def test_paused_is_not_resumed(self):
        r = self.inspect()
        self.assertTrue(r["awake_paused"])
        self.assertFalse(r["advisory"]["allow_unpause"])
        self.assertTrue(core.status(self.root)["paused"])

    def test_critical_memory_reports_while_paused(self):
        r = cool_bridge.observe(self.root, now=T, trusted_local_source=True,
                                resource_sample=machine(ram_used_pct=96))
        self.assertEqual(r["mode"], "REVIEW_REQUIRED")
        self.assertIn("critical-memory-pressure", r["advisory"]["reasons"])
        self.assertTrue(core.status(self.root)["paused"])

    def test_critical_cpu_does_not_mutate_dios(self):
        r = cool_bridge.observe(self.root, now=T, trusted_local_source=True,
                                resource_sample=machine(cpu_load_per_core=4))
        self.assertEqual(r["mode"], "REVIEW_REQUIRED")
        self.assertFalse(r["advisory"]["allow_dios_mutation"])
        self.assertFalse(r["advisory"]["allow_bridge_command"])

    def test_missing_root_does_not_initialize_memory(self):
        empty = self.root / "missing"
        with self.assertRaisesRegex(ValueError, "database-absent"):
            cool_bridge.observe(empty, now=T, resource_sample=machine())
        self.assertFalse(empty.exists())

    def test_no_error_metric_is_not_fabricated(self):
        core.ingest(self.root, [fixture()], now=T)
        r = self.inspect()
        self.assertIn("error_burst_5m", r["missing_metrics"])
        self.assertEqual(r["mode"], "OBSERVE_ONLY")

    def test_duplicate_pressure_from_real_awake_ledger(self):
        core.ingest(self.root, [fixture()], now=T)
        core.ingest(self.root, [fixture()], now=T)
        core.ingest(self.root, [fixture()], now=T)
        core.set_paused(self.root, False, T)
        r = self.inspect(verified_error_count_5m=0)
        self.assertEqual(r["mode"], "COOL_ADVISED")
        self.assertIn("repeated-no-new-evidence", r["advisory"]["reasons"])
        self.assertEqual(r["advisory"]["cooling_plan"]["nonessential_research_defer_seconds"], 900)

    def test_stale_evidence_not_hidden_by_unknown_errors(self):
        core.ingest(self.root, [fixture(T - timedelta(hours=8))], now=T)
        core.set_paused(self.root, False, T)
        r = self.inspect()
        self.assertEqual(r["mode"], "REVIEW_REQUIRED")
        self.assertIn("research-evidence-too-old", r["advisory"]["reasons"])

    def test_bad_schema_fails_closed(self):
        db = core.connect(self.root)
        db.execute("UPDATE control SET value='other' WHERE name='schema'")
        db.close()
        with self.assertRaisesRegex(ValueError, "awake-control-invalid"):
            self.inspect()

    def test_bad_resource_clock_rejected(self):
        with self.assertRaisesRegex(ValueError, "host-sample-time-mismatch"):
            cool_bridge.observe(self.root, now=T,
                                resource_sample=machine(sampled_at="2026-11-15T12:00:00Z"))

    def test_untrusted_source_cannot_gain_permission(self):
        r = cool_bridge.observe(self.root, now=T, trusted_local_source=False,
                                resource_sample=machine(ram_used_pct=96))
        self.assertEqual(r["mode"], "OBSERVE_ONLY")
        self.assertEqual(r["authority"], "none")

    def test_cli_does_not_expose_service_commands(self):
        # No command in COOL can invoke service, DIOS or Bridge actions.
        r = self.inspect(verified_error_count_5m=0)
        self.assertFalse(r["advisory"]["allow_unpause"])
        self.assertFalse(r["advisory"]["allow_bridge_command"])
        self.assertFalse(r["advisory"]["allow_dios_mutation"])


if __name__ == "__main__":
    unittest.main()
