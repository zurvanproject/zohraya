"""Offline transport and evidence contracts; no network or credentials."""
import copy
import datetime as dt
import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
import urllib.error

from tools import nasu_collect_project_status as collector
from tools import nasu_project_integration as integration

NOW = dt.datetime(2026, 11, 22, 13, 10, tzinfo=dt.timezone.utc)
STAMP = "2026-11-22T13:10:00Z"
SHA = "a" * 40
POST = "12345678-1234-1234-1234-123456789abc"
SECRET = "private-marker-never-emit"


class Response(io.BytesIO):
    def __init__(self, url, data, headers=None, code=200):
        super().__init__(data)
        self.url = url
        self.code = code
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def getcode(self):
        return self.code

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, data=b"{}", headers=None, returned_url=None, failure=None):
        self.data, self.headers, self.returned_url, self.failure = data, headers, returned_url, failure
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.failure:
            raise self.failure
        return Response(self.returned_url or request.full_url, self.data, self.headers)


class FixtureClient:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def get(self, url):
        if not collector.allowed_url(url):
            raise AssertionError("unexpected endpoint")
        record = {"source_url": url, "method": "GET", "started_at_utc": STAMP,
                  "acquired_at_utc": STAMP, "status": "ok"}
        self.requests.append(record)
        value = self.responses[url]
        if isinstance(value, Exception):
            record.update(status="error", error_class=type(value).__name__)
            raise value
        return copy.deepcopy(value), dict(record)


def row(ident, body):
    return {"id": ident, "body": body, "created_at": "2026-11-22T13:04:25Z",
            "html_url": collector.WEB + "/issues/212#issuecomment-" + str(ident),
            "updated_at": "2026-11-22T13:04:25Z", "user": {"login": "zurvanproject", "email": SECRET}}


def diagnostics():
    return {"schema": "nasuraya-agent-diagnostics/1", "utc": "2026-11-22T13:04:25Z",
            "mode": "status", "units": {key: {"state": "unavailable"} for key in integration.UNITS},
            "cognition": {"state": "missing"}, "integration": {"state": "missing"},
            "executables": {"installed": "missing", "release": "missing", "match": None}}


def receipt(ident=10, action="agent-status", value=None, payload=None):
    if payload is None:
        payload = json.dumps(diagnostics() if value is None else value, separators=(",", ":"))
    return ("nasu-linux-result request_id=" + str(ident) + "\naction=" + action
            + "; utc=2026-11-22T13:04:25Z\nhost=ubuntu-iran; result:\n"
            + collector.FENCE + "text\nexit=0\n" + payload + "\n" + collector.FENCE)


def pr(number):
    return {"number": number, "state": "open", "draft": True,
            "html_url": collector.WEB + "/pull/" + str(number),
            "head": {"sha": SHA}, "updated_at": STAMP, "body": SECRET}


def fixtures():
    return {
        collector.MAIN_URL: {"name": "main", "commit": {"sha": SHA}},
        collector.pr_url(1): [pr(1)],
        collector.RUNS_URL: {"workflow_runs": [{"id": 7, "workflow_id": 99, "name": "CI",
            "html_url": collector.WEB + "/actions/runs/7", "status": "completed",
            "conclusion": "success", "head_sha": SHA, "updated_at": STAMP, "actor": SECRET}]},
        collector.ISSUE_URL: {"number": 212, "html_url": collector.WEB + "/issues/212", "comments": 2},
        collector.comments_url(1): [row(10, "nasu-linux: agent-status"), row(11, receipt())],
        collector.PROFILE_URL: {"success": True, "agent": {"name": "nasuraya", "is_active": True,
            "is_claimed": True, "last_active": "2026-11-14T10:37:32Z", "posts_count": 0,
            "owner": {"email": SECRET}}, "recentPosts": []},
        collector.FEED_URL: {"success": True, "has_more": True, "posts": [
            {"id": POST, "title": "Public title", "created_at": "2026-11-22T13:09:00Z", "content": SECRET}]},
    }


class TransportTests(unittest.TestCase):
    def test_credential_free_managed_proxies_are_retained(self):
        proxy = "http://managed-proxy.example:3128"
        with patch.object(collector.urllib.request, "getproxies", return_value={
            "http": proxy, "https": proxy, "all": "ignored-scheme://ignored.example"}), \
                patch.object(collector.urllib.request, "build_opener", return_value=Opener()) as build:
            collector.PublicClient()
        self.assertEqual(build.call_args.args[0].proxies, {"http": proxy, "https": proxy})

    def test_authenticated_or_non_origin_proxy_configuration_is_refused(self):
        for proxy in ("http://user:" + SECRET + "@proxy.example:3128", "http://proxy.example?token=" + SECRET,
                      "https://proxy.example/#" + SECRET, "socks5://proxy.example:1080",
                      "http://proxy.example/private", "http://proxy.example:99999", "http://proxy.example\n"):
            with patch.object(collector.urllib.request, "getproxies", return_value={"https": proxy}), \
                    patch.object(collector.urllib.request, "build_opener") as build:
                with self.assertRaisesRegex(ValueError, "^unsafe_proxy_configuration$"):
                    collector.PublicClient()
                build.assert_not_called()

    def test_allowlist_is_exact(self):
        for url in (collector.MAIN_URL, collector.pr_url(10), collector.comments_url(10000)):
            self.assertTrue(collector.allowed_url(url))
        for url in (collector.pr_url(11), collector.PROFILE_URL + "&token=x", collector.MAIN_URL + "#x",
                    collector.MAIN_URL.replace("https:", "http:"), collector.MAIN_URL.replace("api.github.com", "evil.example"),
                    collector.API + "/issues/212/comments", "https://api.github.com@evil.example/", 3):
            self.assertFalse(collector.allowed_url(url))

    def test_get_only_no_auth_headers(self):
        opener = Opener()
        client = collector.PublicClient(opener=opener, now=lambda: NOW)
        with patch.dict("os.environ", {"GITHUB_TOKEN": SECRET, "MOLTBOOK_API_KEY": SECRET}):
            data, metadata = client.get(collector.MAIN_URL)
        request, timeout = opener.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertNotIn("Authorization", dict(request.header_items()))
        self.assertNotIn(SECRET, str(request.header_items()))
        self.assertLessEqual(timeout, collector.TIMEOUT_SECONDS)
        self.assertEqual(metadata["acquired_at_utc"], "2026-11-22T13:10:00Z")
        self.assertEqual(len(metadata["response_sha256"]), 64)
        self.assertEqual(data, {})

    def test_redirect_handler_and_changed_response_url_refused(self):
        body = io.BytesIO(b"unused")
        with self.assertRaises(collector.RedirectRefused):
            collector.NoRedirect().redirect_request(None, body, 302, "", {}, "https://evil.example")
        self.assertTrue(body.closed)
        client = collector.PublicClient(opener=Opener(returned_url="https://evil.example"))
        with self.assertRaises(collector.RedirectRefused):
            client.get(collector.MAIN_URL)

    def test_declared_and_actual_size_bound(self):
        for opener in (Opener(headers={"Content-Length": str(collector.MAX_RESPONSE_BYTES + 1)}),
                       Opener(data=b" " * (collector.MAX_RESPONSE_BYTES + 1))):
            with self.assertRaises(collector.ResponseTooLarge):
                collector.PublicClient(opener=opener).get(collector.MAIN_URL)

    def test_non_json_duplicate_keys_and_nonfinite_rejected(self):
        for opener in (Opener(headers={"Content-Type": "text/html"}), Opener(data=b'{"x":1,"x":2}'),
                       Opener(data=b'{"x":NaN}'), Opener(data=b"not JSON")):
            with self.assertRaises(ValueError):
                collector.PublicClient(opener=opener).get(collector.MAIN_URL)

    def test_request_budget_and_deadline(self):
        client = collector.PublicClient(opener=Opener())
        for _ in range(collector.MAX_REQUESTS):
            client.get(collector.MAIN_URL)
        with self.assertRaises(collector.CollectionLimit):
            client.get(collector.MAIN_URL)
        clock = [0]
        client = collector.PublicClient(opener=Opener(), monotonic=lambda: clock[0])
        clock[0] = collector.TOTAL_SECONDS
        with self.assertRaises(collector.CollectionLimit):
            client.get(collector.MAIN_URL)

    def test_error_message_is_not_recorded(self):
        failure = urllib.error.HTTPError(collector.MAIN_URL, 403, SECRET, {}, None)
        client = collector.PublicClient(opener=Opener(failure=failure))
        with self.assertRaises(urllib.error.HTTPError):
            client.get(collector.MAIN_URL)
        self.assertNotIn(SECRET, json.dumps(client.requests))
        self.assertEqual(client.requests[0]["error_class"], "HTTPError")
        self.assertEqual(client.requests[0]["http_status"], 403)


class CollectionTests(unittest.TestCase):
    def collect(self, responses=None):
        return collector.collect(client=FixtureClient(fixtures() if responses is None else responses), now=lambda: NOW)

    def test_compatible_bundle_and_only_metadata_emitted(self):
        bundle = self.collect()
        self.assertEqual(bundle["collection"]["status"], "complete")
        self.assertNotIn(SECRET, json.dumps(bundle))
        self.assertEqual(bundle["github"]["workflow_runs"][0]["workflow_id"], 99)
        self.assertTrue(bundle["github"]["pull_requests_complete"])
        self.assertFalse(bundle["github"]["workflow_coverage"]["complete_history"])
        self.assertFalse(bundle["server"]["collection_coverage"]["full_history_verified"])
        output = integration.assemble(bundle, now=NOW)
        self.assertEqual(output["components"]["server"]["state"], "observed")
        self.assertEqual(output["components"]["moltbook"]["runtime_linkage"], "UNKNOWN")
        self.assertEqual(output["components"]["moltbook"]["profile"]["activity_freshness"]["state"], "stale")

    def test_moltbook_is_prefetched_once_before_pagination(self):
        bundle = self.collect()
        urls = [r["source_url"] for r in bundle["collection"]["requests"]]
        self.assertEqual(urls[:3], [collector.MAIN_URL, collector.PROFILE_URL, collector.FEED_URL])
        self.assertEqual(urls.count(collector.PROFILE_URL), 1)
        self.assertEqual(urls.count(collector.FEED_URL), 1)

    def test_old_unmatched_receipts_do_not_force_more_tail_pages(self):
        data = fixtures()
        data[collector.ISSUE_URL]["comments"] = 500
        research = {"schema": "nasuraya-bridge-research/1", "state": "completed",
                    "completed": 16, "correct": 9, "errors": 0, "last_sha": "c" * 64,
                    "task_issue": 290, "total": 16, "valid": 16}
        old = row(9, receipt(9999))
        old.update(created_at="2026-11-21T13:04:25Z", updated_at="2026-11-21T13:04:25Z")
        data[collector.comments_url(5)] = [old, row(10, "nasu-linux: agent-status"), row(11, receipt()),
            row(20, "nasu-linux: repo"), row(21, receipt(20, "repo", payload="## main...origin/main\nexit=0\nabcdef1")),
            row(30, "nasu-linux: research-status"), row(31, receipt(30, "research-status", value=research))]
        bundle = self.collect(data)
        scope = bundle["server"]["collection_coverage"]
        self.assertEqual(scope["pages_observed"], [5])
        self.assertEqual(scope["linked_request_ids_missing"], [9999])
        self.assertTrue(scope["latest_relevant_groups_resolved"])
        self.assertTrue(scope["truncated"])
        urls = [r["source_url"] for r in bundle["collection"]["requests"]]
        self.assertNotIn(collector.comments_url(4), urls)
        self.assertIn("feed", bundle["moltbook"])

    def test_latest_pending_requests_are_sufficient_current_events(self):
        data = fixtures()
        data[collector.ISSUE_URL]["comments"] = 500
        old = row(9, receipt(9999))
        old.update(created_at="2026-11-21T13:04:25Z", updated_at="2026-11-21T13:04:25Z")
        data[collector.comments_url(5)] = [old, row(10, "nasu-linux: agent-probe"),
            row(20, "nasu-linux: repo"), row(30, "nasu-linux: research-status")]
        bundle = self.collect(data)
        self.assertEqual(bundle["server"]["collection_coverage"]["pages_observed"], [5])
        self.assertEqual(integration.assemble(bundle, now=NOW)["components"]["server"]["state"], "awaiting_receipt")

    def test_partial_network_failure_retains_other_components(self):
        data = fixtures()
        data[collector.MAIN_URL] = TimeoutError(SECRET)
        bundle = self.collect(data)
        self.assertNotIn("github", bundle)
        self.assertEqual(bundle["collection"]["status"], "partial")
        self.assertIn("server", bundle)
        self.assertIn("moltbook", bundle)
        self.assertNotIn(SECRET, json.dumps(bundle))
        self.assertEqual(bundle["collection"]["errors"][0]["error_class"], "TimeoutError")

    def test_pr_pagination_and_limits_are_explicit(self):
        data = fixtures()
        for page in range(1, 11):
            data[collector.pr_url(page)] = [pr((page - 1) * 100 + i) for i in range(1, 101)]
        bundle = self.collect(data)
        self.assertEqual(len(bundle["github"]["pull_requests"]), 1000)
        self.assertFalse(bundle["github"]["pull_requests_complete"])
        self.assertEqual(bundle["collection"]["status"], "partial")
        self.assertEqual(bundle["github"]["pull_request_coverage"]["pages_observed"], 10)
        self.assertNotIn(collector.pr_url(11), [r["source_url"] for r in bundle["collection"]["requests"]])

    def test_pr_rejection_and_duplicates_prevent_complete_claim(self):
        data = fixtures()
        data[collector.pr_url(1)] = [pr(1), pr(1), {"number": "bad"}]
        bundle = self.collect(data)
        self.assertEqual(len(bundle["github"]["pull_requests"]), 1)
        self.assertFalse(bundle["github"]["pull_requests_complete"])
        self.assertEqual(bundle["github"]["pull_request_coverage"]["rejected_rows"], 1)

    def test_comment_tail_is_bounded_and_fetches_missing_request(self):
        data = fixtures()
        data[collector.ISSUE_URL]["comments"] = 1020
        for page in (7, 8, 9, 10, 11):
            data[collector.comments_url(page)] = []
        data[collector.comments_url(11)] = [row(11, receipt())]
        data[collector.comments_url(9)] = [row(10, "nasu-linux: agent-status")]
        bundle = self.collect(data)
        scope = bundle["server"]["collection_coverage"]
        self.assertEqual(scope["pages_observed"], [11, 10, 9, 8, 7])
        self.assertEqual(scope["linked_request_ids_missing"], [])
        self.assertTrue(scope["truncated"])
        self.assertEqual(integration.assemble(bundle, now=NOW)["components"]["server"]["state"], "observed")

    def test_missing_request_is_reported_not_invented(self):
        data = fixtures()
        data[collector.comments_url(1)] = [row(11, receipt())]
        bundle = self.collect(data)
        self.assertEqual(bundle["server"]["collection_coverage"]["linked_request_ids_missing"], [10])
        self.assertEqual(integration.assemble(bundle, now=NOW)["components"]["server"]["health"], "unknown")

    def test_invalid_receipt_remains_linked_without_raw_payload(self):
        data = fixtures()
        bad = diagnostics()
        bad["private"] = SECRET
        data[collector.comments_url(1)][1]["body"] = receipt(value=bad)
        bundle = self.collect(data)
        self.assertNotIn(SECRET, json.dumps(bundle))
        self.assertIn("INVALID_RECEIPT_METADATA", bundle["server"]["comments"][1]["body"])
        self.assertEqual(integration.assemble(bundle, now=NOW)["components"]["server"]["state"], "invalid_receipt")

    def test_cross_issue_source_is_rejected_not_relabelled(self):
        data = fixtures()
        data[collector.comments_url(1)][1]["html_url"] = collector.WEB + "/issues/149#issuecomment-11"
        bundle = self.collect(data)
        self.assertEqual(bundle["server"]["collection_coverage"]["rejected_rows"], 1)
        self.assertEqual([r["id"] for r in bundle["server"]["comments"]], [10])
        self.assertNotIn("#issuecomment-11", json.dumps(bundle))

    def test_duplicate_receipts_and_unrelated_logs(self):
        data = fixtures()
        data[collector.comments_url(1)] += [row(12, receipt()), row(13, SECRET),
            row(14, "nasu-linux: migration-export " + SECRET)]
        bundle = self.collect(data)
        self.assertNotIn(SECRET, json.dumps(bundle))
        self.assertEqual(len(bundle["server"]["comments"]), 3)
        self.assertEqual(integration.assemble(bundle, now=NOW)["components"]["server"]["state"], "ambiguous_receipts")

    def test_wrong_action_for_known_request_is_invalid_not_pending(self):
        data = fixtures()
        data[collector.comments_url(1)][1]["body"] = receipt(action="private-export", payload=SECRET)
        bundle = self.collect(data)
        self.assertNotIn(SECRET, json.dumps(bundle))
        self.assertEqual(integration.assemble(bundle, now=NOW)["components"]["server"]["state"], "invalid_receipt")

    def test_repo_paths_are_redacted(self):
        data = fixtures()
        data[collector.comments_url(1)] += [row(20, "nasu-linux: repo"),
            row(21, receipt(20, "repo", payload="## main...origin/main\n M " + SECRET + "\nexit=0\nabcdef1"))]
        bundle = self.collect(data)
        self.assertNotIn(SECRET, json.dumps(bundle))
        result = integration.assemble(bundle, now=NOW)
        self.assertEqual(result["components"]["server"]["related_receipts"]["repo"]["worktree_changes_observed"], 1)

    def test_profile_wrong_identity_and_missing_recent_posts(self):
        data = fixtures()
        del data[collector.PROFILE_URL]["recentPosts"]
        self.assertIsNone(self.collect(data)["moltbook"]["public_profile"]["recentPosts"])
        data[collector.PROFILE_URL]["agent"]["name"] = "someone_else"
        self.assertNotIn("moltbook", self.collect(data))

    def test_cli_report_preserves_collection_scope(self):
        out = io.StringIO()
        with patch.object(collector, "collect", return_value=self.collect()), redirect_stdout(out):
            self.assertEqual(collector.main(["--report"]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["schema"], integration.SCHEMA)
        self.assertEqual(result["collection"]["mode"], "PUBLIC_GET_ONLY")
        self.assertFalse(result["collection"]["full_ci_or_issue_history_verified"])

    def test_cli_errors_do_not_echo_messages(self):
        out = io.StringIO()
        with patch.object(collector, "collect", side_effect=RuntimeError(SECRET)), redirect_stderr(out):
            self.assertEqual(collector.main([]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"ok": False, "error_class": "RuntimeError"})

    def test_all_sources_unavailable_keeps_report_and_nonzero_exit(self):
        data = fixtures()
        for url in (collector.MAIN_URL, collector.ISSUE_URL, collector.PROFILE_URL, collector.FEED_URL):
            data[url] = urllib.error.URLError(SECRET)
        bundle = self.collect(data)
        self.assertEqual(bundle["collection"]["status"], "unavailable")
        self.assertEqual(bundle["collection"]["available_components"], [])
        self.assertNotIn(SECRET, json.dumps(bundle))
        out = io.StringIO()
        with patch.object(collector, "collect", return_value=bundle), redirect_stdout(out):
            self.assertEqual(collector.main(["--report"]), 2)
        report = json.loads(out.getvalue())
        self.assertEqual(report["collection"]["status"], "unavailable")
        self.assertEqual(report["components"]["github"]["state"], "missing_evidence")


if __name__ == "__main__":
    unittest.main()
