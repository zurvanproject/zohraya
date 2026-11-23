#!/usr/bin/env python3
"""Admin-console-only, SHA-pinned Qwen timeout pilot. Never callable via Bridge.

Preflight makes no changes; --apply stages runtime + systemd drop-in together,
--rollback restores both. Never runs a model, edits journals or downloads files.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import types

from tools import install_nasu_server_agent as dep

REVISION = "90bff4fee3954b9e1b9c5d7a384fd5bc61fb8c77"
BEFORE = "797669845a680dfc408482c16513e254267323597fff49e3af458e315eee4fe5"
EXPECTED_BLOB = "2f316ff20aa18cfb91c23e7b20108515861501f0"
DROPIN = dep.SYSTEM / (dep.COGNITIVE_SERVICE + ".d") / "90-nasuraya-qwen-timeout.conf"
BACKUP = dep.BACKUPS / ("cognition-timeout-" + REVISION)
DROPIN_BYTES = b'[Service]\nEnvironment="NASU_COGNITION_HTTP_TIMEOUT_SECONDS=300"\nTimeoutStartSec=420\n'
PATH = "tools/nasu_autonomous_cognition.py"


def pinned_runtime():
    # Source is an immutable reviewed commit and exact Git blob, never working-tree bytes.
    base = ["/usr/bin/git", "-c", "safe.directory=" + str(dep.PROJECT),
            "-C", str(dep.PROJECT)]
    env = dict(dep.ENV, GIT_NO_REPLACE_OBJECTS="1")
    raw = subprocess.run(base + ["show", REVISION + ":" + PATH],
                         capture_output=True, check=True, timeout=20, env=env).stdout
    dep.require(0 < len(raw) <= 1024 * 1024, "INVALID_RELEASE_BLOB")
    blob = subprocess.run(base + ["hash-object", "--stdin"],
                          input=raw, capture_output=True, check=True, timeout=10,
                          env=env).stdout.decode().strip()
    dep.require(blob == EXPECTED_BLOB, "RELEASE_BLOB_CHANGED")
    compile(raw, PATH, "exec")
    return raw


def guard_service():
    row = dep.unit_state(dep.COGNITIVE_SERVICE)
    starts = re.findall(r"argv\[\]=([^;]*);", row.get("ExecStart", ""))
    argv = shlex.split(starts[0]) if len(starts) == 1 else []
    if len(argv) >= 2 and argv[1] in ("-B", "-u"):
        argv.pop(1)
    dep.require(row.get("LoadState") == "loaded" and row.get("User") == "nasuraya"
                and row.get("FragmentPath") == str(dep.SYSTEM / dep.COGNITIVE_SERVICE)
                and argv == ["/usr/bin/python3", str(dep.COGNITION), "run"],
                "UNKNOWN_COGNITIVE_SERVICE")
    dep.require(dep.unit_state(dep.BRIDGE_SERVICE).get("ActiveState") == "active",
                "BRIDGE_NOT_ACTIVE")
    env = row.get("Environment", "")
    dep.require("NASU_COGNITION_HTTP_TIMEOUT_SECONDS" not in env,
                "EXISTING_TIMEOUT_OVERRIDE")


def get_effective():
    # No shell and no output of environment or secrets.
    result = dep.execute(["/usr/bin/systemctl", "show", dep.COGNITIVE_SERVICE,
                          "--property=TimeoutStartUSec", "--property=Environment",
                          "--no-pager"], timeout=10)
    values = dict(line.split("=", 1) for line in result.stdout.decode().splitlines()
                  if "=" in line)
    return values


def pilot_effective():
    info = get_effective()
    limit = info.get("TimeoutStartUSec", "")
    key = "NASU_COGNITION_HTTP_TIMEOUT_SECONDS"
    assignments = [item for item in shlex.split(info.get("Environment", ""))
                   if item.partition("=")[0] == key]
    # systemctl normally renders 7min; accept a few equivalent fixed forms.
    dep.require(limit in ("7min", "7min 0s", "420s", "420000000us")
                and assignments == [key + "=300"], "EFFECTIVE_PILOT_UNIT_MISMATCH")


def preflight(raw):
    dep.require(dep.digest(dep.read_file(dep.COGNITION)) == BEFORE, "UNKNOWN_INSTALLED_COGNITION")
    dep.guarded(DROPIN, owner=0)
    dep.require(not DROPIN.exists(), "EXISTING_QWEN_PILOT_DROPIN")
    dep.require(not BACKUP.exists(), "BACKUP_ALREADY_EXISTS")
    guard_service()
    timer = dep.timer_state(dep.COGNITIVE_TIMER)
    dep.require(not dep.unit_state(dep.COGNITIVE_SERVICE).get("ActiveState") == "active",
                "COGNITION_RUNNING")
    dep.require(dep.digest(raw) != BEFORE, "NOT_AN_UPDATED_RELEASE")
    return timer


def apply(raw):
    dep.require(os.geteuid() == 0, "ROOT_REQUIRED")
    timer = preflight(raw)
    desired = {dep.COGNITION: raw, DROPIN: DROPIN_BYTES}
    dep.quiesce_cognition(timer, "COGNITION_RUNNING")
    try:
        snapshot = dep.Snapshot(BACKUP, targets=(dep.COGNITION, DROPIN))
        snapshot.create(REVISION, desired, {"cognitive_timer": timer, "bridge_active": True})
    except BaseException:
        dep.restore_timer(dep.COGNITIVE_TIMER, timer)
        raise
    try:
        snapshot.apply(desired)
        dep.systemctl("daemon-reload")
        pilot_effective()
        dep.restore_timer(dep.COGNITIVE_TIMER, timer)
        dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == timer, "TIMER_RESTORE_MISMATCH")
        snapshot.data["phase"] = "installed"
        snapshot.save()
        return {"state": "installed_pilot", "model_tested": False,
                "runtime_sha256": dep.digest(raw), "rollback_available": True}
    except BaseException:
        try:
            dep.quiesce_cognition(timer, "COGNITION_RUNNING_ROLLBACK_BLOCKED")
            snapshot.restore_files()
            dep.systemctl("daemon-reload")
            dep.restore_timer(dep.COGNITIVE_TIMER, timer)
            dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == timer, "TIMER_RESTORE_MISMATCH")
            snapshot.data["phase"] = "rolled_back"
            snapshot.save()
        except BaseException:
            snapshot.data["phase"] = "rollback_failed"
            snapshot.save()
            raise dep.DeployError("ROLLBACK_INCOMPLETE_ADMIN_REVIEW") from None
        raise dep.DeployError("PILOT_FAILED_ROLLED_BACK") from None


def rollback():
    dep.require(os.geteuid() == 0, "ROOT_REQUIRED")
    snapshot = dep.Snapshot(BACKUP, targets=(dep.COGNITION, DROPIN))
    snapshot.load()
    dep.require(snapshot.data["revision"] == REVISION
                and snapshot.data["phase"] == "installed",
                "NO_INSTALLED_PILOT")
    snapshot.check("desired")
    timer = snapshot.data["states"]["cognitive_timer"]
    dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == timer, "TIMER_STATE_DRIFT")
    dep.quiesce_cognition(timer, "COGNITION_RUNNING")
    try:
        snapshot.restore_files()
        dep.systemctl("daemon-reload")
        dep.restore_timer(dep.COGNITIVE_TIMER, timer)
        dep.require(dep.timer_state(dep.COGNITIVE_TIMER) == timer, "TIMER_RESTORE_MISMATCH")
        snapshot.data["phase"] = "rolled_back"
        snapshot.save()
        return {"state": "rolled_back", "ledger_untouched": True}
    except BaseException:
        dep.restore_timer(dep.COGNITIVE_TIMER, timer)
        raise


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in ("--preflight", "--apply", "--rollback") or os.geteuid() != 0:
        print('{"state":"blocked","reason":"ADMIN_CONSOLE_REQUIRED"}')
        return 2
    try:
        os.umask(0o077)
        if argv[0] == "--preflight":
            raw = pinned_runtime()
            timer = preflight(raw)
            print(dep.canonical({"state": "ready_for_admin_pilot",
                                 "installed_sha256": BEFORE,
                                 "new_sha256": dep.digest(raw), "timer": timer}).decode().strip())
            return 0
        lock = dep.guarded(Path("/run/lock/nasuraya-agent-deploy.lock"))
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            dep.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                        "UNTRUSTED_LOCK")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if argv[0] == "--rollback":
                result = rollback()
            else:
                result = apply(pinned_runtime())
        finally:
            os.close(fd)
        print(dep.canonical(result).decode().strip())
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, dep.DeployError) else type(exc).__name__
        print(json.dumps({"state": "blocked", "reason": reason}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
