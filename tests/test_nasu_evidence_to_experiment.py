"""Phase-2 integration tests: synthetic-only, no live VPS or account data."""
import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request

from tools import nasu_evidence_to_experiment as phase
from tools import nasu_unified_status as hub

ALL_PRESENT = {
    "continuity": "verified_history",
    "awake": "structural_only",
    "frontier": "verified_history",
    "cognition": "verified_history",
    "feedback": "verified_history",
}


def snapshot(**updates):
    states = {**ALL_PRESENT, **updates}
    return {"schema": hub.SCHEMA, "execution": "OFFLINE_READ_ONLY",
            "generated_at_utc": "2026-11-19T00:00:00+00:00",
            "components": {k: {"status": v} for k, v in states.items()},
            "untrusted_private_text": "EXCLUDED_PRIVATE_VALUE"}


class ExperimentPlanTests(unittest.TestCase):
    def test_good_local_history_does_not_establish_offsite_restore(self):
        p = phase.plan(snapshot())
        self.assertEqual(p["selected"]["id"], "independent_recovery")
        self.assertEqual(p["state"], "PROPOSAL_NOT_EXECUTED")
        self.assertEqual(p["authority"], "HUMAN_REVIEW_REQUIRED")
        self.assertFalse(p["evidence"]["independent_security_attestation"])
        self.assertNotIn("EXCLUDED_PRIVATE_VALUE", json.dumps(p))

    def test_changed_source_snapshot_hash_changes(self):
        first = phase.plan(snapshot())
        second = phase.plan(snapshot(feedback="missing"))
        self.assertNotEqual(first["snapshot_sha256_local_non_authenticating"],
                            second["snapshot_sha256_local_non_authenticating"])

    def test_invalid_beats_missing_and_incomplete(self):
        p = phase.plan(snapshot(awake="invalid", frontier="missing",
                                feedback="incomplete"))
        self.assertEqual(p["selected"]["id"], "provenance_integrity")
        self.assertEqual(p["selected"]["affected_components"], ["awake"])

    def test_incomplete_reservation_is_not_success(self):
        p = phase.plan(snapshot(cognition="incomplete"))
        self.assertEqual(p["selected"]["id"], "incomplete_journal")
        self.assertEqual(p["selected"]["affected_components"], ["cognition"])

    def test_missing_core_is_not_initialized(self):
        p = phase.plan(snapshot(continuity="missing"))
        self.assertEqual(p["selected"]["id"], "missing_source")
        self.assertIn("continuity", p["selected"]["affected_components"])

    def test_empty_history_is_not_running(self):
        p = phase.plan(snapshot(frontier="empty"))
        self.assertEqual(p["selected"]["id"], "empty_history")
        self.assertEqual(p["evidence"]["actual_experiment_executed"], False)

    def test_unknown_snapshot_fail_closed(self):
        for sample in ({"schema": "wrong"},
                       {**snapshot(), "execution": "NETWORK_WRITE"}):
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    phase.plan(sample)

    def test_unhashable_or_nontext_status_fails_closed(self):
        for value in ([], {}, None, True, 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    phase.plan(snapshot(continuity=value))

    def test_timestamp_is_a_utc_datetime_not_arbitrary_text(self):
        for stamp in ("", "PRIVATE_STAMP", "2026-11-19T00:00:00",
                      "2026-11-19T00:00:00+03:30", "2026-02-31T00:00:00+00:00"):
            with self.subTest(stamp=stamp):
                with self.assertRaises(ValueError):
                    phase.plan({**snapshot(), "generated_at_utc": stamp})

    def test_plan_does_not_alias_input_metadata(self):
        source = snapshot()
        packet = phase.plan(source)
        source["components"]["awake"]["status"] = "invalid"
        self.assertEqual(packet["evidence"]["component_states"]["awake"],
                         "structural_only")

    def test_wrong_components_fail_closed(self):
        s = snapshot()
        del s["components"]["awake"]
        with self.assertRaises(ValueError):
            phase.plan(s)
        s = snapshot()
        s["components"]["surprise"] = {"status": "verified_history"}
        with self.assertRaises(ValueError):
            phase.plan(s)

    def test_nonawake_cannot_claim_structural_only(self):
        with self.assertRaises(ValueError):
            phase.plan(snapshot(feedback="structural_only"))

    def test_awake_cannot_claim_authenticated_history(self):
        with self.assertRaises(ValueError):
            phase.plan(snapshot(awake="verified_history"))

    def test_draft_schema_must_be_exact_and_nonempty(self):
        good = {"hypothesis": "فرضیهٔ تست‌شدنی، هنوز اجرا نشده است",
                "test": "آزمون مصنوعی با ورودی ثابت و شاهد مستقل",
                "failure_condition": "عدم تشخیص تغییر داده یک شکست روشن است"}
        self.assertEqual(phase.validate_draft(good), good)
        with self.assertRaises(ValueError):
            phase.validate_draft({**good, "run_shell": "yes"})
        with self.assertRaises(ValueError):
            phase.validate_draft({**good, "test": "x"})

    def test_default_run_never_asks_model_or_uses_network(self):
        s = snapshot(awake="missing")
        with mock.patch.object(hub, "collect", return_value=s):
            with mock.patch.object(urllib.request, "urlopen",
                                   side_effect=AssertionError("network")):
                with mock.patch.object(phase, "local_question",
                                       side_effect=AssertionError("llm")):
                    p = phase.run()
        self.assertEqual(p["model"]["state"], "NOT_REQUESTED")

    def test_optin_draft_blocked_when_evidence_missing(self):
        s = snapshot(awake="invalid")
        with mock.patch.object(hub, "collect", return_value=s):
            p = phase.run(ask_local_qwen=True, infer=lambda _: 1/0)
        self.assertEqual(p["model"]["state"], "BLOCKED_BY_EVIDENCE_GATE")

    def test_optin_returns_unverified_text_without_execution(self):
        s = snapshot()
        answer = {"hypothesis": "فرضیهٔ مشخص با قابلیت رد کردن پس از آزمون",
                  "test": "آزمایش ساختگی از روی یک دادهٔ مصنوعی و ثابت",
                  "failure_condition": "عدم بازتولید همان پاسخ با دادهٔ ثابت"}
        with mock.patch.object(hub, "collect", return_value=s):
            p = phase.run(ask_local_qwen=True, infer=lambda _: answer)
        self.assertEqual(p["model"]["state"], "UNVERIFIED_DRAFT")
        self.assertEqual(p["model"]["authority"], "NONE")
        self.assertEqual(p["evidence"]["actual_experiment_executed"], False)

    def test_model_exception_does_not_claim_success(self):
        s = snapshot()
        with mock.patch.object(hub, "collect", return_value=s):
            p = phase.run(ask_local_qwen=True,
                          infer=lambda _: (_ for _ in ()).throw(ValueError("SECRET")))
        self.assertEqual(p["model"]["state"], "UNAVAILABLE")
        self.assertNotIn("SECRET", json.dumps(p))

    def test_local_call_proxy_free_bounded_json(self):
        proposed = {"hypothesis": "این فرضیه فقط پیشنهاد آزمایشی محلی است",
                    "test": "این آزمون مصنوعی هنوز به اجرا نرسیده است",
                    "failure_condition": "پاسخ غلط یا غیردقیق آزمون را رد می‌کند"}
        class Response:
            def __init__(self, raw):
                self.raw = raw
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, n):
                self.asserted_limit = n
                return self.raw[:n]
        class Opener:
            def __init__(self):
                self.urls = []
            def __call__(self, req, timeout):
                self.urls.append((req.full_url, timeout))
                body = json.loads(req.data)
                self.prompt = body["prompt"]
                return Response(json.dumps({"done": True,
                    "response": json.dumps(proposed, ensure_ascii=False)}).encode())
        packet = phase.plan(snapshot())
        opener = Opener()
        self.assertEqual(phase.local_question(packet, opener=opener), proposed)
        self.assertEqual(opener.urls, [(phase.LOCAL_URL, 80)])
        self.assertNotIn("EXCLUDED_PRIVATE_VALUE", opener.prompt)

    def test_oversized_local_response_fails(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, _):
                return b"x" * (phase.MAX_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "oversized_response"):
            phase.local_question(phase.plan(snapshot()),
                                 opener=lambda req, timeout: Response())

    def test_nonobject_model_json_fails_closed(self):
        class Response:
            def __init__(self, value):
                self.raw = json.dumps(value).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, _):
                return self.raw
        for value in ([], None, "PRIVATE_MODEL_REPLY", 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    phase.local_question(phase.plan(snapshot()),
                        opener=lambda req, timeout: Response(value))

    def test_local_model_redirect_never_follows_second_request(self):
        paths = []
        proposed = {"hypothesis": "A synthetic hypothesis still unexecuted",
                    "test": "A bounded synthetic test still unexecuted",
                    "failure_condition": "A mismatch falsifies the synthetic claim"}
        class RedirectServer(BaseHTTPRequestHandler):
            def do_POST(self):
                paths.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(302)
                self.send_header("Location", "/escaped")
                self.end_headers()
            def do_GET(self):
                paths.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"done": True,
                    "response": json.dumps(proposed)}).encode())
            def log_message(self, *_args):
                pass
        server = HTTPServer(("127.0.0.1", 0), RedirectServer)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            local_url = "http://127.0.0.1:%s/api/generate" % server.server_port
            with mock.patch.object(phase, "LOCAL_URL", local_url):
                with self.assertRaisesRegex(ValueError, "local_model_redirect_blocked"):
                    phase.local_question(phase.plan(snapshot()))
            self.assertEqual(paths, ["/api/generate"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_local_model_uses_proxy_disabled_opener(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, _):
                return b'{"done":true,"response":"{}"}'
        class Built:
            def open(self, *_args, **_kwargs):
                return Response()
        with mock.patch.object(phase.urllib.request, "build_opener",
                               return_value=Built()) as build:
            with self.assertRaises(ValueError):
                phase.local_question(phase.plan(snapshot()))
        self.assertEqual(len(build.call_args.args), 2)
        self.assertIsInstance(build.call_args.args[0],
                              urllib.request.ProxyHandler)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], phase._NoRedirect)

    def test_real_hub_missing_data_does_not_create_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "nasuraya"
            root.mkdir()
            before = list(root.rglob("*"))
            p = phase.run(home=root)
            self.assertEqual(p["selected"]["id"], "missing_source")
            self.assertEqual(before, list(root.rglob("*")))

    def test_real_hub_structural_awake_is_not_authenticated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "nasuraya"
            p = root / "awake-stage" / "awake.sqlite3"
            p.parent.mkdir(parents=True)
            with sqlite3.connect(p) as db:
                db.executescript("""
                    CREATE TABLE control(name TEXT PRIMARY KEY,value TEXT);
                    CREATE TABLE evidence(id TEXT, topic TEXT, payload TEXT);
                    CREATE TABLE questions(id TEXT, question TEXT);
                    CREATE TABLE ticks(id TEXT);
                    CREATE TABLE ledger(id TEXT);
                    INSERT INTO control VALUES('schema','tadash-awake/1');
                    INSERT INTO control VALUES('paused','1');
                """)
            result = phase.run(home=root)
            self.assertEqual(result["evidence"]["component_states"]["awake"],
                             "structural_only")
            self.assertEqual(result["selected"]["id"], "missing_source")


if __name__ == "__main__":
    unittest.main()
