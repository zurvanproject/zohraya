#!/usr/bin/env python3
"""Apply only PR292's cognitive executable from a fixed reviewed Git object.

Administrator console only. No Bridge extension, model call, journal write,
release repointing, downloads or generated-code execution. Old diagnostics may
still report a release mismatch: that reference is deliberately not rewritten.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import types

REVISION = "324537b4cf83496bc065ec1ecb34d109eb3e37b3"
BEFORE = "157193be1608e1b87044369ba0dcfb1e7471e8c39d85b08430e48aa1b797a149"
AFTER = "797669845a680dfc408482c16513e254267323597fff49e3af458e315eee4fe5"
SUPPORT_SHA = "73da4a501851df53dc0407bea0079c8d8b558fc7409613b2196787c25cf502ba"
PROJECT = "/opt/zohraya"


def pinned_blob(name, expected, *, project=PROJECT):
    if name not in ("tools/nasu_autonomous_cognition.py", "tools/install_nasu_server_agent.py"):
        raise ValueError("UNEXPECTED_SOURCE")
    raw = subprocess.run(
        ["/usr/bin/git", "-c", "safe.directory=" + project, "-C", project,
         "show", REVISION + ":" + name], check=True, capture_output=True,
        timeout=20, env={"PATH": "/usr/bin:/bin", "LANG": "C", "GIT_NO_REPLACE_OBJECTS": "1"}).stdout
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("SOURCE_DIGEST_MISMATCH")
    compile(raw, name, "exec")
    return raw


def support():
    name = "tools/install_nasu_server_agent.py"
    raw = pinned_blob(name, SUPPORT_SHA)
    module = types.ModuleType("nasu_reviewed_deployment_support")
    module.__file__ = name
    exec(compile(raw, name, "exec"), module.__dict__)
    return module


def apply_runtime(dep, raw):
    dep.require(dep.digest(raw) == AFTER, "UNREVIEWED_REPLACEMENT")
    compile(raw, str(dep.COGNITION), "exec")
    dep.guarded(dep.COGNITION.parent, required=True, directory=True)
    original = dep.read_file(dep.COGNITION)
    current = dep.digest(original)
    dep.require(current in (BEFORE, AFTER), "UNKNOWN_INSTALLED_COGNITION")
    # Never turn a retry after a failed restoration into a false success.
    snapshot = dep.Snapshot(dep.BACKUPS / ("cognition-pr292-" + REVISION), targets=(dep.COGNITION,))
    if snapshot.manifest.exists():
        snapshot.load()
        dep.require(snapshot.data["phase"] == "installed", "PRIOR_ATTEMPT_REQUIRES_REVIEW")
        snapshot.check("desired")
        dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == snapshot.data["states"]["cognitive_timer"],
                    "TIMER_STATE_DIFFERS_FROM_RECEIPT")
        return {"UPDATE": "ALREADY_APPLIED", "installed_sha256": AFTER}
    dep.require(current == BEFORE, "CORRECTED_FILE_WITHOUT_INSTALL_RECEIPT")
    row = dep.unit_state(dep.COGNITIVE_SERVICE)
    starts = re.findall(r"argv\[\]=([^;]*);", row.get("ExecStart", ""))
    argv = shlex.split(starts[0]) if len(starts) == 1 else []
    if len(argv) >= 2 and argv[1] in ("-B", "-u"):
        argv.pop(1)
    dep.require(row.get("LoadState") == "loaded" and row.get("User") == "nasuraya" and
                row.get("FragmentPath") == str(dep.SYSTEM / dep.COGNITIVE_SERVICE) and
                argv == ["/usr/bin/python3", str(dep.COGNITION), "run"], "UNKNOWN_COGNITIVE_SERVICE")
    dep.require(dep.unit_state(dep.BRIDGE_SERVICE).get("ActiveState") == "active", "BRIDGE_NOT_ACTIVE")
    timer = dep.timer_state(dep.COGNITIVE_TIMER)
    desired = {dep.COGNITION: raw}
    dep.quiesce_cognition(timer, "COGNITION_RUNNING_RETRY_AFTER_REVIEW")
    try:
        snapshot.create(REVISION, desired, {"cognitive_timer": timer, "bridge_active": True})
    except BaseException:
        dep.restore_timer(dep.COGNITIVE_TIMER, timer)
        raise
    try:
        snapshot.apply(desired)
        dep.require(dep.digest(dep.read_file(dep.COGNITION)) == AFTER, "POST_WRITE_DIGEST_MISMATCH")
        dep.restore_timer(dep.COGNITIVE_TIMER, timer)
        dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == timer, "TIMER_RESTORE_MISMATCH")
        snapshot.data["phase"] = "installed"
        snapshot.save()
        return {"UPDATE": "APPLIED_RUNTIME_ONLY", "revision": REVISION,
                "installed_sha256": AFTER, "timer_restored": True,
                "model_inference_tested": False, "legacy_diagnostics_repointed": False}
    except BaseException:
        try:
            # Refuse a rollback during inference; never kill a running job.
            dep.quiesce_cognition(timer, "COGNITION_RUNNING_ROLLBACK_BLOCKED")
            snapshot.restore_files()
            dep.restore_timer(dep.COGNITIVE_TIMER, timer)
            dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == timer, "TIMER_RESTORE_MISMATCH")
            snapshot.data["phase"] = "rolled_back"
            snapshot.save()
        except BaseException:
            # Always attempt timer restoration, even if file restoration failed.
            try:
                dep.restore_timer(dep.COGNITIVE_TIMER, timer)
            finally:
                snapshot.data["phase"] = "rollback_failed"
                snapshot.save()
            raise dep.DeployError("ROLLBACK_INCOMPLETE_REQUIRES_ADMIN_REVIEW") from None
        raise dep.DeployError("UPDATE_FAILED_ROLLED_BACK") from None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--apply"] or os.geteuid() != 0:
        print('{"UPDATE":"BLOCKED","reason":"ADMIN_CONSOLE_AND_APPLY_REQUIRED"}')
        return 1
    os.umask(0o077)
    dep = None
    lock_fd = None
    try:
        dep = support()
        raw = pinned_blob("tools/nasu_autonomous_cognition.py", AFTER)
        lock = dep.guarded(Path("/run/lock/nasuraya-agent-deploy.lock"))
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(lock_fd)
        dep.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                    "UNTRUSTED_DEPLOYMENT_LOCK")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = apply_runtime(dep, raw)
        print(dep.canonical(result).decode().strip())
        return 0
    except Exception as exc:
        # Error text and subprocess output can contain private paths/data.
        reason = str(exc) if dep is not None and isinstance(exc, dep.DeployError) else type(exc).__name__
        import json
        print(json.dumps({"UPDATE": "BLOCKED", "reason": reason}))
        return 1
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
