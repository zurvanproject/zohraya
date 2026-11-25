"""Project evidence contracts. All inputs are local fixtures; no live services."""
import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import nasu_project_integration as hub


NOW = dt.datetime(2026, 11, 22, 13, 10, tzinfo=dt.timezone.utc)
SECRET = "PRIVATE_RAW_TEXT_MUST_NOT_BECOME_A_COMMAND_OR_REPORT"
HEAD = "f8bbe739c9b72d7d45a6ba2e9c823771f160d512"


def comment(number, body, created="2026-11-22T13:04:25Z", login=hub.OWNER, issue_url=hub.ISSUE):
    return {"id": number, "body": body, "created_at": created, "updated_at": created,
            "user": {"login": login}, "html_url": issue_url + "#issuecomment-" + str(number)}


def diagnostics(failed=False):
    # Metadata shape and counters match the real November 22 diagnostic sample;
    # fixture health can be varied without writing any production database.
    units = {}
    for name in ("cognition", "integration", "ollama"):
        units[name] = {"active": "active" if name == "ollama" else "inactive",
                       "exit": 0, "load": "loaded", "result": "success",
                       "sub": "running" if name == "ollama" else "dead"}
    for name in ("cognition_timer", "integration_timer"):
        units[name] = {"active": "active", "last": "2026-11-22T12:00:02Z",
                       "load": "loaded", "next": "2026-11-22T14:00:00Z", "sub": "waiting"}
    return {"schema": "nasuraya-agent-diagnostics/1", "mode": "status", "utc": "2026-11-22T13:04:25Z",
            "units": units, "executables": {"installed": hub.KNOWN_INSTALLED, "release": hub.KNOWN_RELEASE, "match": False},
            "integration": {"state": "ok", "records": 81, "hour": "2026-11-22T13:00Z"},
            "cognition": {"state": "verified_history", "completed": 18, "drafts": 7, "failed": 11, "incomplete": 0,
                          "last_successful_slot": "2026-11-21T18" if failed else "2026-11-22T12",
                          "latest": {"slot": "2026-11-22T12", "model": "model_unavailable" if failed else "UNVERIFIED_DRAFT"}}}


def receipt(value, request=100, action="agent-status", number=101,
            stamp="2026-11-22T13:04:25.159208+00:00", created="2026-11-22T13:04:25Z"):
    body = (f"nasu-linux-result request_id={request}\naction={action}; utc={stamp}\n"
            f"host=ubuntu-iran; result:\n```text\nexit=0\n{json.dumps(value, separators=(',', ':'))}\n```")
    return comment(number, body, created)


def bundle(failed=False):
    return {"schema": hub.INPUT_SCHEMA,
            "github": {"retrieved_at_utc": "2026-11-22T13:05:00Z", "repository": hub.REPO,
                       "main": {"sha": HEAD, "html_url": hub.BASE + "/commit/" + HEAD},
                       "pull_requests": [], "pull_requests_complete": True, "workflow_runs": []},
            "server": {"retrieved_at_utc": "2026-11-22T13:05:40Z", "issue_url": hub.ISSUE,
                       "comments": [comment(100, "nasu-linux: agent-status", "2026-11-22T13:04:20Z"), receipt(diagnostics(failed))],
                       "recognized_deployments": [{"installed_sha256": hub.KNOWN_INSTALLED, "release_sha256": hub.KNOWN_RELEASE,
                                                   "source_url": hub.KNOWN_UPDATE_SOURCE, "label": "targeted_cognition_update"}]},
            "moltbook": {"schema": "nasuraya-public-moltbook-evidence/1", "expected_profile_name": "nasuraya",
                         "authenticated_server_poll_verified": True,
                         "public_profile": {"source_url": "https://www.moltbook.com/api/v1/agents/profile?name=Nasuraya",
                                            "acquired_at_utc": "2026-11-22T13:05:00Z",
                                            "agent": {"name": "nasuraya", "is_active": True, "is_claimed": True,
                                                      "posts_count": 0, "comments_count": 2, "last_active": "2026-11-14T10:37:32.983Z"}},
                         "feed": {"source_url": "https://www.moltbook.com/api/v1/posts?sort=new&limit=5",
                                  "acquired_at_utc": "2026-11-22T13:05:00Z", "items": [{"id": "5896bcd8-a64f-480b-bc4b-f99c25281905",
                                      "created_at": "2026-11-22T13:04:09.696Z", "title": SECRET, "body": SECRET,
                                      "source_url": "https://www.moltbook.com/api/v1/posts/5896bcd8-a64f-480b-bc4b-f99c25281905"}]}}}


class ProjectIntegrationTests(unittest.TestCase):
    def report(self, data=None, now=NOW):
        return hub.assemble(data if data is not None else bundle(), now=now)

    def actions(self, result):
        return [r["action"] for r in result["next_steps"]]

    def test_real_receipt_precision_and_targeted_update_are_preserved(self):
        result = self.report()
        server = result["components"]["server"]
        self.assertEqual(server["state"], "observed")
        self.assertEqual(server["health"], "observed_checks_passed")
        self.assertIs(server["deployment"]["raw_match"], False)
        self.assertEqual(server["deployment"]["relationship"], "recognized_targeted_update_against_frozen_release")
        self.assertEqual(result["mode"], "OBSERVE_PLAN_ONLY")
        self.assertEqual(result["external_actions_taken"], 0)

    def test_latest_failed_model_has_priority_without_inventing_cause(self):
        result = self.report(bundle(failed=True))
        self.assertEqual(result["components"]["server"]["health"], "attention_required")
        step = next(s for s in result["next_steps"] if s["action"] == "inspect_latest_model_or_input_failure")
        self.assertEqual(step["priority"], 1)
        self.assertIn("#issuecomment-101", step["evidence_urls"][0])
        self.assertNotIn("incomplete_http_response", json.dumps(result))

    def test_incomplete_cycle_is_never_reported_healthy(self):
        data = bundle()
        value = diagnostics()
        value["cognition"].update(state="incomplete", incomplete=1)
        data["server"]["comments"][1] = receipt(value)
        self.assertIn("inspect_invalid_or_incomplete_cognitive_receipts", self.actions(self.report(data)))

    def test_stale_success_is_attention_required(self):
        result = self.report(now=NOW + dt.timedelta(days=2))
        server = result["components"]["server"]
        self.assertEqual(server["freshness"]["state"], "stale")
        self.assertEqual(server["health"], "attention_required")
        self.assertIn("refresh_server_observation", self.actions(result))

    def test_current_feed_does_not_refresh_account_activity_or_prove_linkage(self):
        result = self.report()["components"]["moltbook"]
        self.assertEqual(result["profile"]["observation_freshness"]["state"], "fresh")
        self.assertEqual(result["profile"]["activity_freshness"]["state"], "stale")
        self.assertEqual(result["feed"]["observation_freshness"]["state"], "fresh")
        self.assertEqual(result["runtime_linkage"], "UNKNOWN")
        self.assertIs(result["authenticated_server_poll_verified"], False)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_untrusted_actor_cannot_supply_request_or_receipt(self):
        for index in (0, 1):
            with self.subTest(index=index):
                data = bundle()
                data["server"]["comments"][index]["user"]["login"] = "someone_else"
                server = self.report(data)["components"]["server"]
                self.assertNotEqual(server["state"], "observed")
                self.assertEqual(server["health"], "unknown")

    def test_comment_from_wrong_issue_or_missing_source_cannot_be_relinked(self):
        for index in (0, 1):
            for source in (None, hub.BASE + "/issues/999#issuecomment-" + str(100 + index)):
                data = bundle()
                data["server"]["comments"][index]["html_url"] = source
                server = self.report(data)["components"]["server"]
                self.assertNotEqual(server["state"], "observed")
                self.assertEqual(server["health"], "unknown")

    def test_embedded_command_in_prose_is_not_a_request(self):
        data = bundle()
        data["server"]["comments"][0]["body"] = SECRET + "\nnasu-linux: agent-status"
        self.assertEqual(self.report(data)["components"]["server"]["state"], "no_diagnostic_request")

    def test_unmatched_receipt_does_not_complete_request(self):
        data = bundle()
        data["server"]["comments"][1] = receipt(diagnostics(), request=999)
        self.assertEqual(self.report(data)["components"]["server"]["state"], "awaiting_receipt")

    def test_pending_new_request_does_not_reuse_old_success(self):
        data = bundle()
        data["server"]["comments"].append(comment(200, "nasu-linux: agent-status", "2026-11-22T13:06:00Z"))
        self.assertEqual(self.report(data)["components"]["server"]["state"], "awaiting_receipt")

    def test_duplicate_receipts_remain_ambiguous(self):
        data = bundle()
        data["server"]["comments"].append(receipt(diagnostics(), number=102))
        self.assertEqual(self.report(data)["components"]["server"]["state"], "ambiguous_receipts")

    def test_edited_comment_is_not_accepted_as_original_evidence(self):
        data = bundle()
        data["server"]["comments"][1]["updated_at"] = "2026-11-22T13:05:00Z"
        self.assertNotEqual(self.report(data)["components"]["server"]["state"], "observed")

    def test_future_comments_and_diagnostic_clocks_do_not_pass(self):
        for kind in ("comment", "clock"):
            data = bundle()
            if kind == "comment":
                data["server"]["comments"][1]["created_at"] = data["server"]["comments"][1]["updated_at"] = "2026-11-23T13:04:25Z"
            else:
                value = diagnostics()
                value["utc"] = "2026-11-23T13:04:25Z"
                data["server"]["comments"][1] = receipt(value)
            self.assertNotEqual(self.report(data)["components"]["server"]["state"], "observed")

    def test_pre_request_diagnostics_are_rejected(self):
        data = bundle()
        value = diagnostics()
        value["utc"] = "2026-11-22T13:03:25Z"
        data["server"]["comments"][1] = receipt(value)
        self.assertEqual(self.report(data)["components"]["server"]["state"], "invalid_receipt")

    def test_malformed_or_inconsistent_diagnostics_never_leak_raw_text(self):
        for mutation in (lambda v: v.update(private=SECRET),
                         lambda v: v["cognition"].update(completed=True),
                         lambda v: v["cognition"].update(failed=800),
                         lambda v: v["cognition"]["latest"].update(model=SECRET),
                         lambda v: v["executables"].update(match=True),
                         lambda v: v["units"]["ollama"].update(active=SECRET)):
            data = bundle()
            value = diagnostics()
            mutation(value)
            data["server"]["comments"][1] = receipt(value)
            result = self.report(data)
            self.assertEqual(result["components"]["server"]["state"], "invalid_receipt")
            self.assertNotIn(SECRET, json.dumps(result))

    def test_impossible_cognitive_state_and_success_counts_are_invalid(self):
        cases = [
            {"state": "verified_history", "completed": 0, "drafts": 0, "failed": 0, "incomplete": 0,
             "latest": None, "last_successful_slot": None},
            {"state": "verified_history", "completed": 18, "drafts": 0, "failed": 18, "incomplete": 0,
             "latest": {"slot": "2026-11-22T12", "model": "UNVERIFIED_DRAFT"}, "last_successful_slot": None},
            {"state": "verified_history", "completed": 18, "drafts": 7, "failed": 11, "incomplete": 0,
             "latest": {"slot": "2026-11-22T12", "model": "UNVERIFIED_DRAFT"}, "last_successful_slot": "2026-11-21T18"},
            {"state": "verified_history", "completed": 18, "drafts": 18, "failed": 0, "incomplete": 0,
             "latest": {"slot": "2026-11-22T12", "model": "model_unavailable"}, "last_successful_slot": "2026-11-21T18"},
            {"state": "empty", "completed": 18, "drafts": 7, "failed": 11, "incomplete": 0,
             "latest": {"slot": "2026-11-22T12", "model": "UNVERIFIED_DRAFT"}, "last_successful_slot": "2026-11-22T12"},
        ]
        for state in cases:
            data = bundle()
            value = diagnostics()
            value["cognition"] = state
            data["server"]["comments"][1] = receipt(value)
            self.assertEqual(self.report(data)["components"]["server"]["state"], "invalid_receipt")

    def test_future_timer_last_trigger_is_invalid_but_future_next_is_normal(self):
        self.assertEqual(self.report()["components"]["server"]["state"], "observed")
        data = bundle()
        value = diagnostics()
        value["units"]["cognition_timer"]["last"] = "2026-11-22T13:06:00Z"
        data["server"]["comments"][1] = receipt(value)
        self.assertEqual(self.report(data)["components"]["server"]["state"], "invalid_receipt")

    def test_forged_recognition_does_not_explain_arbitrary_hash_mismatch(self):
        data = bundle()
        value = diagnostics()
        value["executables"].update(installed="a" * 64)
        data["server"]["comments"][1] = receipt(value)
        data["server"]["recognized_deployments"][0]["installed_sha256"] = "a" * 64
        server = self.report(data)["components"]["server"]
        self.assertEqual(server["deployment"]["relationship"], "different_versions_unexplained")
        self.assertNotIn("corrupt", json.dumps(server))

    def test_exact_hash_pair_without_declaration_stays_unexplained(self):
        data = bundle()
        data["server"].pop("recognized_deployments")
        self.assertEqual(self.report(data)["components"]["server"]["deployment"]["relationship"], "different_versions_unexplained")

    def test_wrong_pinned_recognition_source_is_ignored(self):
        data = bundle()
        data["server"]["recognized_deployments"][0]["source_url"] = hub.BASE + "/blob/main/tools/apply_nasu_cognition_292.py"
        self.assertEqual(self.report(data)["components"]["server"]["deployment"]["relationship"], "different_versions_unexplained")

    def test_oneshot_inactive_success_and_active_timers_are_accepted(self):
        self.assertEqual(self.report()["components"]["server"]["health"], "observed_checks_passed")

    def test_failed_service_is_actionable_despite_valid_history(self):
        data = bundle()
        value = diagnostics()
        value["units"]["ollama"]["active"] = "failed"
        data["server"]["comments"][1] = receipt(value)
        self.assertIn("inspect_service_ollama", self.actions(self.report(data)))

    def test_wrong_repository_and_future_observations_are_not_healthy(self):
        data = bundle()
        data["github"]["repository"] = "other/repo"
        self.assertEqual(self.report(data)["components"]["github"]["state"], "invalid_evidence")
        data = bundle()
        data["server"]["retrieved_at_utc"] = "2026-11-23T13:05:40Z"
        self.assertEqual(self.report(data)["components"]["server"]["health"], "attention_required")

    def test_old_failed_commit_is_not_current_head_failure(self):
        data = bundle()
        def run(number, sha, conclusion, stamp):
            return {"id": number, "name": "contract", "html_url": hub.BASE + "/actions/runs/" + str(number),
                    "head_sha": sha, "status": "completed", "conclusion": conclusion, "updated_at": stamp, "workflow_id": 10}
        data["github"]["workflow_runs"] = [run(1, "b" * 40, "failure", "2026-11-20T01:00:00Z"),
                                            run(2, HEAD, "failure", "2026-11-21T01:00:00Z"),
                                            run(3, HEAD, "success", "2026-11-22T01:00:00Z")]
        github = self.report(data)["components"]["github"]
        self.assertEqual(github["current_head_failures"], 0)
        self.assertEqual(len(github["current_head_checks"]), 1)
        self.assertFalse(github["all_required_checks_verified"])

    def test_same_workflow_name_cannot_hide_another_workflow_failure(self):
        for identified in (True, False):
            data = bundle()
            runs = [{"id": 1, "name": "same display name", "html_url": hub.BASE + "/actions/runs/1",
                     "head_sha": HEAD, "status": "completed", "conclusion": "failure", "updated_at": "2026-11-21T01:00:00Z"},
                    {"id": 2, "name": "same display name", "html_url": hub.BASE + "/actions/runs/2",
                     "head_sha": HEAD, "status": "completed", "conclusion": "success", "updated_at": "2026-11-22T01:00:00Z"}]
            if identified:
                runs[0]["workflow_id"], runs[1]["workflow_id"] = 10, 20
            data["github"]["workflow_runs"] = runs
            github = self.report(data)["components"]["github"]
            self.assertEqual(github["current_head_failures"], 1)
            self.assertEqual(len(github["current_head_checks"]), 2)

    def test_current_head_failure_is_prioritized(self):
        data = bundle()
        data["github"]["workflow_runs"] = [{"id": 1, "name": "contract", "html_url": hub.BASE + "/actions/runs/1",
            "head_sha": HEAD, "status": "completed", "conclusion": "failure", "updated_at": "2026-11-22T01:00:00Z"}]
        self.assertIn("review_current_head_check_failure", self.actions(self.report(data)))

    def test_wrong_moltbook_host_and_future_posts_are_rejected(self):
        data = bundle()
        data["moltbook"]["public_profile"]["source_url"] = "https://www.moltbook.com.evil.test/api/v1/agents/profile?name=nasuraya"
        self.assertEqual(self.report(data)["components"]["moltbook"]["state"], "invalid_evidence")
        data = bundle()
        data["moltbook"]["feed"]["items"][0]["created_at"] = "2026-11-23T13:00:00Z"
        self.assertEqual(self.report(data)["components"]["moltbook"]["feed"]["posts_observed"], 0)

    def test_moltbook_source_queries_cannot_echo_tokens_or_extra_parameters(self):
        for section in ("public_profile", "feed"):
            for suffix in ("&token=" + SECRET, "&unused=", "&limit=5", "&name=nasuraya"):
                data = bundle()
                data["moltbook"][section]["source_url"] += suffix
                result = self.report(data)
                self.assertEqual(result["components"]["moltbook"]["state"], "invalid_evidence")
                self.assertNotIn(SECRET, json.dumps(result))

    def test_moltbook_queries_are_canonical_and_feed_limit_is_bounded(self):
        data = bundle()
        data["moltbook"]["feed"]["source_url"] = "https://moltbook.com/api/v1/posts?limit=5&sort=new"
        result = self.report(data)["components"]["moltbook"]
        self.assertEqual(result["profile"]["source_url"], "https://www.moltbook.com/api/v1/agents/profile?name=nasuraya")
        self.assertEqual(result["feed"]["source_url"], "https://www.moltbook.com/api/v1/posts?sort=new&limit=5")
        for query in ("sort=hot&limit=5", "sort=new&limit=101", "sort=new&limit=0", "sort=new&limit=5&limit=5"):
            data["moltbook"]["feed"]["source_url"] = "https://www.moltbook.com/api/v1/posts?" + query
            self.assertEqual(self.report(data)["components"]["moltbook"]["state"], "invalid_evidence")

    def test_repeated_feed_items_are_unique_observations_not_new_posts(self):
        data = bundle()
        items = data["moltbook"]["feed"]["items"]
        items.append(copy.deepcopy(items[0]))
        feed = self.report(data)["components"]["moltbook"]["feed"]
        self.assertEqual((feed["fetched_items"], feed["unique_posts"], feed["duplicate_items"], feed["posts_observed"]), (2, 1, 1, 1))
        self.assertIsNone(feed["newly_seen"])

    def test_conflicting_duplicate_feed_metadata_is_ambiguous(self):
        for changed in ("created_at", "source_url"):
            data = bundle()
            items = data["moltbook"]["feed"]["items"]
            duplicate = copy.deepcopy(items[0])
            duplicate[changed] = "2026-11-22T13:02:00Z" if changed == "created_at" else duplicate[changed].replace("www.moltbook", "moltbook")
            items.append(duplicate)
            feed = self.report(data)["components"]["moltbook"]["feed"]
            self.assertEqual(feed["state"], "ambiguous_evidence")
            self.assertEqual((feed["ambiguous_posts"], feed["posts_observed"]), (1, 0))
            self.assertIsNone(feed["newly_seen"])

    def test_legacy_metadata_cannot_make_current_server_healthy(self):
        data = {"schema": hub.INPUT_SCHEMA, "legacy": {"issue_url": hub.LEGACY_ISSUE,
                "comments": [comment(1, "Nasuraya Bridge v2 result; " + SECRET, issue_url=hub.LEGACY_ISSUE)]}}
        result = self.report(data)
        self.assertEqual(result["components"]["server"]["health"], "unknown")
        self.assertFalse(result["components"]["legacy"]["validates_current_ubuntu_or_moltbook"])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_pure_assembler_never_opens_files_network_or_processes(self):
        data = bundle()
        original = copy.deepcopy(data)
        with mock.patch("builtins.open", side_effect=AssertionError("file access")), \
             mock.patch("socket.socket", side_effect=AssertionError("network")), \
             mock.patch("subprocess.run", side_effect=AssertionError("process")):
            result = self.report(data)
        self.assertEqual(data, original)
        self.assertEqual(result["external_actions_taken"], 0)

    def test_auxiliary_repo_and_research_receipts_preserve_historical_scope(self):
        data = bundle()
        comments = data["server"]["comments"]
        comments.append(comment(110, "nasu-linux: repo", "2026-11-22T13:04:20Z"))
        comments.append(comment(111, "nasu-linux-result request_id=110\naction=repo; utc=2026-11-22T13:04:25.3+00:00\nhost=ubuntu-iran; result:\n```text\nexit=0\n## main...origin/main\nexit=0\nf8bbe73\n```"))
        comments.append(comment(112, "nasu-linux: research-status", "2026-11-22T13:04:20Z"))
        history = {"schema": "nasuraya-bridge-research/1", "state": "completed", "completed": 16, "correct": 9,
                   "errors": 0, "last_sha": "9" * 64, "task_issue": 290, "total": 16, "valid": 16}
        comments.append(receipt(history, request=112, action="research-status", number=113))
        linked = self.report(data)["components"]["server"]["related_receipts"]
        self.assertEqual(linked["repo"]["state"], "observed")
        self.assertTrue(linked["repo"]["matches_observed_github_head_prefix"])
        self.assertFalse(linked["repo"]["full_checkout_revision_matches_observed_main"])
        self.assertNotIn("full_runtime_revision_confirmed", linked["repo"])
        self.assertEqual(linked["research-status"]["history"]["correct"], 9)
        self.assertFalse(linked["research-status"]["new_execution_proven"])

    def test_full_checkout_sha_does_not_claim_deployed_runtime_identity(self):
        data = bundle()
        data["server"]["comments"].extend([
            comment(110, "nasu-linux: repo", "2026-11-22T13:04:20Z"),
            comment(111, "nasu-linux-result request_id=110\naction=repo; utc=2026-11-22T13:04:25.3+00:00\nhost=ubuntu-iran; result:\n```text\nexit=0\n## main...origin/main\nexit=0\n" + HEAD + "\n```"),
        ])
        row = self.report(data)["components"]["server"]["related_receipts"]["repo"]
        self.assertTrue(row["full_checkout_revision_matches_observed_main"])
        self.assertFalse(any("runtime" in key for key in row))

    def test_cli_reads_one_bundle_without_changing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(bundle()))
            before = path.read_bytes()
            stream = io.StringIO()
            with mock.patch("sys.stdout", stream):
                code = hub.main(["--from-file", str(path), "--now", "2026-11-22T13:10:00Z"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stream.getvalue())["mode"], "OBSERVE_PLAN_ONLY")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_invalid_bundle_and_naive_clock_are_rejected(self):
        with self.assertRaises(ValueError):
            hub.assemble({"schema": "unknown"}, now=NOW)
        with self.assertRaises(ValueError):
            hub.assemble(bundle(), now=NOW.replace(tzinfo=None))



class DevelopmentClosureTests(unittest.TestCase):
    def test_all_observed_open_prs_have_exactly_one_provisional_lane(self):
        data = bundle()
        template = data["github"]["pull_requests"][0]
        data["github"]["pull_requests"] = []
        for n in range(1, 214):
            row = copy.deepcopy(template)
            row.update(number=n, html_url=hub.BASE + "/pull/" + str(n),
                       title="Tadash memory ritual" if n % 2 else "Qwen server")
            data["github"]["pull_requests"].append(row)
        data["github"]["pull_requests_complete"] = True
        github = hub.assemble(data, now=NOW)["components"]["github"]
        q = github["development_queue"]
        self.assertEqual(q["observed_count"], 213)
        self.assertEqual(len(github["recent_prs"]), 20)
        self.assertEqual(sorted(n for group in q["groups"].values() for n in group),
                         list(range(1, 214)))
        self.assertTrue(q["collection_complete"])
        self.assertFalse(q["atomic_snapshot"])
        self.assertTrue(all(not p["merge_or_deploy_authorized"] for p in q["queue"]))

    def test_ambiguous_and_unclassified_titles_are_preserved_without_raw_text(self):
        data = bundle()
        original = data["github"]["pull_requests"][0]
        rows = []
        for n, title in ((11, "ritual affect memory " + SECRET), (12, SECRET), (13, None)):
            row = copy.deepcopy(original)
            row.update(number=n, html_url=hub.BASE + "/pull/" + str(n), title=title)
            rows.append(row)
        data["github"]["pull_requests"] = rows
        data["github"]["pull_requests_complete"] = False
        q = hub.assemble(data, now=NOW)["components"]["github"]["development_queue"]
        self.assertFalse(q["collection_complete"])
        self.assertIn(11, q["multi_lane_numbers"])
        self.assertEqual(q["unclassified_numbers"], [12, 13])
        self.assertNotIn(SECRET, json.dumps(q))
        self.assertTrue(all(p["state"] == "review_required" for p in q["queue"]))

    def test_observed_failure_beats_success_and_unknown_never_means_ready(self):
        pr = {"number": 1, "head_sha": HEAD, "source_url": hub.BASE + "/pull/1", "draft": False}
        other = dict(pr, number=2, head_sha="b" * 40)
        checks = [{"head_sha": HEAD, "status": "completed", "conclusion": "success"},
                  {"head_sha": HEAD, "status": "completed", "conclusion": "failure"}]
        result = hub._development_queue([pr, other], {1: "memory", 2: "body"}, checks, False, "stale")
        self.assertEqual([x["ci_observation"] for x in result["queue"]],
                         ["failure_observed", "unknown_or_no_success_observed"])
        self.assertEqual(result["collection_freshness"], "stale")
        self.assertTrue(all(not x["merge_or_deploy_authorized"] for x in result["queue"]))

    def test_candidate_destinations_exist_in_checkout(self):
        root = Path(__file__).resolve().parents[1]
        for _, _, paths in hub.DEVELOPMENT_LANES:
            for path in paths:
                self.assertTrue((root / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
