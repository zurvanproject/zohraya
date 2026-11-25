#!/usr/bin/env python3
"""Collect bounded PUBLIC metadata for the Nasuraya integration report.

Run python -B -m tools.nasu_collect_project_status --report --pretty.
Only fixed unauthenticated HTTPS GET endpoints are used. No credentials,
environment tokens, model calls, commands, files, or remote mutations are used.
Issue comments are a bounded tail, not a complete or atomic server history.
Only the four supported owner request/receipt types survive projection; other
comment bodies and private owner fields are never emitted.
Collection status describes source coverage, not runtime health or full history.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from tools import nasu_project_integration as integration

API = "https://api.github.com/repos/zurvanproject/zohraya"
WEB = "https://github.com/zurvanproject/zohraya"
MAIN_URL = API + "/branches/main"
RUNS_URL = API + "/actions/runs?per_page=30&page=1"
ISSUE_URL = API + "/issues/212"
PROFILE_URL = "https://www.moltbook.com/api/v1/agents/profile?name=Nasuraya"
FEED_URL = "https://www.moltbook.com/api/v1/posts?sort=new&limit=5"
MAX_PR_PAGES = 10
MAX_COMMENT_PAGES = 5
MAX_REQUESTS = 22
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 8
TOTAL_SECONDS = 45
ACTIONS = frozenset(("agent-status", "agent-probe", "repo", "research-status"))
OWNER = "zurvanproject"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
REQUEST = re.compile(r"nasu-linux: (agent-status|agent-probe|repo|research-status)\Z")
RESULT_ID = re.compile(r"\Anasu-linux-result request_id=([1-9][0-9]{0,18})\n")
RESULT_ACTION = re.compile(r"\Anasu-linux-result request_id=([1-9][0-9]{0,18})\naction=([a-z-]{1,40});")
FENCE = chr(96) * 3
FRAME = re.compile(
    r"\Anasu-linux-result request_id=([1-9][0-9]{0,18})\n"
    r"action=(agent-status|agent-probe|repo|research-status); utc=([^\n]{1,40})\n"
    r"host=ubuntu-iran; result:\n" + FENCE + r"text\n([^\r]*)\n" + FENCE + r"\s*\Z"
)


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def stamp(value):
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def valid_time(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
    ):
        raise ValueError("invalid_time")
    dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def natural(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("invalid_counter")
    return value


def clean_text(value, maximum):
    if not isinstance(value, str) or not 0 < len(value) <= maximum or not all(c.isprintable() for c in value):
        raise ValueError("invalid_text")
    return value


def allowed_url(url):
    if url in (MAIN_URL, RUNS_URL, ISSUE_URL, PROFILE_URL, FEED_URL):
        return True
    if not isinstance(url, str):
        return False
    prefix = re.escape(API)
    return bool(re.fullmatch(prefix + r"/pulls\?state=open&sort=updated&direction=desc&per_page=100&page=(?:[1-9]|10)", url)
                or re.fullmatch(prefix + r"/issues/212/comments\?per_page=100&page=[1-9][0-9]{0,4}", url))


class RedirectRefused(ValueError):
    pass


class ResponseTooLarge(ValueError):
    pass


class CollectionLimit(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise RedirectRefused("redirect_refused")


def strict_json(raw):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite_json")

    return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def safe_environment_proxies():
    """Retain managed standard routing, without proxy credentials or URL data."""
    found = urllib.request.getproxies()
    proxies = {}
    for protocol in ("http", "https"):
        value = found.get(protocol)
        if value is None:
            continue
        try:
            if not isinstance(value, str) or not value or any(c.isspace() or not c.isprintable() for c in value):
                raise ValueError("invalid_proxy")
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                    or parsed.port is not None and not 1 <= parsed.port <= 65535):
                raise ValueError("invalid_proxy")
        except (ValueError, TypeError, AttributeError):
            # The configuration value must never appear in an error or report.
            raise ValueError("unsafe_proxy_configuration") from None
        proxies[protocol] = value
    return proxies


class PublicClient:
    """No caller-provided headers, method, auth, arbitrary URL, or redirects."""

    def __init__(self, *, opener=None, now=utc_now, monotonic=time.monotonic):
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler(safe_environment_proxies()), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.now = now
        self.monotonic = monotonic
        self.deadline = monotonic() + TOTAL_SECONDS
        self.requests = []

    def get(self, url):
        if not allowed_url(url):
            raise ValueError("url_not_allowlisted")
        if len(self.requests) >= MAX_REQUESTS or self.monotonic() >= self.deadline:
            raise CollectionLimit("collection_limit")
        record = {"source_url": url, "started_at_utc": stamp(self.now()), "method": "GET"}
        self.requests.append(record)
        try:
            request = urllib.request.Request(url, method="GET", headers={
                "Accept": "application/json", "User-Agent": "NasurayaPublicStatus/1"})
            remaining = self.deadline - self.monotonic()
            if remaining <= 0:
                raise CollectionLimit("time_budget")
            with self.opener.open(request, timeout=min(TIMEOUT_SECONDS, remaining)) as response:
                if response.getcode() != 200:
                    raise ValueError("unexpected_http_status")
                if response.geturl() != url:
                    raise RedirectRefused("redirect_refused")
                if "json" not in response.headers.get("Content-Type", "").lower():
                    raise ValueError("unexpected_content_type")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                    raise ResponseTooLarge("response_too_large")
                chunks, size = [], 0
                read = getattr(response, "read1", response.read)
                while True:
                    if self.monotonic() >= self.deadline:
                        raise CollectionLimit("time_budget")
                    chunk = read(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ResponseTooLarge("response_too_large")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            data = strict_json(raw)
            record.update(status="ok", acquired_at_utc=stamp(self.now()),
                          response_bytes=len(raw), response_sha256=hashlib.sha256(raw).hexdigest())
            return data, dict(record)
        except Exception as exc:
            record.update(status="error", acquired_at_utc=stamp(self.now()),
                          error_class=type(exc).__name__)
            if isinstance(exc, urllib.error.HTTPError):
                record["http_status"] = exc.code
                exc.close()
            raise


def pr_url(page):
    return API + "/pulls?state=open&sort=updated&direction=desc&per_page=100&page=" + str(page)


def comments_url(page):
    return API + "/issues/212/comments?per_page=100&page=" + str(page)


def _pr(row):
    number = natural(row["number"])
    sha = row["head"]["sha"]
    if not number or row["state"] != "open" or type(row["draft"]) is not bool or not HEX40.fullmatch(sha):
        raise ValueError("invalid_pr")
    if row["html_url"] != WEB + "/pull/" + str(number):
        raise ValueError("wrong_pr_source")
    return {"number": number, "state": "open", "draft": row["draft"],
            "html_url": row["html_url"], "updated_at": valid_time(row["updated_at"]), "head": {"sha": sha},
            "routing_candidates": integration.development_title_candidates(row.get("title"))}


def _run(row):
    ident = natural(row["id"])
    if not ident or row["html_url"] != WEB + "/actions/runs/" + str(ident) or not HEX40.fullmatch(row["head_sha"]):
        raise ValueError("invalid_run")
    status, conclusion = row["status"], row.get("conclusion")
    if status not in integration.RUN_STATUS or conclusion is not None and conclusion not in integration.CONCLUSIONS:
        raise ValueError("invalid_run_state")
    if (status == "completed") != (conclusion is not None):
        raise ValueError("inconsistent_run_state")
    result = {"id": ident, "name": clean_text(row["name"], 160), "html_url": row["html_url"],
              "status": status, "conclusion": conclusion, "head_sha": row["head_sha"],
              "updated_at": valid_time(row["updated_at"])}
    if "workflow_id" in row:
        if not natural(row["workflow_id"]):
            raise ValueError("invalid_workflow_id")
        result["workflow_id"] = row["workflow_id"]
    return result


def _project_rows(rows, projector):
    accepted, rejected = [], 0
    for row in rows:
        try:
            accepted.append(projector(row))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            rejected += 1
    return accepted, rejected


def _safe_body(body, now):
    """Preserve invalid receipt headers but never echo invalid raw payloads."""
    match = FRAME.fullmatch(body)
    ident = RESULT_ID.match(body)
    sentinel = "nasu-linux-result request_id=" + ident[1] + "\nINVALID_RECEIPT_METADATA\n"
    if match is None:
        return sentinel
    try:
        valid_time(match[3])
        lines = match[4].splitlines()
        if not lines or lines[0] != "exit=0":
            raise ValueError("unsuccessful_receipt")
        action = match[2]
        if action in {"agent-status", "agent-probe"}:
            if len(lines) != 2:
                raise ValueError("invalid_receipt")
            value = strict_json(lines[1])
            integration._diagnostics(value, action, now)
            payload = "exit=0\n" + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        elif action == "repo":
            if len(lines) < 4 or not re.fullmatch(r"## main\.\.\.origin/main(?: \[(?:ahead|behind) [1-9][0-9]*(?:, (?:ahead|behind) [1-9][0-9]*)?\])?", lines[1]):
                raise ValueError("invalid_repo")
            if lines[-2] != "exit=0" or not re.fullmatch(r"[0-9a-f]{7,40}", lines[-1]):
                raise ValueError("invalid_repo")
            changes = []
            for line in lines[2:-2]:
                if not re.fullmatch(r"[ MADRCU?!]{2} .{1,500}", line):
                    raise ValueError("invalid_worktree_status")
                changes.append(line[:3] + "redacted_path")
            payload = "\n".join([lines[0], lines[1], *changes, lines[-2], lines[-1]])
        else:
            if len(lines) != 2:
                raise ValueError("invalid_research_status")
            value = strict_json(lines[1])
            keys = {"schema", "state", "completed", "correct", "errors", "last_sha", "task_issue", "total", "valid"}
            if not isinstance(value, dict) or set(value) != keys or value["schema"] != "nasuraya-bridge-research/1" or value["state"] not in {"completed", "running", "stopped", "failed"} or value["task_issue"] != 290:
                raise ValueError("invalid_research_status")
            for key in ("completed", "correct", "errors", "total", "valid"):
                natural(value[key])
            if not value["correct"] <= value["valid"] <= value["completed"] <= value["total"] or value["errors"] > value["completed"] or not re.fullmatch(r"[0-9a-f]{64}", value["last_sha"]):
                raise ValueError("invalid_research_counts")
            payload = "exit=0\n" + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return ("nasu-linux-result request_id=" + match[1] + "\naction=" + action + "; utc=" + match[3]
                + "\nhost=ubuntu-iran; result:\n" + FENCE + "text\n" + payload + "\n" + FENCE)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return sentinel


def project_comments(rows, now):
    owners = [r for r in rows if isinstance(r, dict) and isinstance(r.get("user"), dict) and r["user"].get("login") == OWNER]
    known = {r.get("id") for r in owners if isinstance(r.get("body"), str) and REQUEST.fullmatch(r["body"].strip())}
    result, rejected = [], 0
    for row in owners:
        body = row.get("body")
        if not isinstance(body, str):
            rejected += 1
            continue
        # Prefix matching is bounded even if an unrelated comment is very large.
        request = REQUEST.fullmatch(body.strip())
        candidate = RESULT_ID.match(body[:100])
        action = RESULT_ACTION.match(body[:200])
        if not request and not (candidate and (int(candidate[1]) in known or action and action[2] in ACTIONS)):
            continue
        try:
            ident = natural(row["id"])
            if not ident:
                raise ValueError("invalid_comment_id")
            expected_url = WEB + "/issues/212#issuecomment-" + str(ident)
            if row.get("html_url") != expected_url:
                raise ValueError("wrong_comment_source")
            safe = {"id": ident, "user": {"login": OWNER},
                    "created_at": valid_time(row["created_at"]),
                    "updated_at": valid_time(row["updated_at"]),
                    "html_url": row["html_url"]}
            safe["body"] = body.strip() if request else _safe_body(body if len(body) <= 20000 else body[:100], now)
            safe["body_projection"] = "request" if request else "validated_metadata_or_invalid_sentinel"
            safe["source_body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
            result.append(safe)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            rejected += 1
    return result, rejected


def _post(row):
    ident = row["id"]
    if not isinstance(ident, str) or not UUID.fullmatch(ident):
        raise ValueError("invalid_post")
    result = {"id": ident, "created_at": valid_time(row["created_at"]),
              "source_url": "https://www.moltbook.com/api/v1/posts/" + ident}
    # No post body, author biography, owner identity, or instruction text.
    if isinstance(row.get("title"), str):
        title = "".join(c for c in row["title"][:240] if c.isprintable())
        if title:
            result["title"] = title
    return result


def latest_groups_resolved(rows):
    """Only current events determine tail paging; old orphan receipts do not."""
    groups = {"agent-status": "diagnostics", "agent-probe": "diagnostics",
              "repo": "repo", "research-status": "research-status"}
    requests, events = {}, {group: [] for group in set(groups.values())}
    for row in rows:
        request = REQUEST.fullmatch(row["body"])
        if request:
            group = groups[request[1]]
            requests[row["id"]] = group
            events[group].append((row["created_at"], row["id"], "request", row["id"]))
    for row in rows:
        ident = RESULT_ID.match(row["body"])
        if not ident:
            continue
        request_id = int(ident[1])
        action = RESULT_ACTION.match(row["body"])
        group = groups.get(action[2]) if action else requests.get(request_id)
        if group is not None:
            events[group].append((row["created_at"], row["id"], "receipt", request_id))
    for group, candidates in events.items():
        if not candidates:
            return False
        latest = max(candidates, key=lambda item: (
            dt.datetime.fromisoformat(item[0].replace("Z", "+00:00")), item[1]))
        # A newer request without its result is a visible pending observation.
        # A newer receipt requires its matching request, even if older pairs exist.
        if latest[2] == "receipt" and requests.get(latest[3]) != group:
            return False
    return True


def collect(*, client=None, now=utc_now):
    client = client or PublicClient(now=now)
    started = stamp(now())
    errors = []

    def read(url):
        try:
            return client.get(url)
        except Exception as exc:
            errors.append({"source_url": url, "error_class": type(exc).__name__})
            return None, None

    bundle = {"schema": integration.INPUT_SCHEMA}
    raw_main, main_meta = read(MAIN_URL)
    # Reserve coverage of the second origin before potentially lengthy GitHub
    # pagination. These observations are reused below, never fetched twice.
    profile, profile_meta = read(PROFILE_URL)
    feed, feed_meta = read(FEED_URL)
    github = None
    try:
        sha = raw_main["commit"]["sha"]
        if raw_main.get("name") != "main" or not isinstance(sha, str) or not HEX40.fullmatch(sha):
            raise ValueError("invalid_main")
        github = {"repository": "zurvanproject/zohraya", "retrieved_at_utc": main_meta["acquired_at_utc"],
                  "main": {"sha": sha, "html_url": WEB + "/commit/" + sha},
                  "pull_requests": [], "pull_requests_complete": False, "workflow_runs": []}
        bundle["github"] = github
        committed = raw_main["commit"].get("commit", {}).get("committer", {}).get("date")
        if committed is not None:
            github["main"]["committed_at_utc"] = valid_time(committed)
    except (ValueError, TypeError, KeyError, AttributeError):
        if raw_main is not None:
            errors.append({"source_url": MAIN_URL, "error_class": "ValueError"})
    if github is not None:
        seen, rejected, duplicate, pages, terminal = set(), 0, 0, 0, False
        for page in range(1, MAX_PR_PAGES + 1):
            data, meta = read(pr_url(page))
            if not isinstance(data, list) or len(data) > 100:
                break
            pages += 1
            projected, bad = _project_rows(data, _pr)
            rejected += bad
            for row in projected:
                if row["number"] in seen:
                    duplicate += 1
                    continue
                seen.add(row["number"])
                github["pull_requests"].append(row)
            if len(data) < 100:
                terminal = True
                break
        github["pull_requests_complete"] = terminal and rejected == 0 and duplicate == 0
        github["pull_request_coverage"] = {"pages_observed": pages, "page_limit": MAX_PR_PAGES,
            "terminal_page_observed": terminal, "rejected_rows": rejected, "duplicate_rows": duplicate,
            "truncated_or_incomplete": not github["pull_requests_complete"], "atomic_snapshot": False}
        data, meta = read(RUNS_URL)
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if isinstance(runs, list) and len(runs) <= 30:
            github["workflow_runs"], bad = _project_rows(runs, _run)
            github["workflow_coverage"] = {"state": "observed", "scope": "latest_30_runs_not_all_checks",
                "limit": 30, "returned_count": len(runs), "rejected_rows": bad,
                "acquired_at_utc": meta["acquired_at_utc"], "complete_history": False}
        else:
            github["workflow_coverage"] = {"state": "unavailable", "complete_history": False}

    issue, issue_meta = read(ISSUE_URL)
    try:
        total = natural(issue["comments"])
        if issue["number"] != 212 or issue["html_url"] != WEB + "/issues/212" or total > 1000000:
            raise ValueError("invalid_issue")
        last = max(1, (total + 99) // 100)
        raw_rows, observed_pages = [], []
        transport_duplicates, conflicts, seen = 0, 0, {}
        for page in range(last, max(0, last - MAX_COMMENT_PAGES), -1):
            data, meta = read(comments_url(page))
            if not isinstance(data, list) or len(data) > 100:
                break
            observed_pages.append(page)
            for row in data:
                if not isinstance(row, dict):
                    raw_rows.append(row)
                    continue
                ident = row.get("id")
                minimal = {k: row.get(k) for k in ("id", "user", "body", "created_at", "updated_at")}
                if type(ident) is int and ident in seen:
                    if seen[ident] == minimal:
                        transport_duplicates += 1
                        continue
                    conflicts += 1
                if type(ident) is int:
                    seen[ident] = minimal
                raw_rows.append(row)
            projected, bad = project_comments(raw_rows, now())
            if latest_groups_resolved(projected):
                break
        projected, bad = project_comments(raw_rows, now())
        request_ids = {r["id"] for r in projected if REQUEST.fullmatch(r["body"])}
        linked = {int(m[1]) for r in projected if (m := RESULT_ID.match(r["body"]))}
        bundle["server"] = {"retrieved_at_utc": issue_meta["acquired_at_utc"],
            "issue_url": WEB + "/issues/212", "comments": projected,
            "recognized_deployments": [{"installed_sha256": integration.KNOWN_INSTALLED,
                "release_sha256": integration.KNOWN_RELEASE, "source_url": integration.KNOWN_UPDATE_SOURCE,
                "label": "targeted_cognition_update"}],
            "collection_coverage": {"scope": "bounded_tail_of_issue_212", "reported_total_at_start": total,
                "pages_observed": observed_pages, "page_limit": MAX_COMMENT_PAGES,
                "raw_rows_observed": len(raw_rows), "retained_rows": len(projected), "rejected_rows": bad,
                "duplicate_transport_rows": transport_duplicates, "conflicting_transport_rows": conflicts,
                "linked_request_ids_missing": sorted(linked - request_ids),
                "unmatched_ids_scope": "all_observed_including_historical",
                "latest_relevant_groups_resolved": latest_groups_resolved(projected),
                "full_history_verified": False, "atomic_snapshot": False,
                "truncated": bool(not observed_pages or min(observed_pages) > 1)}}
        if issue.get("updated_at") is not None:
            bundle["server"]["issue_updated_at_utc"] = valid_time(issue["updated_at"])
    except (ValueError, TypeError, KeyError, AttributeError):
        if issue is not None:
            errors.append({"source_url": ISSUE_URL, "error_class": "ValueError"})

    try:
        agent = profile["agent"]
        if profile.get("success") is not True or agent.get("name") != "nasuraya":
            raise ValueError("invalid_profile")
        safe = {"name": "nasuraya"}
        for key in ("is_claimed", "is_active"):
            if key in agent:
                if type(agent[key]) is not bool:
                    raise ValueError("invalid_flag")
                safe[key] = agent[key]
        for key in ("posts_count", "comments_count", "follower_count", "following_count"):
            if key in agent:
                safe[key] = natural(agent[key])
        if agent.get("last_active") is not None:
            safe["last_active"] = valid_time(agent["last_active"])
        recent = profile.get("recentPosts")
        recent_posts, rejected = _project_rows(recent[:20], _post) if isinstance(recent, list) else (None, 0)
        moltbook = {"schema": "nasuraya-public-moltbook-evidence/1", "expected_profile_name": "nasuraya",
            "acquired_at_utc": profile_meta["acquired_at_utc"], "read_only": True, "authentication": "none",
            "authenticated_server_poll_verified": False,
            "public_profile": {"source_url": PROFILE_URL, "acquired_at_utc": profile_meta["acquired_at_utc"],
                "observation_kind": "public_api", "agent": safe, "recentPosts": recent_posts,
                "recent_posts_rejected": rejected, "complete_history": False}}
        bundle["moltbook"] = moltbook
    except (ValueError, TypeError, KeyError, AttributeError):
        if profile is not None:
            errors.append({"source_url": PROFILE_URL, "error_class": "ValueError"})
        moltbook = None
    if moltbook is not None:
        if isinstance(feed, dict) and feed.get("success") is True and isinstance(feed.get("posts"), list) and len(feed["posts"]) <= 5 and type(feed.get("has_more")) is bool:
            posts, bad = _project_rows(feed["posts"], _post)
            moltbook["feed"] = {"source_url": FEED_URL, "acquired_at_utc": feed_meta["acquired_at_utc"],
                "observation_kind": "public_api", "requested_limit": 5, "returned_count": len(feed["posts"]),
                "has_more": feed["has_more"], "scope": "bounded_first_page", "items": posts,
                "rejected_rows": bad, "complete_history": False}
        elif feed is not None:
            errors.append({"source_url": FEED_URL, "error_class": "ValueError"})
    available = [name for name in ("github", "server", "moltbook") if name in bundle]
    g = bundle.get("github", {})
    s = bundle.get("server", {}).get("collection_coverage", {})
    m = bundle.get("moltbook", {})
    complete = (len(available) == 3 and not errors and g.get("pull_requests_complete") is True
        and g.get("workflow_coverage", {}).get("state") == "observed"
        and not g.get("workflow_coverage", {}).get("rejected_rows")
        and bool(s.get("pages_observed")) and not s.get("rejected_rows")
        and not s.get("conflicting_transport_rows") and not s.get("linked_request_ids_missing")
        and "feed" in m and not m["feed"].get("rejected_rows"))
    status = "unavailable" if not available else "complete" if complete else "partial"
    bundle["collection"] = {"schema": "nasuraya-public-collection/1", "started_at_utc": started,
        "completed_at_utc": stamp(now()), "mode": "PUBLIC_GET_ONLY", "authentication": "none",
        "status": status, "available_components": available,
        "status_scope": "requested_bounded_sources_not_runtime_health_or_full_history",
        "requests": list(client.requests), "errors": errors, "requests_limit": MAX_REQUESTS,
        "per_request_bytes_limit": MAX_RESPONSE_BYTES, "time_budget_seconds": TOTAL_SECONDS,
        "full_ci_or_issue_history_verified": False, "model_calls": 0, "remote_mutations": 0}
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="Project the collected bundle through the offline coordinator")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        bundle = collect()
        result = integration.assemble(bundle) if args.report else bundle
        if args.report:
            result["collection"] = bundle["collection"]
            result["collection_coverage"] = {name: {key: value for key, value in bundle.get(name, {}).items()
                if key in {"collection_coverage", "pull_request_coverage", "workflow_coverage"}}
                for name in ("github", "server")}
        encoded = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, allow_nan=False)
        if len(encoded.encode()) > MAX_OUTPUT_BYTES:
            raise ResponseTooLarge("output_too_large")
        print(encoded)
        return 2 if bundle["collection"]["status"] == "unavailable" else 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error_class": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
