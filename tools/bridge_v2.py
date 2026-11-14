"""Nasuraya Bridge v2: pinned, fingerprinted job relay for owner's Windows VPS.

One Issue is the command queue. No arbitrary command or URL is accepted from comments.
Every job is Python source downloaded from a specific commit in owner's public repo,
and SHA-256 fingerprint must match the GitHub comment before execution.
The result posted back is deliberately tiny and non-sensitive.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import ssl
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler

REPO = "zurvanproject/zohraya"
OWNER = "zurvanproject"
ISSUE = 149
BASE = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "NasurayaBridge-v2"
JOB_RE = re.compile(r"^nasu: run ([0-9a-f]{40}) ([a-z][a-z0-9_]{1,39}) ([0-9a-f]{64})$", re.ASCII)
SAFE_REPLY_RE = re.compile(r"\A[a-zA-Z0-9 .,:;=/_()+-]{1,180}\Z", re.ASCII)
RESULT_RE = re.compile(r"request_id=(comment-[0-9]+);", re.ASCII)
MAX_JOB_BYTES = 24_000
MAX_NEW_JOBS_PER_POLL = 1
MAX_RESPONSE_BYTES = 100_000
JOB_TIMEOUT_SECONDS = 75
API_TIMEOUT_SECONDS = 25


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_verified(req):
    # Use certifi when present on the older Windows host; keep verification on.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return build_opener(ProxyHandler({}), NoRedirect(),
                        HTTPSHandler(context=context)).open(req, timeout=API_TIMEOUT_SECONDS)


def api_request(token: str, path: str, method: str = "GET", data: dict | None = None) -> Any:
    body = None if data is None else json.dumps(data, separators=(",", ":")).encode("utf-8")
    req = Request(
        BASE + path,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    with open_verified(req) as resp:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("API response size limit exceeded")
    return json.loads(raw.decode("utf-8"))


def get_comments(token: str) -> list[dict]:
    found: list[dict] = []
    for page in range(1, 35):
        items = api_request(token, f"/repos/{REPO}/issues/{ISSUE}/comments?per_page=30&page={page}")
        if not isinstance(items, list):
            raise TypeError("Comments API returned unexpected data")
        found.extend(items)
        if len(items) < 30:
            break
    else:
        raise RuntimeError("Comment page limit exceeded; refusing to process incomplete queue")
    return found


def done_requests(comments: list[dict]) -> set[str]:
    finished: set[str] = set()
    for c in comments:
        if c.get("user", {}).get("login") != OWNER:
            continue
        match = RESULT_RE.search(str(c.get("body", "")))
        if match and "Nasuraya Bridge" in str(c.get("body", "")):
            finished.add(match.group(1))
    return finished


def parse_job(body: str) -> tuple[str, str, str] | None:
    match = JOB_RE.fullmatch(body.strip())
    if match is None:
        return None
    return match.groups()


def download_job(commit: str, job: str, expected_sha256: str) -> bytes:
    url = f"{RAW}/{REPO}/{commit}/tools/bridge_jobs/{job}.py"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with open_verified(req) as resp:
        src = resp.read(MAX_JOB_BYTES + 1)
    if len(src) > MAX_JOB_BYTES:
        raise ValueError("Job source too large")
    actual = hashlib.sha256(src).hexdigest()
    if actual != expected_sha256:
        raise ValueError("Job fingerprint mismatch")
    return src


def safe_summary(stdout: str, exit_code: int) -> str:
    if exit_code != 0:
        return "JOB_FAILED"
    try:
        payload = json.loads(stdout.strip())
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return "INVALID_JOB_RESULT"
        summary = payload.get("summary", "")
        if not isinstance(summary, str) or not SAFE_REPLY_RE.fullmatch(summary):
            return "INVALID_JOB_RESULT"
        if any(word in summary.lower() for word in ("token", "password", "secret", "github_pat", "bearer")):
            return "INVALID_JOB_RESULT"
        return "OK " + summary
    except (ValueError, TypeError):
        return "INVALID_JOB_RESULT"


def execute_job(commit: str, job: str, digest: str, root: Path) -> str:
    source = download_job(commit, job, digest)
    jobs_dir = root / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    file_path = jobs_dir / (f"{job}_{digest[:16]}.py")
    file_path.write_bytes(source)
    # Do not pass the GitHub token to the job process.
    env = dict(os.environ)
    env.pop("NASURAYA_GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    try:
        p = subprocess.run(
            [sys.executable, "-I", str(file_path)],
            cwd=str(jobs_dir),
            env=env,
            text=True,
            capture_output=True,
            timeout=JOB_TIMEOUT_SECONDS,
            check=False,
        )
        return safe_summary(p.stdout[:1000], p.returncode)
    except subprocess.TimeoutExpired:
        return "JOB_TIMEOUT"
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass


def load_journal(root: Path) -> dict[str, dict]:
    journal_path = root / "v2_journal.json"
    if not journal_path.exists():
        return {}
    data = json.loads(journal_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid bridge journal")
    return data


def save_journal(root: Path, journal: dict[str, dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "v2_journal.tmp"
    dest = root / "v2_journal.json"
    tmp.write_text(json.dumps(journal, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, dest)


def poll(token: str, root: Path) -> tuple[int, int]:
    issue = api_request(token, f"/repos/{REPO}/issues/{ISSUE}")
    if issue.get("state") != "open" or issue.get("user", {}).get("login") != OWNER:
        return (0, 0)
    comments = get_comments(token)
    finished = done_requests(comments)
    journal = load_journal(root)
    new_count = 0
    for c in comments:
        if c.get("user", {}).get("login") != OWNER:
            continue
        request_id = f"comment-{c['id']}"
        if request_id in finished:
            continue
        job = parse_job(str(c.get("body", "")))
        if job is None:
            continue
        commit, name, digest = job
        record = journal.get(request_id)
        if record is None:
            # Prevent duplicate execution on crash or network timeout. A job with
            # 'started' state will never run a second time without manual review.
            journal[request_id] = {"state": "started", "job": name}
            save_journal(root, journal)
            try:
                result = execute_job(commit, name, digest, root)
            except (ValueError, OSError, HTTPError, URLError) as err:
                result = "JOB_NOT_EXECUTED"
                print(f"Job {request_id} failed: {type(err).__name__}", flush=True)
            journal[request_id] = {"state": "pending_post", "job": name, "result": result}
            save_journal(root, journal)
            record = journal[request_id]
        if record["state"] == "started":
            # Job outcome is uncertain; never re-execute automatically.
            continue
        if record["state"] == "posted":
            continue
        if record["state"] != "pending_post":
            continue
        body = (
            f"Nasuraya Bridge v2 result; request_id={request_id}; command=run {name}\n"
            f"Result: {record['result']}"
        )
        api_request(token, f"/repos/{REPO}/issues/{ISSUE}/comments", "POST", {"body": body})
        journal[request_id]["state"] = "posted"
        save_journal(root, journal)
        finished.add(request_id)
        new_count += 1
        if new_count >= MAX_NEW_JOBS_PER_POLL:
            break
    return (len(comments), new_count)


def main() -> int:
    token = os.environ.get("NASURAYA_GH_TOKEN", "")
    if not token or len(token) < 16:
        print("Bridge token unavailable. Start via Windows bridge.ps1 wrapper.")
        return 2
    root = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "NasurayaBridge"
    root.mkdir(parents=True, exist_ok=True)
    print("Nasuraya Bridge v2 started; GitHub Jobs relay is active.", flush=True)
    while True:
        try:
            total, newly = poll(token, root)
            # Written only after a successful authenticated poll. Startup alone
            # is not evidence of a working relay.
            health = root / "v2_health.tmp"
            health.write_text(json.dumps({"pid": os.getpid(), "utc_epoch": time.time(),
                                          "poll_ok": True}), encoding="utf-8")
            os.replace(health, root / "v2_health.json")
            print(f"Bridge poll complete: {total} comments; {newly} new jobs", flush=True)
        except (HTTPError, URLError, OSError, ValueError, KeyError, TypeError, RuntimeError) as err:
            print("Bridge poll error: " + type(err).__name__, flush=True)
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
