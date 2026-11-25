"""Behavioral checks for the executed offline integration rehearsal.

All data are authored fixtures. The subprocess case checks cold recovery in a
different interpreter; the application itself must not launch any process.
"""
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request

from tools import nasu_integration_rehearsal as rehearsal
from tools import nasuraya_offline_continuity as continuity


class IntegrationRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.output = self.parent / "episode"

    def run_episode(self):
        return rehearsal.rehearse(self.output)

    def memory_path(self):
        found = []
        for path in self.output.rglob("*"):
            if path.suffix not in (".sqlite", ".sqlite3", ".db"):
                continue
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "cognitive_views" in tables:
                    found.append(path)
        self.assertEqual(len(found), 1, "one DIOS cognitive memory is expected")
        return found[0]

    def counts(self):
        with closing(sqlite3.connect(self.memory_path())) as db:
            return tuple(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                         for table in ("evidence", "cognitive_views"))

    def test_api_executes_without_network_or_subprocess(self):
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
             mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
             mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=AssertionError("network")), \
             mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess")), \
             mock.patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess")):
            result = self.run_episode()
            recovered = rehearsal.recover(self.output)
        self.assertIsInstance(result, dict)
        self.assertIsInstance(recovered, dict)

    def test_dialogue_affect_awake_dios_handoff(self):
        with mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=AssertionError("network")):
            result = rehearsal.rehearse_dialogue(self.output)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["dios_review"]["stance"], "SUPPORTED")
        self.assertEqual(result["recovered_decision"], "A")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["external_actions_taken"], 0)
        self.assertFalse(result["live_deployment_verified"])
        self.assertNotIn("SYNTHETIC_DIALOGUE_PRIVATE_SENTINEL", json.dumps(result))
        with closing(sqlite3.connect(self.output / "awake-stage/awake.sqlite3")) as db:
            payloads = [json.loads(row[0]) for row in db.execute("SELECT payload FROM evidence")]
            self.assertEqual(len(payloads), 5)
            self.assertTrue(all(type(row["value"]) is bool for row in payloads))
            self.assertNotIn("SYNTHETIC_DIALOGUE_PRIVATE_SENTINEL", json.dumps(payloads))
        with self.assertRaises((ValueError, FileExistsError)):
            rehearsal.rehearse_dialogue(self.output)

    def test_existing_empty_directory_is_not_initialized(self):
        self.output.mkdir()
        with self.assertRaises((ValueError, FileExistsError)):
            self.run_episode()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_files_are_not_rewritten(self):
        self.output.mkdir()
        sentinel = self.output / "existing.sqlite"
        sentinel.write_bytes(b"EXISTING_MEMORY_DO_NOT_RESET")
        with self.assertRaises((ValueError, FileExistsError)):
            self.run_episode()
        self.assertEqual(sentinel.read_bytes(), b"EXISTING_MEMORY_DO_NOT_RESET")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_symlinked_output_is_rejected(self):
        real = self.parent / "real"
        real.mkdir()
        self.output.symlink_to(real, target_is_directory=True)
        with self.assertRaises((ValueError, FileExistsError)):
            self.run_episode()
        self.assertEqual(list(real.iterdir()), [])

    def test_symlinked_ancestor_is_rejected(self):
        real = self.parent / "real"
        real.mkdir()
        alias = self.parent / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            rehearsal.rehearse(alias / "new")
        self.assertEqual(list(real.iterdir()), [])

    def test_recover_does_not_initialize_missing_directory(self):
        with self.assertRaises((ValueError, OSError)):
            rehearsal.recover(self.output)
        self.assertFalse(self.output.exists())

    def test_recover_rejects_foreign_directory(self):
        self.output.mkdir()
        sentinel = self.output / "do-not-touch"
        sentinel.write_text("foreign")
        with self.assertRaises((ValueError, OSError)):
            rehearsal.recover(self.output)
        self.assertEqual(sentinel.read_text(), "foreign")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_rerunning_finished_episode_cannot_reset_it(self):
        self.run_episode()
        memory = self.memory_path().read_bytes()
        counts = self.counts()
        with self.assertRaises((ValueError, FileExistsError)):
            self.run_episode()
        self.assertEqual(memory, self.memory_path().read_bytes())
        self.assertEqual(counts, self.counts())

    def test_repeated_recovery_does_not_append_evidence_or_views(self):
        self.run_episode()
        counts = self.counts()
        first = rehearsal.recover(self.output)
        second = rehearsal.recover(self.output)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(first, second)

    def test_memory_edit_fails_recovery(self):
        self.run_episode()
        with closing(sqlite3.connect(self.memory_path())) as db:
            with db:
                db.execute("UPDATE evidence SET value=CASE value WHEN 'A' THEN 'B' ELSE 'A' END")
        with self.assertRaises((ValueError, RuntimeError)):
            rehearsal.recover(self.output)

    def test_new_interpreter_recovers_same_result(self):
        self.run_episode()
        expected = rehearsal.recover(self.output)
        counts = self.counts()
        script = (
            "import json,sys; "
            "from pathlib import Path; "
            "from tools.nasu_integration_rehearsal import recover; "
            "print(json.dumps(recover(Path(sys.argv[1])),sort_keys=True))"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.output)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=True, timeout=20,
        )
        self.assertEqual(json.loads(completed.stdout), expected)
        self.assertEqual(self.counts(), counts)

    def test_five_inputs_drive_revision_and_experiment_priority(self):
        result = self.run_episode()
        initial, corrupt, restored = result["cycles"]
        self.assertEqual([row["name"] for row in result["cycles"]],
                         ["initial", "corrupted", "restored"])
        expected = {"continuity": "verified_history", "awake": "structural_only",
                    "frontier": "verified_history", "cognition": "verified_history",
                    "feedback": "verified_history"}
        self.assertEqual(initial["states"], expected)
        self.assertEqual(restored["states"], expected)
        self.assertEqual(corrupt["states"], {**expected, "continuity": "invalid"})
        self.assertEqual([row["experiment_id"] for row in result["cycles"]],
                         ["independent_recovery", "provenance_integrity", "independent_recovery"])
        self.assertEqual([row["review"]["stance"] for row in result["cycles"]],
                         ["SUPPORTED", "PROVISIONAL_DISSENT", "SUPPORTED"])
        for before, row, after in (("A", corrupt, "B"), ("B", restored, "A")):
            review = row["review"]["evidence_review"]
            self.assertEqual(review["previous_decision"], before)
            self.assertEqual(review["decision"], after)
            self.assertTrue(review["revised"])
        self.assertNotEqual(initial["snapshot_sha256"], corrupt["snapshot_sha256"])
        self.assertEqual(result["counts"], {"evidence_records": 22, "view_records": 6})

    def test_all_five_claims_use_one_observer_not_fake_corroboration(self):
        self.run_episode()
        with closing(sqlite3.connect(self.memory_path())) as db:
            rows = db.execute(
                "SELECT claim_key,value,source_root FROM evidence "
                "WHERE scope='fixture:1' AND epoch=3 AND verified_by_caller=1 "
                "ORDER BY claim_key"
            ).fetchall()
        self.assertEqual(len(rows), 6)
        self.assertEqual({row[2] for row in rows}, {"fixture:1"})
        self.assertEqual(dict((row[0], row[1]) for row in rows), {
            "fixture:1": "B", "fixture:2": "A", "fixture:3": "A",
            "fixture:4": "A", "fixture:5": "A", "fixture:6": "B",
        })

    def test_draft_is_retained_untrusted_and_cannot_override_observation(self):
        result = self.run_episode()
        review = result["unverified_draft_review"]["evidence_review"]
        self.assertEqual(review["decision"], "A")
        self.assertEqual(review["supporting_roots"], [1])
        self.assertEqual(review["opposing_roots"], [])
        with closing(sqlite3.connect(self.memory_path())) as db:
            draft = db.execute(
                "SELECT value,epoch,source_kind,verified_by_caller FROM evidence "
                "WHERE event_id='fixture:900'"
            ).fetchone()
        self.assertEqual(draft, ("B", 2, "public_text", 0))

    def test_equal_epoch_conflict_abstains_and_survives_recovery(self):
        result = self.run_episode()
        conflict = result["contradiction_review"]["evidence_review"]
        self.assertEqual(conflict["verdict"], "ABSTAIN")
        self.assertEqual(conflict["status"], "abstain_contradiction")
        self.assertEqual(conflict["supporting_roots"], [1])
        self.assertEqual(conflict["opposing_roots"], [2])
        recovered = result["recovery"]
        self.assertIsNone(recovered["conflict"]["decision"])
        self.assertEqual(recovered["decision"]["decision"], "A")
        self.assertEqual(recovered["outcome"]["decision"], "A")
        self.assertEqual(recovered["experiments_reexecuted"], 0)

    def test_restore_reads_real_retained_sqlite_and_matches_original_chain(self):
        result = self.run_episode()
        verified = []
        for relative in ("checkpoint.sqlite", "local-restore.sqlite",
                         "inputs/continuity/continuity.sqlite3"):
            path = self.output / relative
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                verified.append(continuity.verify(db))
        self.assertEqual(verified[0], verified[1])
        self.assertEqual(verified[1], verified[2])
        self.assertEqual(verified[0]["records"], 1)
        self.assertEqual(result["local_restore"]["baseline"], verified[0])
        self.assertEqual(result["local_restore"]["restored"], verified[2])
        self.assertFalse(result["phase2_offsite_experiment_executed"])
        self.assertIn("independent_offsite_restore_with_separate_keys", result["unverified_gates"])

    def test_awake_records_actual_ingestion_without_resuming_or_ticking(self):
        result = self.run_episode()
        with closing(sqlite3.connect(self.output / "inputs/awake-stage/awake.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT value FROM control WHERE name='paused'").fetchone(), ("1",))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence").fetchone(), (2,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ticks").fetchone(), (0,))
            columns = {row[1] for row in db.execute("PRAGMA table_info(questions)")}
        self.assertTrue({"topic", "id", "kind", "question", "evidence_hash", "revision"}.issubset(columns))
        self.assertTrue(all(cycle["awake_paused"] for cycle in result["cycles"]))

    def test_private_fixture_text_never_reaches_public_report_or_dios_memory(self):
        result = self.run_episode()
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(rehearsal.PRIVATE_SENTINEL, encoded)
        self.assertNotIn(rehearsal.PRIVATE_SENTINEL.encode(), self.memory_path().read_bytes())
        with closing(sqlite3.connect(self.output / "inputs/cognitive-growth/cycles.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT proposal FROM cycles").fetchone()[0],
                             rehearsal.PRIVATE_SENTINEL)
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(all(cycle["feedback_comparable"] == 0 for cycle in result["cycles"]))

    def test_supported_evidence_does_not_enable_external_action(self):
        result = self.run_episode()
        review = result["external_action_review"]
        self.assertEqual(review["evidence_review"]["verdict"], "SUPPORTED")
        self.assertEqual(review["stance"], "HALT_AND_REVIEW")
        self.assertFalse(review["execution_permitted"])
        self.assertIn("missing_authorization", review["boundary_review"]["reason_codes"])
        self.assertEqual(result["external_actions_taken"], 0)

    def test_modified_report_or_missing_retained_file_fails_recovery(self):
        self.run_episode()
        report = self.output / "report.json"
        original = report.read_bytes()
        report.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "report_changed"):
            rehearsal.recover(self.output)
        report.write_bytes(original)
        (self.output / "checkpoint.sqlite").unlink()
        with self.assertRaisesRegex(ValueError, "missing_rehearsal_file"):
            rehearsal.recover(self.output)

    def test_recovery_rejects_symlink_in_retained_files(self):
        self.run_episode()
        original = self.output / "checkpoint.sqlite"
        outside = self.parent / "outside.sqlite"
        original.replace(outside)
        original.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            rehearsal.recover(self.output)

    def test_recovery_rejects_committed_wal_change_with_unchanged_main_file(self):
        self.run_episode()
        source = self.output / "inputs/continuity/continuity.sqlite3"
        original_main = source.read_bytes()
        with closing(sqlite3.connect(source)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("UPDATE observations SET metrics='{}'")
            writer.commit()
            wal = Path(str(source) + "-wal")
            self.assertGreater(wal.stat().st_size, 0)
            self.assertEqual(source.read_bytes(), original_main,
                             "the regression requires a matching but stale main-file hash")
            original_wal = wal.read_bytes()
            with self.assertRaisesRegex(ValueError, "uncheckpointed_or_interrupted_database"):
                rehearsal.recover(self.output)
            self.assertEqual(source.read_bytes(), original_main)
            self.assertEqual(wal.read_bytes(), original_wal)
            self.assertEqual(writer.execute("SELECT metrics FROM observations").fetchone(), ("{}",))

    def test_recovery_rejects_unfinished_cognitive_writer_lock(self):
        self.run_episode()
        lock = Path(str(self.memory_path()) + ".cognitive-lock")
        lock.mkdir()
        marker = lock / "interrupted"
        marker.write_text("do not clear this writer state")
        with self.assertRaisesRegex(ValueError, "unfinished_cognitive_writer"):
            rehearsal.recover(self.output)
        self.assertTrue(lock.is_dir())
        self.assertEqual(marker.read_text(), "do not clear this writer state")

    def test_recovery_rejects_symlinked_sqlite_coordination_files(self):
        self.run_episode()
        memory = self.memory_path()
        outside = self.parent / "outside-sidecar"
        outside.write_bytes(b"do not follow or change")
        for suffix in ("-wal", "-journal", "-shm", ".cognitive-lock"):
            with self.subTest(suffix=suffix):
                sidecar = Path(str(memory) + suffix)
                self.assertFalse(sidecar.exists())
                sidecar.symlink_to(outside)
                try:
                    with self.assertRaisesRegex(ValueError, "symlinked_sqlite_sidecar"):
                        rehearsal.recover(self.output)
                    self.assertEqual(outside.read_bytes(), b"do not follow or change")
                finally:
                    sidecar.unlink()


if __name__ == "__main__":
    unittest.main()
