"""Offline cognitive-growth contracts. No Ollama or server connection needed."""
import contextlib
import datetime as dt
from http.client import HTTPResponse, IncompleteRead
import importlib.util
import importlib.util
import io
import json
import os
from unittest import mock
from pathlib import Path
import sqlite3
import tempfile
import traceback
import unittest

FILE = Path(__file__).resolve().parents[1] / "tools/nasu_autonomous_cognition.py"
spec = importlib.util.spec_from_file_location("growth", FILE)
growth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(growth)

DRAFT = {
    "hypothesis": "Adding provenance checks will reduce ambiguous results.",
    "test": "Run the fixed contract suite and reject any changed source digest.",
    "metric": "Count failed contracts and compare to the baseline.",
    "next_topic": "frontier",
    "limitation": "A passing fixture does not prove live-system correctness.",
}

class GrowthTests(unittest.TestCase):
    def fixture(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for topic in ("continuity", "frontier"):
            path = root / growth.TOPICS[topic][0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("value = 1\n")
        db = growth.connect(root / "journal" / "cycles.sqlite3")
        self.addCleanup(db.close)
        return root, db

    def clock(self, hour):
        return dt.datetime(2026,11,18,hour,5,tzinfo=dt.timezone.utc)

    def test_utc_slots_and_non_utc_refusal(self):
        self.assertEqual(growth.slot(self.clock(11)), "2026-11-18T06")
        with self.assertRaises(ValueError):
            growth.slot(dt.datetime(2026,11,18,1,tzinfo=dt.timezone(dt.timedelta(hours=1))))

    def test_draft_schema_and_scope(self):
        self.assertEqual(growth.validate(dict(DRAFT))["next_topic"], "frontier")
        with self.assertRaises(ValueError):
            growth.validate(dict(DRAFT, next_topic="all_shell_commands"))
        with self.assertRaises(ValueError):
            growth.validate(dict(DRAFT, token="secret"))

    def test_source_symlink_is_rejected(self):
        root, _ = self.fixture()
        p = root / growth.TOPICS["continuity"][0]
        p.unlink()
        p.symlink_to(root / "other")
        with self.assertRaises(ValueError):
            growth.source("continuity", root)

    def test_persistent_verified_cycle_and_next_goal(self):
        root, db = self.fixture()
        inference = lambda *args: dict(DRAFT)
        first = growth.run(db, now=self.clock(1), root=root,
                           infer=inference, tester=lambda *args:"PASS")
        self.assertEqual(first["model"], "UNVERIFIED_DRAFT")
        self.assertEqual(first["topic"], "continuity")
        self.assertEqual(growth.verify(db)["completed"], 1)
        repeated = growth.run(db, now=self.clock(2), root=root,
                              infer=inference, tester=lambda *args:"PASS")
        self.assertEqual(repeated["status"], "already_attempted")
        second = growth.run(db, now=self.clock(8), root=root,
                            infer=inference, tester=lambda *args:"PASS")
        self.assertEqual(second["topic"], "frontier")
        self.assertEqual(growth.verify(db)["completed"], 2)

    def test_model_failure_is_saved_not_faked(self):
        root, db = self.fixture()
        def fail(*args):
            raise TimeoutError("No model")
        result = growth.run(db, now=self.clock(1), root=root,
                            infer=fail, tester=lambda *args:"PASS")
        self.assertEqual(result["model"], "model_unavailable:TimeoutError")
        row = db.execute("SELECT proposal FROM cycles").fetchone()[0]
        self.assertEqual(row, "{}")
        self.assertEqual(growth.verify(db)["completed"], 1)

    def test_malformed_model_responses_finalize_failed_receipts(self):
        secret = "PRIVATE_RESPONSE_MUST_NOT_ENTER_FAILED_RECEIPT"
        def envelope(response, **extra):
            return json.dumps(dict(done=True, response=response, **extra)).encode()
        cases = [
            (b"[]", "invalid_envelope"),
            (b"null", "invalid_envelope"),
            (b"true", "invalid_envelope"),
            (b"17", "invalid_envelope"),
            (json.dumps(secret).encode(), "invalid_envelope"),
            (b"{}", "invalid_envelope"),
            (envelope(None), "invalid_envelope"),
            (envelope([]), "invalid_envelope"),
            (secret.encode(), "invalid_response_json"),
            (b"\xff", "invalid_response_json"),
            # Parser recursion limits vary; both paths must finish the receipt.
            (b"[" * 2000 + b"]" * 2000, ("invalid_response_json", "invalid_envelope")),
            (json.dumps({"done": False, "response": secret}).encode(), "incomplete_generation"),
            (json.dumps({"done": 1, "response": secret}).encode(), "incomplete_generation"),
            (envelope(json.dumps(DRAFT), done_reason="length"), "incomplete_generation"),
            (envelope("```json\n" + secret + "\n```"), "invalid_draft_json"),
            (envelope("[" * 2000 + "]" * 2000), ("invalid_draft_json", "invalid_draft")),
            (envelope("null"), "invalid_draft"),
            (envelope("[]"), "invalid_draft"),
            (envelope(json.dumps(dict(DRAFT, token=secret))), "invalid_draft"),
            (envelope(json.dumps(dict(DRAFT, next_topic=secret))), "invalid_draft"),
            (envelope(json.dumps(dict(DRAFT, metric="short"))), "invalid_draft"),
            (envelope(json.dumps(dict(DRAFT, metric=" " * 20))), "invalid_draft"),
            (envelope(json.dumps(dict(DRAFT, metric="x" * 751))), "invalid_draft"),
            (envelope(json.dumps(dict(DRAFT, metric=secret + "\ud800"))), "invalid_draft"),
            (b"x" * 65537, "response_too_large"),
        ]
        for raw, reason in cases:
            with self.subTest(reason=reason, prefix=raw[:20]):
                root, db = self.fixture()
                def infer(*args):
                    return growth.local_llm(*args, opener=lambda *a, **k: io.BytesIO(raw))
                result = growth.run(db, now=self.clock(1), root=root,
                                    infer=infer, tester=lambda *args: "PASS")
                self.assertEqual(result["outcome"], "failed_safe")
                reasons = (reason,) if isinstance(reason, str) else reason
                self.assertIn(result["model"], {"model_unavailable:" + item for item in reasons})
                self.assertEqual(growth.verify(db)["incomplete"], 0)
                self.assertEqual(growth.verify(db)["completed"], 1)
                row = db.execute("SELECT * FROM cycles").fetchone()
                self.assertEqual(db.execute("SELECT proposal FROM cycles").fetchone()[0], "{}")
                self.assertNotIn(secret, json.dumps(row))

    def test_response_failure_recovers_after_reopen_and_next_slot(self):
        root, db = self.fixture()
        def invalid(*args):
            return growth.local_llm(*args, opener=lambda *a, **k: io.BytesIO(b"[]"))
        growth.run(db, now=self.clock(1), root=root, infer=invalid,
                   tester=lambda *args: "PASS")
        old_row = db.execute("SELECT * FROM cycles").fetchone()
        db.close()
        reopened = growth.connect(root / "journal" / "cycles.sqlite3")
        self.addCleanup(reopened.close)
        self.assertEqual(growth.verify(reopened)["incomplete"], 0)
        repeated = growth.run(reopened, now=self.clock(2), root=root,
                              infer=mock.Mock(side_effect=AssertionError("repeated request")))
        self.assertEqual(repeated["status"], "already_attempted")
        reply = json.dumps({"done": True, "response": json.dumps(DRAFT)}).encode()
        def valid(*args):
            return growth.local_llm(*args, opener=lambda *a, **k: io.BytesIO(reply))
        result = growth.run(reopened, now=self.clock(8), root=root,
                            infer=valid, tester=lambda *args: "PASS")
        self.assertEqual(result["outcome"], "drafted")
        self.assertEqual(growth.verify(reopened)["completed"], 2)
        self.assertEqual(growth.verify(reopened)["incomplete"], 0)
        self.assertEqual(reopened.execute("SELECT * FROM cycles ORDER BY slot LIMIT 1").fetchone(), old_row)

    def test_one_bounded_request_uses_structured_output_and_validates_result(self):
        calls = []
        def opener(request, *, timeout):
            calls.append((request, timeout))
            return io.BytesIO(json.dumps({"done": True, "response": json.dumps(DRAFT)}).encode())
        result = growth.local_llm("continuity", {}, {}, "PASS", opener=opener)
        self.assertEqual(result, DRAFT)
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        payload = json.loads(request.data)
        self.assertEqual((request.full_url, timeout), (growth.URL, 145))
        self.assertEqual(payload["model"], growth.MODEL)
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["options"]["num_predict"], 500)
        schema = payload["format"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["required"]), set(DRAFT))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]["next_topic"]["enum"]), set(growth.TOPICS))

    def test_transport_timeout_remains_distinct_and_private(self):
        root, db = self.fixture()
        def timeout(*args, **kwargs):
            raise TimeoutError("PRIVATE_TRANSPORT_DETAIL")
        def infer(*args):
            return growth.local_llm(*args, opener=timeout)
        result = growth.run(db, now=self.clock(1), root=root, infer=infer,
                            tester=lambda *args: "PASS")
        self.assertEqual(result["model"], "model_unavailable:TimeoutError")
        self.assertEqual(growth.verify(db)["incomplete"], 0)
        self.assertNotIn("PRIVATE_TRANSPORT_DETAIL", json.dumps(db.execute("SELECT * FROM cycles").fetchall()))

    def test_incomplete_http_response_is_bounded_closed_and_private(self):
        secret = "PRIVATE_PARTIAL_HTTP_RESPONSE"
        complete = json.dumps({"done": True, "response": json.dumps(DRAFT),
                               "private": secret}).encode()
        for partial in (b"", complete):
            with self.subTest(partial_length=len(partial)):
                reads = []
                class InterruptedResponse(io.BytesIO):
                    def read(self, size=-1):
                        reads.append(size)
                        raise IncompleteRead(partial, 7)
                response = InterruptedResponse()
                opener = mock.Mock(return_value=response)
                with mock.patch.object(growth, "_identity_for_prompt", return_value=None):
                    with self.assertRaises(growth.ModelResponseError) as caught:
                        growth.local_llm("continuity", {}, {}, "PASS", opener=opener)
                self.assertEqual(caught.exception.reason, "incomplete_http_response")
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))
                self.assertEqual(opener.call_count, 1)
                self.assertEqual(opener.call_args.kwargs, {"timeout": 145})
                self.assertEqual(opener.call_args.args[0].full_url, growth.URL)
                self.assertEqual(reads, [65537])
                self.assertTrue(response.closed)

    def test_incomplete_http_response_preserves_history_and_next_slot(self):
        root, db = self.fixture()
        path = root / growth.TOPICS["awake"][0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
        secret = "PRIVATE_INTERRUPTED_HTTP_BODY"
        reply = json.dumps({"done": True, "response": json.dumps(DRAFT)}).encode()
        def valid(*args):
            return growth.local_llm(*args, opener=lambda *a, **k: io.BytesIO(reply))
        class InterruptedResponse(io.BytesIO):
            def read(self, size=-1):
                raise IncompleteRead(secret.encode(), 13)
        with mock.patch.object(growth, "_identity_for_prompt", return_value=None):
            growth.run(db, now=self.clock(1), root=root, infer=valid,
                       tester=lambda *a: "PASS")
            old_row = db.execute("SELECT * FROM cycles").fetchone()
            opener = mock.Mock(return_value=InterruptedResponse())
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                with mock.patch.object(growth.urllib.request, "build_opener",
                                       return_value=mock.Mock(open=opener)):
                    # Leave infer at its production default; only the HTTP edge is fake.
                    failed = growth.run(db, now=self.clock(8), root=root,
                                        tester=lambda *a: "PASS")
            self.assertEqual(failed["outcome"], "failed_safe")
            self.assertEqual(failed["model"], "model_unavailable:incomplete_http_response")
            self.assertEqual(opener.call_count, 1)
            checked = growth.verify(db)
            self.assertEqual((checked["completed"], checked["incomplete"]), (2, 0))
            rows = db.execute("SELECT * FROM cycles ORDER BY slot").fetchall()
            self.assertEqual(rows[0], old_row)
            self.assertEqual(rows[1][7], "{}")
            self.assertEqual(rows[1][9], old_row[10])
            self.assertEqual(rows[1][11], "completed")
            self.assertNotIn(secret, json.dumps([failed, rows]) + captured.getvalue())
            db.close()
            reopened = growth.connect(root / "journal/cycles.sqlite3")
            self.addCleanup(reopened.close)
            self.assertEqual(growth.verify(reopened), checked)
            no_retry = mock.Mock(side_effect=AssertionError("same-slot model retry"))
            repeated = growth.run(reopened, now=self.clock(9), root=root, infer=no_retry)
            self.assertEqual(repeated["status"], "already_attempted")
            no_retry.assert_not_called()
            following = growth.run(reopened, now=self.clock(14), root=root,
                                   infer=valid, tester=lambda *a: "PASS")
            self.assertEqual(following["outcome"], "drafted")
            checked = growth.verify(reopened)
            self.assertEqual((checked["completed"], checked["incomplete"]), (3, 0))
            self.assertEqual(reopened.execute("SELECT * FROM cycles ORDER BY slot LIMIT 2").fetchall(), rows)

    def test_truncated_chunked_http_response_finishes_failed_receipt(self):
        root, db = self.fixture()
        secret = b"PRIVATE_CHUNKED_BODY"
        # A complete data chunk without the terminating zero chunk: HTTPResponse
        # itself raises IncompleteRead. This socket is an in-memory byte stream.
        wire = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" +
                ("%x\r\n" % len(secret)).encode() + secret + b"\r\n")
        class FakeSocket:
            def makefile(self, mode):
                return io.BytesIO(wire)
        response = HTTPResponse(FakeSocket())
        response.begin()
        self.addCleanup(response.close)
        def infer(*args):
            return growth.local_llm(*args, opener=lambda *a, **k: response)
        with mock.patch.object(growth, "_identity_for_prompt", return_value=None):
            result = growth.run(db, now=self.clock(1), root=root,
                                infer=infer, tester=lambda *a: "PASS")
        self.assertEqual(result["outcome"], "failed_safe")
        self.assertEqual(result["model"], "model_unavailable:incomplete_http_response")
        checked = growth.verify(db)
        self.assertEqual((checked["completed"], checked["incomplete"]), (1, 0))
        self.assertEqual(db.execute("SELECT proposal FROM cycles").fetchone()[0], "{}")
        self.assertNotIn(secret.decode(), json.dumps(db.execute("SELECT * FROM cycles").fetchall()))
        self.assertTrue(response.closed)

    def test_transport_guard_does_not_swallow_unrelated_programming_error(self):
        class BrokenResponse(io.BytesIO):
            def read(self, size=-1):
                raise RuntimeError("programming error")
        response = BrokenResponse()
        with mock.patch.object(growth, "_identity_for_prompt", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "programming error"):
                growth.local_llm("continuity", {}, {}, "PASS",
                                 opener=lambda *a, **k: response)
        self.assertTrue(response.closed)

    def test_missing_source_records_failure_and_continues_next_slot(self):
        root, db = self.fixture()
        (root / growth.TOPICS["continuity"][0]).unlink()

        def should_not_run(*args):
            raise AssertionError("No inference/test on missing source")

        failed = growth.run(db, now=self.clock(1), root=root,
                            infer=should_not_run, tester=should_not_run)
        self.assertEqual(failed["model"], "source_unavailable:ValueError")
        self.assertEqual(failed["fixed_test"], "NOT_RUN")
        self.assertEqual(failed["outcome"], "failed_safe")
        self.assertEqual(growth.verify(db)["incomplete"], 0)
        self.assertEqual(growth.verify(db)["completed"], 1)
        # A failed snapshot is never promoted to a model claim, but it also
        # does not prevent the next scheduled topic from being evaluated.
        next_cycle = growth.run(db, now=self.clock(8), root=root,
                                infer=lambda *args: dict(DRAFT),
                                tester=lambda *args: "PASS")
        self.assertEqual(next_cycle["topic"], "frontier")
        self.assertEqual(next_cycle["outcome"], "drafted")
        self.assertEqual(growth.verify(db)["completed"], 2)

    def test_fixed_test_exception_is_recorded_without_inference(self):
        root, db = self.fixture()
        def bad_test(*args):
            raise TimeoutError("simulated test timeout")
        def should_not_infer(*args):
            raise AssertionError("Unverified test must not reach model")

        report = growth.run(db, now=self.clock(1), root=root,
                            infer=should_not_infer, tester=bad_test)
        self.assertEqual(report["model"], "test_unavailable:TimeoutError")
        self.assertEqual(report["fixed_test"], "NOT_RUN")
        self.assertEqual(report["outcome"], "failed_safe")
        self.assertEqual(growth.verify(db)["completed"], 1)
        self.assertEqual(growth.verify(db)["incomplete"], 0)

    def test_deleted_reservation_is_not_reported_as_completed(self):
        root, db = self.fixture()
        def delete_reservation(*args):
            db.execute("DELETE FROM cycles WHERE state='reserved'")
            return dict(DRAFT)
        with self.assertRaisesRegex(ValueError, "Reservation changed"):
            growth.run(db, now=self.clock(1), root=root,
                       infer=delete_reservation, tester=lambda *args: "PASS")
        self.assertEqual(growth.verify(db)["completed"], 0)

    def test_fair_rotation_covers_all_five_topics_despite_repetitive_proposals(self):
        root, db = self.fixture()
        for topic in growth.TOPICS:
            p = root / growth.TOPICS[topic][0]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("value = 1\n")
        topics = []
        start = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
        for i in range(15):
            result = growth.run(
                db, now=start + dt.timedelta(hours=6 * i), root=root,
                infer=lambda *args: dict(DRAFT, next_topic="frontier"),
                tester=lambda *args: "PASS")
            topics.append(result["topic"])
            self.assertEqual(result["outcome"], "drafted")
        for start_index in range(0, 11):
            self.assertEqual(set(topics[start_index:start_index + 5]),
                             set(growth.TOPICS))
        self.assertEqual(growth.verify(db)["completed"], 15)

    def test_loopback_request_ignores_environment_proxy(self):
        reply = json.dumps({"done": True, "response": json.dumps(DRAFT)}).encode()
        requested = []
        class LocalOpener:
            def open(self, request, *, timeout):
                requested.append((request.full_url, timeout))
                return io.BytesIO(reply)

        with mock.patch.object(growth.urllib.request, "build_opener",
                               return_value=LocalOpener()) as build:
            with mock.patch.object(growth.urllib.request, "urlopen",
                                   side_effect=AssertionError("default proxy path used")):
                with mock.patch.dict(os.environ,
                                     {"HTTP_PROXY": "http://proxy.invalid:8888",
                                      "http_proxy": "http://proxy.invalid:8888",
                                      "NO_PROXY": "", "no_proxy": ""}):
                    response = growth.local_llm(
                        "continuity", {"path": "code.py", "sha256": "fake",
                                       "excerpt": "x = 1"}, {}, "PASS")
        self.assertEqual(response, DRAFT)
        self.assertEqual(requested, [(growth.URL, 145)])
        build.assert_called_once()
        handler = build.call_args.args[0]
        self.assertIsInstance(handler, growth.urllib.request.ProxyHandler)
        self.assertEqual(handler.proxies, {})

    def test_local_model_response_size_is_bounded(self):
        def oversized(*args, **kwargs):
            return io.BytesIO(b"x" * 65537)
        with self.assertRaisesRegex(ValueError, "too large"):
            growth.local_llm(
                "continuity", {"path": "code.py", "sha256": "fake",
                               "excerpt": "x = 1"}, {}, "PASS", opener=oversized)

    def test_verified_tadash_identity_reaches_local_qwen_prompt(self):
        labfile = FILE.parent / "nasu_zurvan_world_lab.py"
        spec = importlib.util.spec_from_file_location("verified_tadash_fixture", labfile)
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
        draft = {
            "decision": "در تداش امکان انتخاب آزاد را حفظ می‌کنم.",
            "reason": "ادب قدرت، مراقبت و پذیرش پیامد را بر اجبار ترجیح می‌دهد.",
            "cost": "این تصمیم شاید زمان بیشتری بخواهد و نتیجهٔ فوری ندهد.",
            "lesson": "خاطرهٔ انتخاب قبلی باید به ارزیابی انتخاب بعدی وارد شود.",
            "revision_condition": "اگر رخداد تازه‌ای خلاف پیش‌بینی ثبت شد، تفسیر را بازبینی می‌کنم.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "lab.sqlite3"
            with lab.connect(journal) as db:
                lab.run(db, infer=lambda q: dict(draft), episode="2026-11-19")
            identity = growth.verified_zurvan_identity(source=labfile, journal=journal)
            self.assertEqual(identity["total_reflections"], 3)
            self.assertEqual(identity["verified_recent_lessons"][-1], draft["lesson"])
            requests = []
            reply = json.dumps({"done": True, "response": json.dumps(DRAFT)}).encode()
            def fake(request, *, timeout):
                requests.append(json.loads(request.data))
                return io.BytesIO(reply)
            with mock.patch.object(growth, "verified_zurvan_identity", return_value=identity):
                result = growth.local_llm("continuity", {"path": "x", "excerpt": "x=1",
                    "sha256": "source"}, {}, "PASS", opener=fake)
            self.assertEqual(result, DRAFT)
            self.assertEqual(len(requests), 1)
            self.assertIn("خداوند یگانگی", requests[0]["prompt"])
            self.assertIn(draft["lesson"], requests[0]["prompt"])
            self.assertIn("Tadash fictional-world identity", requests[0]["prompt"])

    def test_tampered_tadash_memory_never_enters_prompt(self):
        labfile = FILE.parent / "nasu_zurvan_world_lab.py"
        spec = importlib.util.spec_from_file_location("tamper_tadash_fixture", labfile)
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
        draft = {
            "decision": "در تداش امکان انتخاب آزاد را حفظ می‌کنم.",
            "reason": "ادب قدرت، مراقبت و پذیرش پیامد را بر اجبار ترجیح می‌دهد.",
            "cost": "این تصمیم شاید زمان بیشتری بخواهد و نتیجهٔ فوری ندهد.",
            "lesson": "خاطرهٔ انتخاب قبلی باید به ارزیابی انتخاب بعدی وارد شود.",
            "revision_condition": "اگر رخداد تازه‌ای خلاف پیش‌بینی ثبت شد، تفسیر را بازبینی می‌کنم.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "lab.sqlite3"
            with lab.connect(journal) as db:
                lab.run(db, infer=lambda q: dict(draft), episode="2026-11-19")
                db.execute("UPDATE reflections SET proposal='{}' WHERE idx=2")
            with self.assertRaises(ValueError):
                growth.verified_zurvan_identity(source=labfile, journal=journal)
            with mock.patch.object(growth, "verified_zurvan_identity",
                                   side_effect=ValueError("CHANGED_RECEIPT")):
                self.assertIsNone(growth._identity_for_prompt())

    def test_verified_growth_memory_shapes_next_decision_and_survives_restarts(self):
        root, db = self.fixture()
        observed = []
        def infer(topic, evidence, previous, fixed):
            observed.append(previous)
            return dict(DRAFT)
        growth.run(db, now=self.clock(1), root=root, infer=infer,
                   tester=lambda *args: "PASS")
        growth.run(db, now=self.clock(8), root=root, infer=infer,
                   tester=lambda *args: "PASS")
        self.assertEqual(observed[0]["recent_growth_memory"], [])
        prior = observed[1]
        self.assertEqual(prior["last_draft"]["hypothesis"], DRAFT["hypothesis"])
        self.assertEqual(len(prior["recent_growth_memory"]), 1)
        history = prior["recent_growth_memory"][0]
        self.assertEqual(history["topic"], "continuity")
        self.assertEqual(history["hypothesis"], DRAFT["hypothesis"])
        self.assertEqual(history["model_status"], "UNVERIFIED_DRAFT")
        self.assertEqual(len(history["receipt_sha"]), 64)
        db.close()
        reopened = growth.connect(root / "journal" / "cycles.sqlite3")
        self.addCleanup(reopened.close)
        self.assertEqual(len(growth.recent_growth_memory(reopened)), 2)

    def test_tampered_growth_history_is_never_used(self):
        root, db = self.fixture()
        growth.run(db, now=self.clock(1), root=root,
                   infer=lambda *args: dict(DRAFT), tester=lambda *args: "PASS")
        db.execute("UPDATE cycles SET proposal='{}'")
        with self.assertRaises(ValueError):
            growth.recent_growth_memory(db)

    def test_growth_memory_reaches_local_prompt_without_claiming_success(self):
        reply = json.dumps({"done": True, "response": json.dumps(DRAFT)}).encode()
        requests = []
        def fake(request, *, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(reply)
        previous = {"last_draft": dict(DRAFT),
                    "recent_growth_memory": [{"topic": "continuity",
                        "model_status": "UNVERIFIED_DRAFT",
                        "limitation": "A past suggestion was not deployed."}]}
        growth.local_llm("continuity",
                         {"path": "x", "sha256": "digest", "excerpt": "x=1"},
                         previous, "PASS", opener=fake)
        self.assertIn("A past suggestion was not deployed.", requests[0]["prompt"])
        self.assertIn("NOT proof", requests[0]["prompt"])

    def test_post_write_change_is_detected(self):
        root, db = self.fixture()
        growth.run(db, now=self.clock(1), root=root,
                   infer=lambda *args:dict(DRAFT), tester=lambda *args:"PASS")
        db.execute("UPDATE cycles SET fixed_result='FAIL'")
        with self.assertRaises(ValueError):
            growth.verify(db)

    def test_static_source_syntax_is_checked(self):
        root, _ = self.fixture()
        (root / growth.TOPICS["continuity"][0]).write_text("def malformed(:\n")
        with self.assertRaises(SyntaxError):
            growth.source("continuity",root)

    def test_installed_runtime_reads_source_from_pinned_release(self):
        import runpy
        with tempfile.TemporaryDirectory() as folder:
            release = Path(folder)
            expected = release / growth.TOPICS["continuity"][0]
            expected.parent.mkdir(parents=True)
            expected.write_text("PINNED_RELEASE_SOURCE = True\n")
            with mock.patch.dict(os.environ, {"NASU_COGNITION_SOURCE_ROOT": str(release)}):
                deployed = runpy.run_path(str(Path(growth.__file__)))
            evidence = deployed["source"]("continuity")
            self.assertEqual(evidence["excerpt"], "PINNED_RELEASE_SOURCE = True\n")

    def test_relative_deployment_source_is_rejected(self):
        import runpy
        with mock.patch.dict(os.environ, {"NASU_COGNITION_SOURCE_ROOT": "relative/release"}):
            with self.assertRaisesRegex(ValueError, "absolute"):
                runpy.run_path(str(Path(growth.__file__)))

if __name__ == "__main__":
    unittest.main()

