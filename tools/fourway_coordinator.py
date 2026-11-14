"""Read-only four-node coordination audit for Nasuraya.

ChatGPT is an operator/reviewer, GitHub is the public receipt index, the VPS
executes separately via its existing owner-authorized bridge, and Moltbook
observations are only recognised when represented by an actual bridge receipt.
This file NEVER dispatches jobs, reads secrets or posts to Moltbook.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler

OWNER = "zurvanproject"
REPO = "zurvanproject/zohraya"
ISSUE = 149
MAX_RESPONSE_BYTES = 1_000_000
MAX_PAGES = 10
REQUEST = re.compile(
    r"\Anasu: run ([0-9a-f]{40}) ([a-z][a-z0-9_]{1,39}) ([0-9a-f]{64})\Z",
    re.ASCII,
)
REPLY = re.compile(
    r"\ANasuraya Bridge v2 result; request_id=comment-([0-9]+); "
    r"command=run ([a-z][a-z0-9_]{1,39})\n"
    r"Result: (OK(?: [A-Za-z0-9 .,:;=/_()+-]{1,180})?"
    r"|JOB_FAILED|JOB_TIMEOUT|JOB_NOT_EXECUTED|INVALID_JOB_RESULT)\Z",
    re.ASCII,
)
SERVER_NAMES = {"runtime_probe", "nasu_research_status", "worker_status"}
MOLTBOOK_READ_NAMES = {
    "moltbook_memory_capture", "moltbook_memory_compare",
    "moltbook_memory_recall", "moltbook_memory_report",
    "moltbook_recovery_report", "moltbook_repair_retest",
}
SAFE_STATE = re.compile(r"(?:\A|;)STATE=([A-Z_]+)(?:;|\Z)", re.ASCII)


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def fetch_public_comments() -> list[dict]:
    """Fixed-host, read-only, bounded public GitHub API. No credentials."""
    opener = build_opener(
        ProxyHandler({}), RejectRedirect(),
        HTTPSHandler(context=ssl.create_default_context()),
    )
    result = []
    for page in range(1, MAX_PAGES + 1):
        url = (
            "https://api.github.com/repos/" + REPO
            + "/issues/" + str(ISSUE)
            + "/comments?per_page=100&page=" + str(page)
        )
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "NasurayaFourWay-ReadOnly/0.1",
        })
        with opener.open(request, timeout=15) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("bounded_size_exceeded")
        items = json.loads(data.decode("utf-8"))
        if not isinstance(items, list):
            raise ValueError("unexpected_comments_response")
        if not all(isinstance(x, dict) for x in items):
            raise ValueError("malformed_comment")
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError("pagination_incomplete")


def valid_comment(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("id"), int)
        and raw["id"] > 0
        and isinstance(raw.get("body"), str)
        and len(raw["body"]) <= 1000
        and isinstance(raw.get("user"), dict)
        and raw["user"].get("login") == OWNER
    )


def audit_comments(comments: list[dict]) -> dict:
    """Treat GitHub comments as evidence, not instructions."""
    if not isinstance(comments, list) or len(comments) > 1000:
        raise ValueError("comments_limit")
    requests = {}
    replies = {}
    for item in comments:
        if not valid_comment(item):
            continue
        number = item["id"]
        body = item["body"].strip()
        match = REQUEST.fullmatch(body)
        if match:
            requests[number] = {"job": match.group(2), "id": number}
            continue
        result = REPLY.fullmatch(body)
        if result:
            target = int(result.group(1))
            replies.setdefault(target, []).append({
                "job": result.group(2),
                "status": result.group(3),
                "id": number,
            })

    def receipt_for(request: dict | None) -> dict:
        if request is None:
            return {"state": "no_request"}
        request_id = request["id"]
        answer = replies.get(request_id, [])
        if len(answer) != 1 or answer[0]["job"] != request["job"]:
            phase = "pending" if not answer else "ambiguous"
            return {"state": phase, "request_id": request_id,
                    "request_url": url_for(request_id)}
        value = answer[0]["status"]
        result = {
            "state": "reported_ok" if value.startswith("OK") else "reported_failure",
            "request_id": request_id,
            "request_url": url_for(request_id),
            "receipt_id": answer[0]["id"],
            "receipt_url": url_for(answer[0]["id"]),
            "job": request["job"],
        }
        if request["job"] == "nasu_research_status" and value.startswith("OK "):
            state_match = SAFE_STATE.search(value[3:])
            if state_match:
                result["study_state"] = state_match.group(1)
        return result

    def latest(names: set[str]) -> dict:
        candidates = [req for req in requests.values() if req["job"] in names]
        return receipt_for(max(candidates, key=lambda x: x["id"]) if candidates else None)

    server = latest(SERVER_NAMES)
    moltbook = latest(MOLTBOOK_READ_NAMES)
    pending = sum(receipt_for(r)["state"] == "pending" for r in requests.values())
    return {
        "schema": "nasuraya.fourway.audit.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "public_github_issue_149",
        "github": {
            "role": "code_tasks_and_receipts",
            "requests_seen": len(requests),
            "pending_requests": pending,
            "source_url": "https://github.com/" + REPO + "/issues/" + str(ISSUE),
        },
        "server": server,
        "moltbook": moltbook,
        "chatgpt": {
            "role": "on_demand_review_and_decision",
            "live_model_session_on_vps": False,
            "owner_approval_required_for_publication": True,
        },
        "controls": {
            "command_execution": False, "public_posting": False,
            "secret_access": False, "evidence_is_not_proof_of_live_health": True,
        },
    }


def url_for(comment_id: int) -> str:
    return ("https://github.com/" + REPO + "/issues/"
            + str(ISSUE) + "#issuecomment-" + str(comment_id))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GitHub/bridge/Moltbook receipt audit")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Read fixed public GitHub issue")
    group.add_argument("--from-file", help="Offline JSON list of GitHub comments")
    arguments = parser.parse_args()
    try:
        if arguments.live:
            comments = fetch_public_comments()
        else:
            with open(arguments.from_file, encoding="utf-8") as handle:
                comments = json.load(handle)
        report = audit_comments(comments)
    except (ValueError, OSError, TimeoutError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "nasuraya.fourway.audit.v1",
                          "state": "unverified",
                          "error_type": type(error).__name__},
                         separators=(",", ":")))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
