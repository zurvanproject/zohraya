"""Read-only fourway evidence gate: CI is not a real server receipt.

Combines previously inspected public GitHub CI status with the authenticated
GitHub *account*'s Bridge queue comments. Neither proves process identity,
real-world bodily simulation, nor current Moltbook activity. No commands run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import ssl
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler

if __package__:
    from .public_ci_witness import audit_snapshot
else:
    from public_ci_witness import audit_snapshot

SCHEMA = "nasuraya.fourway-evidence-gate.v02"
REPO = "zurvanproject/zohraya"
OWNER = "zurvanproject"
ISSUE = 149
MAX_COMMENTS = 1000
MAX_RESPONSE_BYTES = 1_000_000
MAX_PAGES = 10
BRIDGE_SCHEMA = "nasuraya.bridge-observations.v02"

ATLAS_COMMAND = (
    "nasu: run f1c93810abf83bea894ceda2801c3771716c5b30 "
    "nasu_wholebody_phase1 "
    "c0d984346b1c87f82b28225e76eada70880c1a795f9303d0e9250e193b106173"
)
STATUS_COMMAND = (
    "nasu: run f9ae14e28cacb1e21313ec4ba9b8cd1247e458fa "
    "nasu_research_status "
    "7627a9c3b53a0f18bd863b4b5febab1eecfd1f65280255a8bb471de35a137ff3"
)
MOLTBOOK_COMMAND = (
    "nasu: run 1987da5fc5ebed18cb43372b6ea776b0b4804629 "
    "moltbook_repair_retest "
    "8dc3d3cfba8f9862fedf4e7a079e44d34935801d36c84282697d581bcdce319d"
)
KNOWN = {
    6771977584: ("nasu_wholebody_phase1", ATLAS_COMMAND),
    6770326192: ("nasu_research_status", STATUS_COMMAND),
    6740249936: ("nasu_research_status", STATUS_COMMAND),
    6724967463: ("moltbook_repair_retest", MOLTBOOK_COMMAND),
}
REPLY_RE = re.compile(
    r"\ANasuraya Bridge v2 result; request_id=comment-([0-9]+); "
    r"command=run ([a-z][a-z0-9_]{1,39})\n"
    r"Result: ([A-Za-z0-9 .,:;=/_()+-]{1,190})\Z", re.ASCII,
)
REQ_ID_RE = re.compile(r"request_id=comment-([0-9]+)", re.ASCII)
FAILURES = frozenset((
    "JOB_FAILED", "JOB_TIMEOUT", "JOB_NOT_EXECUTED",
    "INVALID_JOB_RESULT", "JOB_NOT_AUTHORIZED",
))

FIELD_RE = re.compile(r"\\A([A-Z][A-Z0-9_]*)=([A-Za-z0-9._/+-]+)\\Z", re.ASCII)


def parse_summary_fields(raw: str) -> dict[str, str] | None:
    """Exact fields only: NODES=970 must never count as NODES=97."""
    if not isinstance(raw, str) or not raw.startswith("OK "):
        return None
    parts = raw[3:].split(";")
    values: dict[str, str] = {}
    for part in parts:
        m = FIELD_RE.fullmatch(part)
        if m is None or m.group(1) in values:
            return None
        values[m.group(1)] = m.group(2)
    return values



def public_comment_url(number: int) -> str:
    return ("https://github.com/" + REPO + "/issues/" + str(ISSUE)
            + "#issuecomment-" + str(number))


def owner_comment(comment: dict) -> bool:
    return (
        isinstance(comment, dict) and
        type(comment.get("id")) is int and comment["id"] > 0 and
        isinstance(comment.get("user"), dict) and
        comment["user"].get("login") == OWNER and
        isinstance(comment.get("body"), str) and
        len(comment["body"]) <= 1000
    )


def extract_pair(comments: list[dict], request_id: int) -> dict:
    name, expected = KNOWN[request_id]
    request = [x for x in comments if owner_comment(x)
               and x["id"] == request_id and x["body"].strip() == expected]
    if len(request) != 1:
        return {"state": "REQUEST_UNVERIFIED", "request_id": request_id,
                "request_url": public_comment_url(request_id)}
    related = []
    for item in comments:
        if not owner_comment(item):
            continue
        body = item["body"].strip()
        m = REQ_ID_RE.search(body)
        if not m or int(m.group(1)) != request_id:
            continue
        parsed = REPLY_RE.fullmatch(body)
        if parsed is None or parsed.group(2) != name:
            return {"state": "CONFLICT", "request_id": request_id,
                    "request_url": public_comment_url(request_id),
                    "reason": "malformed_or_wrong_job_reply"}
        related.append((item["id"], parsed.group(3)))
    if not related:
        return {"state": "QUEUED_NO_RECEIPT", "request_id": request_id,
                "request_url": public_comment_url(request_id)}
    if len(related) > 1:
        return {"state": "CONFLICT", "request_id": request_id,
                "request_url": public_comment_url(request_id),
                "reason": "multiple_reply_records"}
    reply_id, result = related[0]
    return {
        "state": "OWNER_ACCOUNT_REPORTED",
        "request_id": request_id,
        "request_url": public_comment_url(request_id),
        "reply_id": reply_id,
        "reply_url": public_comment_url(reply_id),
        "job": name,
        "result": result,
        "evidence_tier": "github_owner_account_report_not_server_signature",
    }


def atlas_status(record: dict) -> dict:
    result = dict(record)
    if record["state"] != "OWNER_ACCOUNT_REPORTED":
        return result
    raw = record["result"]
    fields = parse_summary_fields(raw)
    required = {
        "ATLAS": "INVENTORY", "NODES": "97", "SYSTEMS": "12",
        "ROUTES": "31", "EXTRA": "35", "PHYSICS": "UNVERIFIED",
    }
    if fields is not None and all(fields.get(k) == v for k, v in required.items()):
        result["state"] = "REPORTED_INVENTORY"
        result["not_physical_body"] = True
    elif raw in FAILURES or raw.startswith("OK FAIL="):
        result["state"] = "REPORTED_FAILURE"
    else:
        result["state"] = "REVIEW_REQUIRED"
    del result["result"]
    return result


def research_status(record: dict, historical: bool = False) -> dict:
    result = dict(record)
    if record["state"] != "OWNER_ACCOUNT_REPORTED":
        if record["state"] == "QUEUED_NO_RECEIPT":
            result["state"] = "STATUS_REQUEST_PENDING"
        return result
    raw = record["result"]
    fields = parse_summary_fields(raw)
    if (fields is not None and fields.get("STATE") == "COMPLETED" and
            fields.get("BAD") == "0" and fields.get("TF") == "0"):
        result["state"] = "REPORTED_COMPLETED_NO_TEST_FAILURE"
    elif fields is not None and fields.get("STATE") == "RUNNING":
        result["state"] = "REPORTED_RUNNING"
    elif raw in FAILURES or raw.startswith("OK FAIL="):
        result["state"] = "REPORTED_FAILURE"
    else:
        result["state"] = "REVIEW_REQUIRED"
    result["historical_not_current"] = historical
    del result["result"]
    return result


def moltbook_status(record: dict) -> dict:
    result = dict(record)
    if record["state"] != "OWNER_ACCOUNT_REPORTED":
        return result
    raw = record["result"]
    fields = parse_summary_fields(raw)
    if fields is not None and fields.get("REPAIR") == "REPLAY" and fields.get("GET") == "0":
        result["state"] = "HISTORICAL_REPLAY_ONLY"
    else:
        result["state"] = "NOT_PROOF_OF_FRESH_MOLTBOOK_READ"
    result["direct_current_moltbook_confirmed"] = False
    del result["result"]
    return result


def reconcile(ci_fixture: dict, bridge_fixture: dict) -> dict:
    if (not isinstance(bridge_fixture, dict) or
            bridge_fixture.get("schema") != BRIDGE_SCHEMA or
            bridge_fixture.get("repository") != REPO or
            bridge_fixture.get("issue_number") != ISSUE):
        raise ValueError("invalid_bridge_fixture_source")
    comments = bridge_fixture.get("comments")
    if not isinstance(comments, list) or len(comments) > MAX_COMMENTS:
        raise ValueError("incomplete_or_invalid_public_comment_input")
    ids = [c.get("id") for c in comments if isinstance(c, dict)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_comment_id")
    audit = audit_snapshot(ci_fixture)
    runs = {r["run_id"]: r for r in audit["runs"]}
    body_ci = runs.get(42846878619, {}).get("verdict", "NOT_OBSERVED")
    fourway_ci = runs.get(42841363043, {}).get("verdict", "NOT_OBSERVED")
    atlas = atlas_status(extract_pair(comments, 6771977584))
    research_latest = research_status(extract_pair(comments, 6770326192))
    research_previous = research_status(extract_pair(comments, 6740249936),
                                        historical=True)
    moltbook = moltbook_status(extract_pair(comments, 6724967463))
    # Green CI never upgrades the VPS or current Moltbook state.
    return {
        "schema": SCHEMA,
        "github_ci": {
            "observed_public_runs": audit["distinct_run_count"],
            "passed": audit["verdict_counts"]["PASSED"],
            "failed": audit["verdict_counts"]["FAILURE"],
            "body_atlas_offline_ci": body_ci,
            "fourway_offline_ci": fourway_ci,
            "not_live_vps_evidence": True,
        },
        "vps": {
            "atlas_phase1": atlas,
            "research_fresh_request": research_latest,
            "research_previous_historical": research_previous,
            "server_liveness_independently_verified": False,
        },
        "moltbook": moltbook,
        "chatgpt": {
            "role": "interactive_human_supervised_reviewer",
            "continuous_session_on_vps_proven": False,
            "model_memory_changed": False,
        },
        "whole_fourway_status": "NOT_LIVE_VERIFIED",
        "no_new_command_dispatched": True,
        "reading_is_not_authorization": True,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_live_issue_comments() -> list[dict]:
    """Optional public GitHub GET only; complete pages or fail closed."""
    opener = build_opener(ProxyHandler({}), NoRedirect(),
                          HTTPSHandler(context=ssl.create_default_context()))
    output: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = (
            "https://api.github.com/repos/" + REPO +
            "/issues/149/comments?per_page=100&page=" + str(page)
        )
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "NasurayaFourwayEvidenceReadOnly-v02",
        })
        with opener.open(request, timeout=12) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if response.url != url or len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("invalid_or_oversized_public_response")
        comments = json.loads(data.decode("utf-8"))
        if (not isinstance(comments, list) or
                not all(isinstance(x, dict) for x in comments)):
            raise ValueError("malformed_public_response")
        output.extend(comments)
        if len(output) > MAX_COMMENTS:
            raise ValueError("public_comments_limit")
        if len(comments) < 100:
            return output
    raise ValueError("pagination_incomplete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--ci-file", type=Path, default=(
        root / "docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json"
    ))
    parser.add_argument("--bridge-file", type=Path, default=(
        root / "docs/evidence/fourway-evidence-v02/frozen-bridge-comments.json"
    ))
    parser.add_argument("--live", action="store_true",
                        help="Read fixed public GitHub issue (no token, no writes)")
    args = parser.parse_args()
    try:
        ci = json.loads(args.ci_file.read_text(encoding="utf-8"))
        bridge = json.loads(args.bridge_file.read_text(encoding="utf-8"))
        if args.live:
            bridge["comments"] = fetch_live_issue_comments()
        result = reconcile(ci, bridge)
    except (ValueError, OSError, TimeoutError) as err:
        print(json.dumps({"schema": SCHEMA, "status": "UNVERIFIED",
                          "error_type": type(err).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
