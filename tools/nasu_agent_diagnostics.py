#!/usr/bin/env python3
"""Fixed, metadata-only diagnostics for the deployed offline agent.

``status`` never generates model output, initializes a database, or changes a
service. ``probe`` additionally makes ONE bounded inference request to local
Ollama. The CLI has no path, unit, prompt, model, URL or shell arguments.
Historical draft counts do not prove current service health or model quality.
Read-only SQLite can use WAL/SHM coordination files; it does not ignore WAL.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request

from tools import nasu_autonomous_cognition as cognition

SCHEMA = "nasuraya-agent-diagnostics/1"
HOME = Path("/var/lib/nasuraya")
INSTALLED_COGNITION = Path("/usr/local/lib/nasuraya/nasu_autonomous_cognition.py")
RELEASE_COGNITION = Path(__file__).resolve().with_name("nasu_autonomous_cognition.py")
LOCAL_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3:4b-instruct"
MAX_RESPONSE = 8192
MAX_OUTPUT = 2199
MAX_ROWS = 20000
UNITS = {
    "ollama": "ollama.service",
    "cognition": "nasuraya-cognitive-growth.service",
    "cognition_timer": "nasuraya-cognitive-growth.timer",
    "integration": "nasuraya-agent-integration.service",
    "integration_timer": "nasuraya-agent-integration.timer",
}
PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result",
              "ExecMainStatus", "NextElapseUSecRealtime", "LastTriggerUSec")
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
       "TZ": "UTC", "SYSTEMD_COLORS": "0", "SYSTEMD_PAGER": "cat"}
LOAD_STATES = {"loaded", "not-found", "masked", "error", "bad-setting", "stub", "merged"}
ACTIVE_STATES = {"active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance", "refreshing"}
SUB_STATES = {"running", "exited", "dead", "failed", "waiting", "elapsed",
              "start", "start-pre", "start-post", "auto-restart", "stop", "stop-sigterm", "stop-sigkill", "reload"}
RESULTS = {"success", "exit-code", "timeout", "signal", "core-dump", "watchdog",
           "start-limit-hit", "resources", "protocol", "dependency", "oom-kill", "exec-condition", "assert"}
COLUMNS = ("slot", "stamp", "topic", "source_path", "source_sha", "fixed_result",
           "model_status", "proposal", "next_topic", "previous_sha", "receipt_sha", "state")


def _guard(path):
    path = Path(os.path.abspath(os.fspath(path)))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlinked_source")
    return path


def _slot(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}", value):
        raise ValueError("invalid_slot")
    parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H")
    if parsed.hour not in (0, 6, 12, 18):
        raise ValueError("invalid_cognitive_slot")
    return value


def _model_status(value):
    if value == "UNVERIFIED_DRAFT":
        return value
    if isinstance(value, str):
        for prefix in ("model_unavailable", "source_unavailable", "test_unavailable"):
            if value.startswith(prefix + ":"):
                return prefix
    raise ValueError("unknown_model_status")


def cognitive_status(home=HOME):
    """Verify and project a single existing SQLite read snapshot, never init."""
    try:
        path = _guard(Path(home) / "cognitive-growth/cycles.sqlite3")
        if not path.exists():
            return {"state": "missing"}
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("invalid_database_file")
        for suffix in ("-wal", "-shm", "-journal"):
            _guard(Path(str(path) + suffix))
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            deadline = time.monotonic() + 4
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            columns = tuple(row[1] for row in db.execute("PRAGMA table_info(cycles)"))
            if columns != COLUMNS:
                raise ValueError("unknown_schema")
            count = db.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
            if count > MAX_ROWS:
                raise ValueError("journal_too_large")
            if db.execute("SELECT 1 FROM cycles WHERE state NOT IN ('completed','reserved') OR state IS NULL LIMIT 1").fetchone():
                raise ValueError("unknown_cycle_state")
            checked = cognition.verify(db)
            rows = db.execute("SELECT slot,model_status FROM cycles WHERE state='completed' ORDER BY slot").fetchall()
            drafts = 0
            last_successful = None
            latest = None
            for slot, model_status in rows:
                slot, model_status = _slot(slot), _model_status(model_status)
                latest = {"slot": slot, "model": model_status}
                if model_status == "UNVERIFIED_DRAFT":
                    drafts += 1
                    last_successful = slot
            return {"state": "incomplete" if checked["incomplete"] else "verified_history" if rows else "empty",
                    "completed": checked["completed"], "incomplete": checked["incomplete"],
                    "drafts": drafts, "failed": len(rows) - drafts,
                    "latest": latest, "last_successful_slot": last_successful}
        finally:
            db.close()
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError, RuntimeError):
        return {"state": "invalid"}


def _systemd_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", value):
        return None
    try:
        return dt.datetime.strptime(value[4:-4], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def service_status(*, runner=None):
    """Only fixed systemctl show commands; never echo stdout/stderr verbatim."""
    runner = runner or subprocess.run
    out = {}
    for key, unit in UNITS.items():
        args = ["/usr/bin/systemctl", "show", unit, "--no-pager"]
        args.extend("--property=" + prop for prop in PROPERTIES)
        try:
            result = runner(args, capture_output=True, text=True, timeout=3,
                            check=False, env=dict(ENV))
            if result.returncode != 0 or not isinstance(result.stdout, str) or len(result.stdout) > 16384:
                raise ValueError("systemctl_unavailable")
            values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            row = {"load": values.get("LoadState") if values.get("LoadState") in LOAD_STATES else "unknown",
                   "active": values.get("ActiveState") if values.get("ActiveState") in ACTIVE_STATES else "unknown",
                   "sub": values.get("SubState") if values.get("SubState") in SUB_STATES else "unknown"}
            if unit.endswith(".timer"):
                row["next"] = _systemd_time(values.get("NextElapseUSecRealtime"))
                row["last"] = _systemd_time(values.get("LastTriggerUSec"))
            else:
                row["result"] = values.get("Result") if values.get("Result") in RESULTS else "unknown"
                code = values.get("ExecMainStatus", "")
                row["exit"] = int(code) if re.fullmatch(r"\d{1,3}", code) and int(code) <= 255 else None
            out[key] = row
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            out[key] = {"state": "unavailable"}
    return out


def _file_hash(path):
    try:
        path = _guard(path)
        if not path.exists():
            return "missing"
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            return "invalid"
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return "invalid"


def executable_status():
    installed, release = _file_hash(INSTALLED_COGNITION), _file_hash(RELEASE_COGNITION)
    comparable = re.fullmatch(r"[0-9a-f]{64}", installed) and re.fullmatch(r"[0-9a-f]{64}", release)
    return {"installed": installed, "release": release,
            "match": installed == release if comparable else None}


def integration_status(home=HOME):
    """Import the independent status reader lazily; it must not import us."""
    try:
        from tools import nasu_live_integration as live
    except ImportError:
        return {"state": "missing_module"}
    try:
        result = live.status(state=Path(home) / "agent-integration")
        state = result.get("status", result.get("state"))
        out = {"state": state if state in {"ok", "missing", "invalid", "empty", "verified_history", "incomplete"} else "unknown"}
        count = result.get("records")
        if type(count) is int and 0 <= count <= 100000000:
            out["records"] = count
        latest = result.get("latest")
        if isinstance(latest, dict):
            hour = latest.get("hour")
            if isinstance(hour, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:00Z", hour):
                dt.datetime.strptime(hour, "%Y-%m-%dT%H:00Z")
                out["hour"] = hour
        return out
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RuntimeError, AttributeError):
        return {"state": "invalid"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise ValueError("redirect_refused")


def probe_model(*, opener=None):
    """ONE fixed inference. No remote URLs/proxies/redirects; no response text."""
    payload = {"model": MODEL, "stream": False, "think": False,
               "prompt": "/no_think Reply with exactly one word: READY",
               "keep_alive": "2m",
               "options": {"temperature": 0, "num_ctx": 512, "num_predict": 64}}
    request = urllib.request.Request(LOCAL_URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open
        with client(request, timeout=90) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("oversized_model_response")
        result = json.loads(raw)
        if (not isinstance(result, dict) or result.get("done") is not True or
                result.get("model") != MODEL or result.get("response", "").strip() != "READY"):
            raise ValueError("invalid_model_response")
        return {"state": "success", "sha256": hashlib.sha256(b"READY").hexdigest()}
    except (OSError, ValueError, TypeError, AttributeError, TimeoutError, UnicodeError):
        return {"state": "failed"}


def collect(mode="status", *, home=HOME, now=None, runner=None):
    if mode not in ("status", "probe"):
        raise ValueError("invalid_mode")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC_required")
    result = {"schema": SCHEMA, "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": mode,
              "units": service_status(runner=runner), "cognition": cognitive_status(home),
              "executables": executable_status(), "integration": integration_status(home)}
    if mode == "probe":
        result["probe"] = probe_model()
    return result


def compact(result):
    text = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(text) > MAX_OUTPUT:
        # Do not truncate JSON, publish private overflow, or claim success.
        return json.dumps({"schema": SCHEMA, "state": "output_limit"}, separators=(",", ":"))
    return text


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if os.geteuid() == 0:
        print(compact({"schema": SCHEMA, "state": "root_refused"}))
        return 2
    if len(argv) != 1 or argv[0] not in ("status", "probe"):
        print(compact({"schema": SCHEMA, "state": "usage_status_or_probe"}))
        return 2
    result = collect(argv[0])
    print(compact(result))
    return 1 if argv[0] == "probe" and result["probe"]["state"] != "success" else 0


if __name__ == "__main__":
    raise SystemExit(main())
