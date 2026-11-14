#!/usr/bin/env python3
"""Nasuraya Ubuntu Bridge: GitHub issue relay with fixed, bounded commands.
Runs as the unprivileged nasuraya account. Never executes submitted shell text.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER = "zurvanproject"
REPO = "zurvanproject/zohraya"
ISSUE = 212
BASE = "https://api.github.com"
HOME = pathlib.Path("/var/lib/nasuraya")
TOKEN_PATH = HOME / "github-token"
SEEN_PATH = HOME / "seen.json"
PROJECT = HOME / "zohraya"
COMMAND_RE = re.compile(r"(?m)^\s*nasu-linux:\s*(status|disk|python|repo|sync|test|offline|awake-stage|awake-status|awake-activate|workload-stage|workload-status|help)\s*$", re.I)
RESULT_RE = re.compile(r"(?m)^nasu-linux-result request_id=(\d+)\b")

def api(method, path, data=None):
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Nasuraya-Linux-Bridge/1.0",
    }
    payload = None if data is None else json.dumps(data).encode("utf-8")
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=25) as resp:
        raw = resp.read(500_000)
        return json.loads(raw.decode("utf-8"))

def command(argv, timeout=30, cwd=PROJECT):
    try:
        result = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                                timeout=timeout, check=False, env={
                                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                                    "HOME": str(HOME), "LANG": "C.UTF-8",
                                })
        output = (result.stdout + "\n" + result.stderr).strip()
        return "exit=" + str(result.returncode) + "\n" + output[:2600]
    except subprocess.TimeoutExpired:
        return "Timed out after " + str(timeout) + " seconds"
    except Exception as exc:
        return "Execution error: " + type(exc).__name__

def dispatch(action):
    if action == "status":
        return command(["/usr/bin/uname", "-a"]) + "\n" + command(["/usr/bin/uptime"])
    if action == "disk":
        return command(["/usr/bin/df", "-h", "/"]) + "\n" + command(["/usr/bin/free", "-h"])
    if action == "python":
        return command(["/usr/bin/python3", "--version"])
    if action == "repo":
        return command(["/usr/bin/git", "status", "--short", "--branch"]) + "\n" + command(
            ["/usr/bin/git", "rev-parse", "--short", "HEAD"])
    if action == "sync":
        return command(["/usr/bin/git", "pull", "--ff-only", "origin", "main"], timeout=75)
    if action == "test":
        return command(["/usr/bin/python3", "-m", "unittest", "discover",
                        "-s", "examples/nasuraya_agent_loop/tests", "-v"], timeout=120)
    if action == "offline":
        return command(["/usr/bin/python3", "/usr/local/lib/nasuraya/continuity.py", "status"]) + "\n" + command(
            ["/usr/bin/python3", "/usr/local/lib/nasuraya/continuity.py", "verify"])
    if action == "awake-stage":
        return command(["/usr/bin/bash", str(PROJECT / "tools/nasuraya_stage_awake_unprivileged.sh")], timeout=180)
    if action == "awake-status":
        return command(["/usr/bin/python3", "/usr/local/lib/nasuraya/awake_health.py"], cwd=HOME)
    if action == "awake-activate":
        return command(["/usr/bin/python3", "/usr/local/lib/nasuraya/awake_activate.py"], timeout=20)
    if action == "workload-stage":
        return command(["/usr/bin/python3", "/usr/local/lib/nasuraya/workload_sources.py", "stage-next"], timeout=180, cwd=HOME)
    if action == "workload-status":
        return command(["/usr/bin/python3", "/usr/local/lib/nasuraya/workload_sources.py", "status"], cwd=HOME)
    return "Allowed: status, disk, python, repo, sync, test, offline, awake-stage, awake-status, awake-activate, workload-stage, workload-status, help. No arbitrary shell."

def all_comments():
    comments = []
    page = 1
    while True:
        batch = api("GET", f"/repos/{REPO}/issues/{ISSUE}/comments?per_page=100&page={page}")
        comments.extend(batch)
        if len(batch) < 100:
            return comments
        page += 1

def seen_load():
    if not SEEN_PATH.exists():
        return set()
    return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))

def seen_save(seen):
    temp = SEEN_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(SEEN_PATH)

def poll():
    issue = api("GET", f"/repos/{REPO}/issues/{ISSUE}")
    if issue.get("state") != "open" or issue.get("user", {}).get("login") != OWNER:
        raise RuntimeError("Expected issue owner/open state mismatch")
    comments = all_comments()
    completed = set()
    for item in comments:
        if item.get("user", {}).get("login") == OWNER:
            match = RESULT_RE.search(item.get("body", ""))
            if match:
                completed.add(match.group(1))
    seen = seen_load()
    for item in comments:
        if item.get("user", {}).get("login") != OWNER:
            continue
        body = item.get("body", "")
        match = COMMAND_RE.search(body)
        if not match:
            continue
        request_id = str(item["id"])
        if request_id in completed or request_id in seen:
            continue
        action = match.group(1).lower()
        result = dispatch(action)
        receipt = (
            f"nasu-linux-result request_id={request_id}\n"
            f"action={action}; utc={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
            f"host=ubuntu-iran; result:\n```text\n{result[:3500]}\n```"
        )
        api("POST", f"/repos/{REPO}/issues/{ISSUE}/comments", {"body": receipt})
        seen.add(request_id)
        seen_save(seen)
        print("Completed request", request_id, action, flush=True)

def main():
    if os.geteuid() == 0:
        sys.exit("Refusing to run as root")
    if api("GET", "/user").get("login") != OWNER:
        sys.exit("GitHub token must belong to repository owner")
    print("Nasuraya Linux Bridge online; issue #212", flush=True)
    while True:
        try:
            poll()
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            print("Poll error:", type(exc).__name__, str(exc)[:180], flush=True)
        time.sleep(40)

if __name__ == "__main__":
    main()

