"""Local synthetic tests. No production data, services, model or VPS access."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import nasu_live_integration as live
from tools import nasuraya_offline_continuity as continuity

NOW = dt.datetime(2026, 11, 19, 5, 15, tzinfo=dt.timezone.utc)
SECRET = "PRIVATE_MODEL_TEXT_AND_CREDENTIAL_SENTINEL_NEVER_COPY"


class LiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "source-home"
        self.home.mkdir()
        self.state = self.root / "new-integration"
        patch = mock.patch.object(live.os, "geteuid", return_value=1000)
        patch.start()
        self.addCleanup(patch.stop)

    def run_cycle(self, now=NOW):
        return live.run(home=self.home, state=self.state, now=now)

    def database(self):
        return self.state / live.DATABASE

    def fingerprint(self):
        return hashlib.sha256(self.database().read_bytes()).hexdigest()

    def payloads(self):
        with sqlite3.connect(self.database().as_uri() + "?mode=ro", uri=True) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM cycles ORDER BY hour")]

    def continuity_fixture(self):
        db = continuity.open_db(self.home / "continuity")
        try:
            hour = NOW.strftime("%Y-%m-%dT%H:00Z")
            stamp = NOW.isoformat()
            raw = json.dumps({"private": SECRET})
            digest = continuity.digest(continuity.ZERO, hour, stamp, raw)
            db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) VALUES(?,?,?,?,?)",
                       (hour, stamp, raw, continuity.ZERO, digest))
        finally:
            db.close()
        return self.home / "continuity/continuity.sqlite3"

    def healthy_snapshot(self):
        # Authored in a test only; production never seeds any of these sources.
        return {
            "schema": live.hub.SCHEMA, "execution": "OFFLINE_READ_ONLY",
            "generated_at_utc": NOW.isoformat(), "private": SECRET,
            "components": {
                "continuity": {"status": "verified_history", "records": 1,
                               "last_hour": "2026-11-19T05:00Z", "raw": SECRET},
                "frontier": {"status": "verified_history", "days": 1, "question": SECRET},
                "cognition": {"status": "verified_history", "completed": 1, "incomplete": 0,
                              "proposal": SECRET, "latest": {"slot": "2026-11-19T00",
                              "topic": "continuity", "model_status": "UNVERIFIED_DRAFT",
                              "private": SECRET}},
                "feedback": {"status": "verified_history", "completed": 1, "reserved": 0,
                             "comparable": 0, "baseline_correct": 0, "coached_correct": 0},
                "awake": {"status": "structural_only", "paused": False,
                          "counts": {"evidence": 1, "questions": 1, "ticks": 1, "ledger": 1},
                          "events": SECRET},
            },
        }

    def test_missing_sources_are_recorded_without_creating_them(self):
        before = list(self.home.rglob("*"))
        with mock.patch.object(live.planner, "local_question", side_effect=AssertionError("No model")), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("No network")), \
             mock.patch("subprocess.run", side_effect=AssertionError("No shell")):
            result = self.run_cycle()
        self.assertEqual(before, list(self.home.rglob("*")))
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["latest"]["experiment"], "missing_source")
        self.assertFalse(result["latest"]["local_checks_passed"])
        self.assertEqual(set(result["latest"]["states"].values()), {"missing"})
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["external_actions_taken"], 0)

    def test_real_reader_observation_is_persisted_but_private_rows_are_not(self):
        source = self.continuity_fixture()
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        result = self.run_cycle()
        self.assertEqual(result["latest"]["states"]["continuity"], "verified_history")
        self.assertEqual(self.payloads()[0]["components"]["continuity"]["records"], 1)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(SECRET.encode(), self.database().read_bytes())
        self.assertEqual(source_sha, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_repeated_hour_is_idempotent_and_does_not_reobserve(self):
        first = self.run_cycle()
        fingerprint = self.fingerprint()
        with mock.patch.object(live.hub, "collect", side_effect=AssertionError("Replay should not read sources")):
            repeated = self.run_cycle(now=NOW + dt.timedelta(minutes=20))
        self.assertEqual(repeated["status"], "already_recorded")
        self.assertEqual(first["latest"], repeated["latest"])
        self.assertEqual(repeated["records"], 1)
        self.assertEqual(fingerprint, self.fingerprint())

    def test_new_hour_revises_plan_for_observed_source_corruption(self):
        source = self.continuity_fixture()
        first = self.run_cycle()
        self.assertEqual(first["latest"]["experiment"], "missing_source")
        with sqlite3.connect(source) as db:
            db.execute("UPDATE observations SET metrics='{}'")
        second = self.run_cycle(now=NOW + dt.timedelta(hours=1))
        self.assertEqual(second["records"], 2)
        self.assertEqual(second["latest"]["states"]["continuity"], "invalid")
        self.assertEqual(second["latest"]["experiment"], "provenance_integrity")
        restored = live.status(state=self.state)
        self.assertEqual(restored["status"], "ok")
        self.assertEqual(restored["latest"], second["latest"])

    def test_known_source_labels_do_not_claim_live_dios_or_service_verification(self):
        with mock.patch.object(live.hub, "collect", return_value=self.healthy_snapshot()):
            result = self.run_cycle()
        self.assertTrue(result["latest"]["local_checks_passed"])
        self.assertEqual(result["latest"]["experiment"], "independent_recovery")
        self.assertFalse(result["services_verified"])
        self.assertEqual(result["dios"], "NOT_CONNECTED_SYNTHETIC_ADAPTER")
        self.assertEqual(self.payloads()[0]["plan_state"], "PROPOSAL_NOT_EXECUTED")
        self.assertNotIn(SECRET, json.dumps(self.payloads()))
        self.assertNotIn(SECRET.encode(), self.database().read_bytes())
        self.assertLess(len(live.canonical(result)), 700)

    def test_status_missing_never_initializes_state(self):
        self.assertEqual(live.status(self.state)["status"], "missing")
        self.assertFalse(self.state.exists())
        self.state.mkdir()
        self.assertEqual(live.status(self.state)["status"], "missing")
        self.assertEqual(list(self.state.iterdir()), [])

    def test_status_does_not_write_to_valid_state(self):
        self.run_cycle()
        before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.state.iterdir()}
        self.assertEqual(live.status(self.state)["status"], "ok")
        after = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.state.iterdir()}
        self.assertEqual(before, after)

    def test_cold_interpreter_recovers_same_observation_without_new_cycle(self):
        result = self.run_cycle()
        code = ("import json,sys; from pathlib import Path; "
                "from tools.nasu_live_integration import status; "
                "print(json.dumps(status(state=Path(sys.argv[1]))))")
        process = subprocess.run([sys.executable, "-B", "-c", code, str(self.state)],
                                 cwd=Path(__file__).resolve().parents[1],
                                 capture_output=True, text=True, timeout=20, check=True)
        recovered = json.loads(process.stdout)
        self.assertEqual(recovered["status"], "ok")
        self.assertEqual(recovered["records"], 1)
        self.assertEqual(recovered["latest"], result["latest"])

    def test_tampered_journal_is_refused_without_reset(self):
        self.run_cycle()
        with sqlite3.connect(self.database()) as db:
            db.execute("UPDATE cycles SET payload='{}'")
        before = self.fingerprint()
        result = live.status(self.state)
        self.assertEqual(result["status"], "invalid")
        self.assertNotIn("latest", result)
        with self.assertRaises(ValueError):
            self.run_cycle(now=NOW + dt.timedelta(hours=1))
        self.assertEqual(before, self.fingerprint())

    def test_unknown_schema_is_not_migrated_or_reinitialized(self):
        self.run_cycle()
        with sqlite3.connect(self.database()) as db:
            db.execute("UPDATE metadata SET value='unknown/v99'")
        before = self.fingerprint()
        self.assertEqual(live.status(self.state)["status"], "invalid")
        with self.assertRaises(ValueError):
            self.run_cycle(now=NOW + dt.timedelta(hours=1))
        self.assertEqual(before, self.fingerprint())

    def test_extra_table_or_trigger_is_unknown_schema(self):
        self.run_cycle()
        with sqlite3.connect(self.database()) as db:
            db.execute("CREATE TABLE surprise(value)")
        self.assertEqual(live.status(self.state)["status"], "invalid")
        with self.assertRaises(ValueError):
            self.run_cycle(now=NOW + dt.timedelta(hours=1))

    def test_partial_initialization_and_corrupt_file_are_preserved(self):
        self.state.mkdir()
        for value in (b"", b"not sqlite " + SECRET.encode()):
            with self.subTest(value_length=len(value)):
                self.database().write_bytes(value)
                result = live.status(self.state)
                self.assertEqual(result["status"], "invalid")
                self.assertNotIn(SECRET, json.dumps(result))
                with self.assertRaises((ValueError, sqlite3.Error)):
                    self.run_cycle()
                self.assertEqual(self.database().read_bytes(), value)

    def test_unknown_files_or_nonempty_sqlite_sidecar_block_execution(self):
        self.run_cycle()
        for filename in ("unexpected", live.DATABASE + "-journal", live.DATABASE + "-wal"):
            with self.subTest(filename=filename):
                path = self.state / filename
                path.write_text(SECRET)
                self.assertEqual(live.status(self.state)["status"], "invalid")
                with self.assertRaises(ValueError):
                    self.run_cycle(now=NOW + dt.timedelta(hours=1))
                path.unlink()

    def test_symlinked_state_or_database_is_rejected(self):
        target = self.root / "elsewhere"
        target.mkdir()
        self.state.symlink_to(target, target_is_directory=True)
        self.assertEqual(live.status(self.state)["status"], "invalid")
        with self.assertRaises(ValueError):
            self.run_cycle()
        self.state.unlink()
        self.state.mkdir()
        target_file = target / "source.sqlite3"
        target_file.write_bytes(b"do not edit")
        self.database().symlink_to(target_file)
        self.assertEqual(live.status(self.state)["status"], "invalid")
        with self.assertRaises(ValueError):
            self.run_cycle()
        self.assertEqual(target_file.read_bytes(), b"do not edit")

    def test_hardlinked_state_cannot_modify_a_source_file(self):
        source = self.continuity_fixture()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        self.state.mkdir()
        os.link(source, self.database())
        self.assertEqual(live.status(self.state)["status"], "invalid")
        with self.assertRaises(ValueError):
            self.run_cycle()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_state_path_cannot_overlap_source_ledgers(self):
        for state in (self.home, self.root, self.home / "continuity"):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    live.run(home=self.home, state=state, now=NOW)
        self.assertEqual(list(self.home.iterdir()), [])
        result = live.run(home=self.home, state=self.home / "agent-integration", now=NOW)
        self.assertEqual(result["status"], "recorded")

    def test_clock_rollback_is_refused(self):
        self.run_cycle()
        before = self.fingerprint()
        with self.assertRaisesRegex(ValueError, "clock_rollback"):
            self.run_cycle(now=NOW - dt.timedelta(hours=1))
        self.assertEqual(before, self.fingerprint())

    def test_root_execution_is_refused_before_files_are_created(self):
        with mock.patch.object(live.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "refusing_root"):
                self.run_cycle()
        self.assertFalse(self.state.exists())

    def test_naive_or_non_utc_timestamp_is_refused(self):
        for value in (NOW.replace(tzinfo=None), NOW.astimezone(dt.timezone(dt.timedelta(hours=3)))):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.run_cycle(now=value)
        self.assertFalse(self.state.exists())

    def test_failed_collection_does_not_commit_a_successful_cycle(self):
        first = self.run_cycle()
        before = self.fingerprint()
        with mock.patch.object(live.hub, "collect", side_effect=ValueError(SECRET)):
            with self.assertRaises(ValueError):
                self.run_cycle(now=NOW + dt.timedelta(hours=1))
        result = live.status(self.state)
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["latest"], first["latest"])
        self.assertEqual(before, self.fingerprint())

    def test_failed_first_collection_leaves_known_empty_journal(self):
        with mock.patch.object(live.hub, "collect", side_effect=ValueError(SECRET)):
            with self.assertRaises(ValueError):
                self.run_cycle()
        self.assertEqual(live.status(self.state)["status"], "empty")
        self.assertEqual(self.run_cycle()["records"], 1)

    def test_rehashed_private_payload_fields_are_not_republished(self):
        self.run_cycle()
        with sqlite3.connect(self.database()) as db:
            hour, stamp, raw, previous = db.execute(
                "SELECT hour,observed_at_utc,payload,previous_sha FROM cycles").fetchone()
            payload = json.loads(raw)
            payload["private"] = SECRET
            db.execute("UPDATE cycles SET payload=?,digest=?",
                       (live.canonical(payload), live._digest(hour, stamp, payload, previous)))
        result = live.status(self.state)
        self.assertEqual(result["status"], "invalid")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_concurrent_calls_cannot_duplicate_a_slot(self):
        self.run_cycle()
        def call():
            try:
                return self.run_cycle(now=NOW + dt.timedelta(hours=1))["status"]
            except (ValueError, sqlite3.OperationalError):
                # An observed nonempty journal is conservatively blocked.
                return "blocked_concurrent_writer"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: call(), range(2)))
        self.assertEqual(results.count("recorded"), 1)
        self.assertEqual(live.status(self.state)["records"], 2)


if __name__ == "__main__":
    unittest.main()
