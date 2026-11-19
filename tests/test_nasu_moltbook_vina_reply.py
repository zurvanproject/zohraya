"""Offline checks: one approved comment, no credentials or live writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("memory_reply_vina", Path(__file__).resolve().parents[1] /
                                            "tools/bridge_jobs/nasu_moltbook_vina_reply.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
IDENT = "11111111-2222-3333-4444-555555555555"


def comment(**changes):
    c = {"id": IDENT, "post_id": m.POST_ID, "content": m.BODY,
         "author": {"name": "nasuraya"}, "replies": [],
         "is_deleted": False, "is_spam": False, "verification_status": "verified"}
    c.update(changes)
    return c


class FakeClient:
    def __init__(self, existing=None, failure=False, pending=False):
        self.existing = existing or []
        self.failure = failure
        self.pending = pending
        self.writes = 0

    def request(self, method, route, data=None):
        if route == "/api/v1/agents/status":
            return {"status": "claimed"}
        if route == "/api/v1/agents/me":
            return {"agent": {"name": "nasuraya"}}
        if method == "GET":
            return {"post_id": m.POST_ID, "comments": self.existing, "has_more": False}
        assert route == m.ROUTE and data == {"content": m.BODY}
        self.writes += 1
        if self.failure:
            raise TimeoutError("synthetic timeout after possible side effect")
        c = comment(verification_status="pending" if self.pending else "verified")
        self.existing = [c]
        return {"comment": c, "verification": {"challenge_text": "private challenge"}}


class VinaReplyTests(unittest.TestCase):
    def test_approved_fixed_post_and_research_question(self):
        self.assertEqual(m.POST_ID, "cd56ed15-de54-466b-8f92-23874f848c85")
        self.assertEqual(m.ROUTE, "/api/v1/posts/" + m.POST_ID + "/comments")
        self.assertIn("160/160 authored synthetic", m.BODY)
        self.assertIn("bounded stale window", m.BODY)
        self.assertNotIn("sk-proj", m.BODY)
        self.assertLessEqual(len(m.BODY), 1800)

    def test_one_write_and_independent_read(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            self.assertEqual(m.publish(client, Path(d)), "COMMENT_VERIFIED=" + IDENT)
            self.assertEqual(m.publish(client, Path(d)), "COMMENT_VERIFIED=" + IDENT)
            self.assertEqual(client.writes, 1)
            self.assertEqual(json.loads((Path(d) / "memory_reply_vina.json").read_text())["state"], "verified")

    def test_existing_nested_comment_is_not_reposted(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(existing=[{"content": "other", "replies": [comment()]}])
            self.assertEqual(m.publish(client, Path(d)), "COMMENT_VERIFIED=" + IDENT)
            self.assertEqual(client.writes, 0)

    def test_timeout_never_retries(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(failure=True)
            with self.assertRaises(TimeoutError):
                m.publish(client, Path(d))
            self.assertEqual(m.publish(client, Path(d)), "REVIEW_REQUIRED")
            self.assertEqual(client.writes, 1)

    def test_pending_is_not_claimed_as_published(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(pending=True)
            self.assertEqual(m.publish(client, Path(d)), "COMMENT_PENDING=" + IDENT)
            self.assertEqual(m.publish(client, Path(d)), "COMMENT_PENDING=" + IDENT)
            self.assertEqual(client.writes, 1)

    def test_deleted_and_spam_do_not_allow_republication(self):
        for changes in ({"is_deleted": True}, {"is_spam": True}, {"verification_status": None}):
            with tempfile.TemporaryDirectory() as d:
                client = FakeClient(existing=[comment(**changes)])
                self.assertEqual(m.publish(client, Path(d)), "COMMENT_PENDING=" + IDENT)
                self.assertEqual(client.writes, 0)

    def test_wrong_account_stops_before_writing(self):
        class WrongAccount(FakeClient):
            def request(self, method, route, data=None):
                if route == "/api/v1/agents/me":
                    return {"agent": {"name": "other"}}
                return super().request(method, route, data)
        with tempfile.TemporaryDirectory() as d:
            client = WrongAccount()
            self.assertEqual(m.publish(client, Path(d)), "ACCOUNT_MISMATCH")
            self.assertEqual(client.writes, 0)

    def test_crash_lock_stops_new_execution(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "memory_reply_vina.lock").mkdir()
            client = FakeClient()
            self.assertEqual(m.publish(client, Path(d)), "REVIEW_REQUIRED")
            self.assertEqual(client.writes, 0)

    def test_incomplete_pagination_stops_before_writing(self):
        class Truncated(FakeClient):
            def request(self, method, route, data=None):
                if method == "GET" and route.startswith(m.ROUTE):
                    return {"post_id": m.POST_ID, "comments": [], "has_more": True}
                return super().request(method, route, data)
        with tempfile.TemporaryDirectory() as d:
            client = Truncated()
            with self.assertRaises(ValueError):
                m.publish(client, Path(d))
            self.assertEqual(client.writes, 0)

    def test_client_denies_other_content_or_routes(self):
        client = m.Client("synthetic-key-never-transmitted")
        for route, data in ((m.ROUTE, {"content": "changed"}),
                            ("/api/v1/posts", {"content": m.BODY}),
                            ("https://example.com", {"content": m.BODY})):
            with self.assertRaises(ValueError):
                client.request("POST", route, data)

    def test_expiry_is_bounded_and_timezone_aware(self):
        from datetime import datetime, timezone
        self.assertIsNotNone(m.EXPIRES_AT_UTC.tzinfo)
        self.assertEqual(m.EXPIRES_AT_UTC, datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
