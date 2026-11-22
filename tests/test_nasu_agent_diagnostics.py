"""Offline contract tests for metadata diagnostics; no production state used."""
import contextlib
import datetime as dt
import hashlib
from http.client import IncompleteRead
import http.server
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import types
import unittest
from unittest import mock
import urllib.request

from tools import nasu_agent_diagnostics as diag
from tools import nasu_autonomous_cognition as cognition


SECRET = "PRIVATE_SECRET_TOKEN_AND_MODEL_RESPONSE"
NOW = dt.datetime(2026, 11, 19, 7, tzinfo=dt.timezone.utc)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def database(self):
        db = cognition.connect(self.home / "cognitive-growth/cycles.sqlite3")
        self.addCleanup(db.close)
        return db

    def record(self, db, slot, model="UNVERIFIED_DRAFT", previous=None):
        previous = previous or cognition.ZERO
        row = {"slot": slot, "stamp": NOW.isoformat(), "topic": "continuity",
               "source_path": SECRET, "source_sha": "a" * 64, "fixed_result": "PASS",
               "model_status": model, "proposal": json.dumps({"private": SECRET}),
               "next_topic": "", "previous_sha": previous}
        digest = cognition.sha(row)
        db.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (*row.values(), digest, "completed"))
        return digest

    def runner(self, args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=(
            "LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\n"
            "ExecMainStatus=0\nNextElapseUSecRealtime=Thu 2026-11-19 12:00:00 UTC\n"
            "LastTriggerUSec=Thu 2026-11-19 06:00:00 UTC\n"), stderr=SECRET)

    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def test_missing_database_does_not_initialize_or_generate(self):
        before = list(self.home.rglob("*"))
        with mock.patch.object(diag, "probe_model", side_effect=AssertionError("generation")):
            with mock.patch.object(cognition, "connect", side_effect=AssertionError("database init")):
                result = diag.collect(home=self.home, now=NOW, runner=self.runner)
        self.assertEqual(result["cognition"], {"state": "missing"})
        self.assertEqual(before, list(self.home.rglob("*")))
        self.assertNotIn("probe", result)

    def test_wrong_schema_and_tampering_are_invalid(self):
        path = self.home / "cognitive-growth/cycles.sqlite3"
        path.parent.mkdir()
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE cycles(slot TEXT)")
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})
        path.unlink()
        db = self.database()
        self.record(db, "2026-11-19T00")
        db.execute("UPDATE cycles SET proposal='changed'")
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})

    def test_completed_drafts_failures_and_reserved_are_distinct(self):
        db = self.database()
        first = self.record(db, "2026-11-18T18")
        self.record(db, "2026-11-19T00", "model_unavailable:" + SECRET, first)
        db.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("2026-11-19T06", NOW.isoformat(), "continuity", "", "", "", "", "{}", "", "", "", "reserved"))
        result = diag.cognitive_status(self.home)
        self.assertEqual((result["completed"], result["drafts"], result["failed"], result["incomplete"]), (2, 1, 1, 1))
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(result["latest"], {"slot": "2026-11-19T00", "model": "model_unavailable"})
        self.assertEqual(result["last_successful_slot"], "2026-11-18T18")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_unknown_state_and_rehashed_metadata_fail_closed(self):
        db = self.database()
        self.record(db, "2026-11-19T00", SECRET)
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})
        db.execute("DELETE FROM cycles")
        self.record(db, SECRET)
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})
        db.execute("UPDATE cycles SET state='some_new_state'")
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})

    def test_known_failure_reasons_are_safe_and_legacy_rows_unchanged(self):
        db = self.database()
        cases = [(reason, reason) for reason in cognition.MODEL_RESPONSE_FAILURES]
        cases += [("TimeoutError", "timeout"), ("URLError", "transport_error"),
                  ("ConnectionRefusedError", "connection_refused"), ("HTTPError", "http_error"),
                  ("ValueError", None), (SECRET, None), ("invalid_envelope:" + SECRET, None)]
        for suffix, expected in cases:
            with self.subTest(suffix=suffix):
                db.execute("DELETE FROM cycles")
                self.record(db, "2026-11-19T00", "model_unavailable:" + suffix)
                before = db.execute("SELECT * FROM cycles").fetchall()
                result = diag.cognitive_status(self.home)
                self.assertEqual(result["latest"].get("failure_reason"), expected)
                self.assertEqual((result["drafts"], result["failed"], result["incomplete"]), (0, 1, 0))
                self.assertEqual(db.execute("SELECT * FROM cycles").fetchall(), before)
                self.assertNotIn(SECRET, json.dumps(result))
                encoded = diag.compact(diag.collect(home=self.home, now=NOW, runner=self.runner))
                self.assertLessEqual(len(encoded), diag.MAX_OUTPUT)
                self.assertIn("cognition", json.loads(encoded))

    def test_actual_rejected_response_reaches_diagnostics_as_failed_receipt(self):
        db = self.database()
        source = self.home / cognition.TOPICS["continuity"][0]
        source.parent.mkdir(parents=True)
        source.write_text("value = 1\n")
        def infer(*args):
            return cognition.local_llm(*args, opener=lambda *a, **k: io.BytesIO(b"[]"))
        cognition.run(db, now=NOW, root=self.home, infer=infer, tester=lambda *a: "PASS")
        result = diag.cognitive_status(self.home)
        self.assertEqual(result["latest"]["failure_reason"], "invalid_envelope")
        self.assertEqual((result["drafts"], result["failed"], result["incomplete"]), (0, 1, 0))
        self.assertIsNone(result["last_successful_slot"])

    def test_actual_incomplete_http_receipt_projects_only_fixed_failure_reason(self):
        db = self.database()
        source = self.home / cognition.TOPICS["continuity"][0]
        source.parent.mkdir(parents=True)
        source.write_text("value = 1\n")
        class InterruptedResponse(io.BytesIO):
            def read(self, size=-1):
                raise IncompleteRead(SECRET.encode(), 11)
        def infer(*args):
            return cognition.local_llm(*args, opener=lambda *a, **k: InterruptedResponse())
        with mock.patch.object(cognition, "_identity_for_prompt", return_value=None):
            cognition.run(db, now=NOW, root=self.home, infer=infer,
                          tester=lambda *a: "PASS")
        before = db.execute("SELECT * FROM cycles").fetchall()
        result = diag.cognitive_status(self.home)
        self.assertEqual(result["state"], "verified_history")
        self.assertEqual(result["latest"], {"slot": "2026-11-19T06",
                         "model": "model_unavailable", "failure_reason": "incomplete_http_response"})
        self.assertEqual((result["completed"], result["drafts"], result["failed"], result["incomplete"]), (1, 0, 1, 0))
        self.assertEqual(db.execute("SELECT * FROM cycles").fetchall(), before)
        self.assertNotIn(SECRET, diag.compact(result))
        self.assertIsNone(diag._failure_reason("model_unavailable:incomplete_http_response:" + SECRET))

    def test_symlink_database_and_sidecar_are_rejected(self):
        db = self.database()
        self.record(db, "2026-11-19T00")
        db.close()
        path = self.home / "cognitive-growth/cycles.sqlite3"
        journal = Path(str(path) + "-journal")
        journal.symlink_to(self.home / "nonexistent")
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})
        journal.unlink()
        alternate = path.with_name("actual.sqlite3")
        path.rename(alternate)
        path.symlink_to(alternate)
        self.assertEqual(diag.cognitive_status(self.home), {"state": "invalid"})

    def test_wal_rows_are_seen_without_initialization(self):
        db = self.database()
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.record(db, "2026-11-19T00")
        self.assertGreater(Path(str(self.home / "cognitive-growth/cycles.sqlite3") + "-wal").stat().st_size, 0)
        with mock.patch.object(cognition, "connect", side_effect=AssertionError("init")):
            self.assertEqual(diag.cognitive_status(self.home)["drafts"], 1)

    def test_fixed_systemctl_allowlist_and_safe_projection(self):
        seen = []
        def runner(args, **kwargs):
            seen.append(args)
            self.assertEqual(kwargs["env"], diag.ENV)
            self.assertEqual(kwargs["timeout"], 3)
            self.assertFalse(kwargs.get("shell", False))
            return self.runner(args, **kwargs)
        result = diag.service_status(runner=runner)
        self.assertEqual([args[2] for args in seen], list(diag.UNITS.values()))
        self.assertTrue(all(args[:2] == ["/usr/bin/systemctl", "show"] for args in seen))
        self.assertEqual(result["cognition_timer"]["next"], "2026-11-19T12:00:00Z")
        self.assertNotIn(SECRET, json.dumps(result))
        def injected(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "LoadState=" + SECRET + "\nActiveState=" + SECRET + "\nSubState=" + SECRET + "\nResult=" + SECRET + "\nNextElapseUSecRealtime=" + SECRET, SECRET)
        self.assertNotIn(SECRET, json.dumps(diag.service_status(runner=injected)))

    def test_unavailable_systemctl_never_echoes_error(self):
        def fail(*args, **kwargs):
            raise OSError(SECRET)
        result = diag.service_status(runner=fail)
        self.assertTrue(all(row == {"state": "unavailable"} for row in result.values()))
        self.assertNotIn(SECRET, json.dumps(result))

    def test_source_and_installed_hashes(self):
        installed = self.home / "installed.py"
        release = self.home / "release.py"
        installed.write_text("old")
        release.write_text("new")
        with mock.patch.object(diag, "INSTALLED_COGNITION", installed), mock.patch.object(diag, "RELEASE_COGNITION", release):
            result = diag.executable_status()
        self.assertEqual(result["installed"], hashlib.sha256(b"old").hexdigest())
        self.assertFalse(result["match"])

    def test_probe_is_one_fixed_bounded_local_call_and_no_text(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            self.assertEqual(request.full_url, diag.LOCAL_URL)
            self.assertEqual(timeout, 90)
            payload = json.loads(request.data)
            self.assertEqual(payload["model"], "qwen3:4b-instruct")
            self.assertEqual(payload["options"]["num_predict"], 64)
            self.assertNotIn(SECRET, payload["prompt"])
            return self.response({"model": diag.MODEL, "done": True, "response": "READY", "private": SECRET})
        result = diag.probe_model(opener=opener)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result, {"state": "success", "sha256": hashlib.sha256(b"READY").hexdigest()})
        self.assertNotIn(SECRET, json.dumps(result))

    def test_proxy_disabled_and_redirect_handler_installed(self):
        fake = types.SimpleNamespace(open=lambda *a, **k: self.response({"model": diag.MODEL, "done": True, "response": "READY"}))
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://" + SECRET, "HTTPS_PROXY": "http://" + SECRET}):
            with mock.patch.object(urllib.request, "build_opener", return_value=fake) as build:
                self.assertEqual(diag.probe_model()["state"], "success")
        handlers = build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], diag._NoRedirect)
        fp = io.BytesIO(b"redirect")
        with self.assertRaises(ValueError):
            handlers[1].redirect_request(None, fp, 302, "Found", {}, "https://example.invalid/" + SECRET)
        self.assertTrue(fp.closed)

    def test_probe_rejects_oversized_malformed_incomplete_or_wrong_model(self):
        cases = [b"x" * (diag.MAX_RESPONSE + 1), b"not json", b"[]",
                 json.dumps({"model": diag.MODEL, "done": False, "response": "READY"}).encode(),
                 json.dumps({"model": "different", "done": True, "response": "READY"}).encode(),
                 json.dumps({"model": diag.MODEL, "done": True, "response": SECRET}).encode(),
                 json.dumps({"model": diag.MODEL, "done": True, "response": None}).encode()]
        for data in cases:
            with self.subTest(data_length=len(data)):
                result = diag.probe_model(opener=lambda *a, **k: io.BytesIO(data))
                self.assertEqual(result, {"state": "failed"})
                self.assertNotIn(SECRET, json.dumps(result))

    def test_real_local_http_redirect_is_not_followed(self):
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(302)
                self.send_header("Location", "/escaped")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                requests.append(self.path)
                body = json.dumps({"model": diag.MODEL, "done": True, "response": "READY"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%d/api/generate" % server.server_port
            with mock.patch.object(diag, "LOCAL_URL", url):
                with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
                    self.assertEqual(diag.probe_model(), {"state": "failed"})
            self.assertEqual(requests, ["/api/generate"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_compact_output_is_valid_bounded_json(self):
        db = self.database()
        self.record(db, "2026-11-19T00")
        result = diag.collect(home=self.home, now=NOW, runner=self.runner)
        encoded = diag.compact(result)
        self.assertLessEqual(len(encoded), diag.MAX_OUTPUT)
        self.assertEqual(json.loads(encoded)["schema"], diag.SCHEMA)
        self.assertNotIn(SECRET, encoded)
        overflow = diag.compact({"unknown": SECRET * 2000})
        self.assertEqual(json.loads(overflow)["state"], "output_limit")
        self.assertNotIn(SECRET, overflow)

    def test_cli_refuses_root_and_arbitrary_arguments(self):
        for uid, args, state in ((0, ["status"], "root_refused"),
                                 (1000, ["status", "--home", SECRET], "usage_status_or_probe")):
            with mock.patch.object(os, "geteuid", return_value=uid), contextlib.redirect_stdout(io.StringIO()) as output:
                with mock.patch.object(diag, "collect", side_effect=AssertionError("should not run")):
                    self.assertEqual(diag.main(args), 2)
            self.assertEqual(json.loads(output.getvalue())["state"], state)
            self.assertNotIn(SECRET, output.getvalue())

    def test_cli_probe_failure_has_nonzero_exit_and_safe_receipt(self):
        result = {"schema": diag.SCHEMA, "probe": {"state": "failed"}}
        with mock.patch.object(os, "geteuid", return_value=1000), contextlib.redirect_stdout(io.StringIO()) as output:
            with mock.patch.object(diag, "collect", return_value=result) as collect:
                self.assertEqual(diag.main(["probe"]), 1)
        collect.assert_called_once_with("probe")
        self.assertEqual(json.loads(output.getvalue()), result)


if __name__ == "__main__":
    unittest.main()
