#!/usr/bin/env python3
"""Administrator-only, pinned deployment of the bounded Nasuraya server agent.

No downloads, checkout, package installation, token access or submitted shell.
Existing Bridge code is surgically extended, never replaced by repository code.
Only fixed root-owned executable/configuration files are changed. User ledgers
are never restored/deleted by rollback. Call from an administrator console.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

SCHEMA = "nasuraya-agent-deployment/1"
PROJECT = Path("/opt/zohraya")
PREFIX = Path("/usr/local/lib/nasuraya")
BACKUPS = Path("/var/backups/nasuraya-agent")
STATE = Path("/var/lib/nasuraya/agent-integration")
BRIDGE = PREFIX / "bridge.py"
COGNITION = PREFIX / "nasu_autonomous_cognition.py"
DEPLOYED = PREFIX / "agent-deployment.json"
SYSTEM = Path("/etc/systemd/system")
COGNITIVE_SERVICE = "nasuraya-cognitive-growth.service"
COGNITIVE_TIMER = "nasuraya-cognitive-growth.timer"
BRIDGE_SERVICE = "nasuraya-bridge.service"
SERVICE = "nasuraya-agent-integration.service"
TIMER = "nasuraya-agent-integration.timer"
DROPIN = SYSTEM / (COGNITIVE_SERVICE + ".d") / "20-pinned-source.conf"
TARGETS = (BRIDGE, COGNITION, DROPIN, SYSTEM / SERVICE, SYSTEM / TIMER, DEPLOYED)
KNOWN_COGNITION = (
    "a4db984ce1bb3bb5c997f1c531ec9578b37c44ae",
    "0753a58292afd888c1e2fe6b1b8f41d3da3deff9",
    "15ea53b1707a71415038683c9a2d292be838a728",
)
FILES = (
    "tools/install_nasu_server_agent.py",
    "tools/nasu_autonomous_cognition.py",
    "tools/nasu_unified_status.py",
    "tools/nasu_evidence_to_experiment.py",
    "tools/nasu_live_integration.py",
    "tools/nasu_agent_diagnostics.py",
    "tools/nasuraya_offline_continuity.py",
    "tools/nasu_frontier_lab.py",
    "tools/nasu_feedback_learning.py",
    "tools/nasu_awake_offline_runner.py",
    "tools/install_nasu_awake_offline.sh",
    "examples/nasuraya_body_loop/self_knowledge.py",
    "examples/nasuraya_research/evaluate_confidence.py",
    "tests/test_install_nasu_server_agent.py",
    "tests/test_nasu_autonomous_cognition.py",
    "tests/test_nasu_unified_status.py",
    "tests/test_nasu_evidence_to_experiment.py",
    "tests/test_nasu_live_integration.py",
    "tests/test_nasu_agent_diagnostics.py",
    "tests/test_nasuraya_offline_continuity.py",
    "tests/test_nasu_frontier_lab.py",
    "tests/test_nasu_feedback_learning.py",
    "tests/test_nasu_awake_offline_runner.py",
)
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
       "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
       "SYSTEMD_PAGER": "cat", "SYSTEMD_COLORS": "0"}
BEGIN = "# NASURAYA_AGENT_BRIDGE_BEGIN "
END = "# NASURAYA_AGENT_BRIDGE_END"


class DeployError(RuntimeError):
    """Only fixed, non-sensitive error identifiers may be passed here."""


def require(condition, reason):
    if not condition:
        raise DeployError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def revision(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "INVALID_REVISION")
    return value


def guarded(path, *, owner=0, required=False, directory=False):
    """Reject symlinks in every ancestor; never follow a target symlink."""
    path = Path(os.path.abspath(os.fspath(path)))
    for part in (path, *path.parents):
        require(not part.is_symlink(), "SYMLINKED_SYSTEM_PATH")
    require(not required or path.exists(), "REQUIRED_PATH_MISSING")
    if path.exists():
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "UNEXPECTED_PATH_TYPE")
        if owner is not None:
            require(info.st_uid == owner and not info.st_mode & 0o022, "UNTRUSTED_FILE_OWNER_OR_MODE")
    return path


def root_directory(path, *, owner=0, group=0, mode=0o755):
    path = guarded(path, owner=owner, directory=True)
    if not path.exists():
        root_directory(path.parent, owner=owner, group=group)
        path.mkdir(mode=mode)
        os.chown(path, owner, group, follow_symlinks=False)
        os.chmod(path, mode, follow_symlinks=False)
    return path


def read_file(path, *, owner=0):
    path = guarded(path, owner=owner, required=True)
    require(path.stat().st_size <= 4 * 1024 * 1024, "OVERSIZED_SYSTEM_FILE")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and (owner is None or info.st_uid == owner), "UNTRUSTED_FILE_OWNER_OR_MODE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(4 * 1024 * 1024 + 1)
    finally:
        os.close(fd)


def atomic_write(path, data, *, mode=0o644, owner=0, group=0):
    path = guarded(path, owner=owner)
    root_directory(path.parent, owner=owner, group=group)
    fd, temporary = tempfile.mkstemp(prefix=".nasuraya-agent-", dir=path.parent)
    try:
        os.fchown(fd, owner, group)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        guarded(path, owner=owner)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(args, *, cwd=None, timeout=30, check=True):
    result = subprocess.run(args, cwd=cwd, env=dict(ENV), timeout=timeout,
                            check=False, capture_output=True)
    if check:
        require(result.returncode == 0, "FIXED_COMMAND_FAILED")
    require(len(result.stdout) <= 4 * 1024 * 1024, "OVERSIZED_COMMAND_OUTPUT")
    return result


def git_blob(commit, name):
    revision(commit)
    require(name in FILES or name == "tools/nasu_autonomous_cognition.py", "UNEXPECTED_RELEASE_PATH")
    item = execute(["/usr/bin/git", "-C", str(PROJECT), "ls-tree", commit, "--", name]).stdout.decode()
    require(re.fullmatch(r"100(?:644|755) blob [0-9a-f]{40}\t" + re.escape(name) + r"\n", item), "MISSING_OR_NONREGULAR_GIT_BLOB")
    data = execute(["/usr/bin/git", "-C", str(PROJECT), "show", commit + ":" + name]).stdout
    require(data and len(data) <= 1024 * 1024, "INVALID_RELEASE_BLOB")
    if name.endswith(".py"):
        ast.parse(data, filename=name)
    return data


def _span(text, node):
    # Python AST columns are UTF-8 byte offsets, including in Persian comments.
    lines = text.encode("utf-8").splitlines(keepends=True)
    start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
    end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
    return start, end


def patch_bridge(raw, release, commit):
    """Change only the regex literal, two new handlers and fallback help text."""
    revision(commit)
    require(str(release) == str(PREFIX / "releases" / commit), "UNEXPECTED_RELEASE_LOCATION")
    text = raw.decode("utf-8")
    require(BEGIN not in text and END not in text and "agent-status" not in text and "agent-probe" not in text,
            "BRIDGE_ALREADY_PATCHED_OR_DRIFTED")
    tree = ast.parse(text)
    assignments = [x for x in tree.body if isinstance(x, ast.Assign) and
                   any(isinstance(t, ast.Name) and t.id == "COMMAND_RE" for t in x.targets)]
    require(len(assignments) == 1 and len(assignments[0].targets) == 1, "UNKNOWN_BRIDGE_REGEX")
    call = assignments[0].value
    require(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and
            isinstance(call.func.value, ast.Name) and call.func.value.id == "re" and call.func.attr == "compile" and
            not call.keywords and len(call.args) == 2 and isinstance(call.args[0], ast.Constant) and
            isinstance(call.args[0].value, str) and isinstance(call.args[1], ast.Attribute) and
            isinstance(call.args[1].value, ast.Name) and call.args[1].value.id == "re" and call.args[1].attr == "I",
            "UNKNOWN_BRIDGE_REGEX")
    expression = call.args[0].value
    prefix, suffix = r"(?m)^\s*nasu-linux:\s*(", r")\s*$"
    require(expression.startswith(prefix) and expression.endswith(suffix), "UNKNOWN_BRIDGE_REGEX")
    verbs = expression[len(prefix):-len(suffix)].split("|")
    require(len(verbs) == len(set(verbs)) and all(re.fullmatch(r"[a-z][a-z0-9-]*", v) for v in verbs) and
            {"status", "help"} <= set(verbs), "UNKNOWN_BRIDGE_VERBS")
    functions = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "dispatch"]
    require(len(functions) == 1, "UNKNOWN_BRIDGE_DISPATCH")
    function = functions[0]
    require(not function.decorator_list and len(function.args.args) == 1 and function.args.args[0].arg == "action" and
            not function.args.posonlyargs and not function.args.kwonlyargs and not function.args.defaults and
            not function.args.vararg and not function.args.kwarg, "UNKNOWN_BRIDGE_DISPATCH")
    body = function.body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    require(len(body) >= 2 and isinstance(body[-1], ast.Return) and isinstance(body[-1].value, ast.Constant) and
            isinstance(body[-1].value.value, str) and body[-1].value.value.startswith("Allowed:"), "UNKNOWN_BRIDGE_HELP")
    handled = []
    for branch in body[:-1]:
        require(isinstance(branch, ast.If) and not branch.orelse and isinstance(branch.test, ast.Compare), "UNKNOWN_BRIDGE_DISPATCH")
        test = branch.test
        require(isinstance(test.left, ast.Name) and test.left.id == "action" and len(test.ops) == 1 and
                isinstance(test.ops[0], ast.Eq) and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant) and
                isinstance(test.comparators[0].value, str), "UNKNOWN_BRIDGE_DISPATCH")
        handled.append(test.comparators[0].value)
    require(len(handled) == len(set(handled)) and set(handled) == set(verbs) - {"help"}, "UNKNOWN_BRIDGE_DISPATCH")
    command = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "command"]
    require(len(command) == 1 and {"argv", "timeout", "cwd"} <= {x.arg for x in command[0].args.args}, "UNKNOWN_BRIDGE_COMMAND_HELPER")
    updated_regex = prefix + "|".join(verbs + ["agent-status", "agent-probe"]) + suffix
    block = (
        "    " + BEGIN + commit + "\n"
        "    if action == 'agent-status':\n"
        "        return command(['/usr/bin/python3', '-B', '-m', 'tools.nasu_agent_diagnostics', 'status'], timeout=60, cwd=" + repr(str(release)) + ")\n"
        "    if action == 'agent-probe':\n"
        "        return command(['/usr/bin/python3', '-B', '-m', 'tools.nasu_agent_diagnostics', 'probe'], timeout=150, cwd=" + repr(str(release)) + ")\n"
        "    " + END + "\n"
    ).encode()
    fallback = body[-1]
    insert, _ = _span(text, fallback)
    insert -= fallback.col_offset
    edits = [(*_span(text, call.args[0]), repr(updated_regex).encode()),
             (*_span(text, fallback.value), repr(fallback.value.value + " Agent diagnostics: agent-status, agent-probe.").encode()),
             (insert, insert, block)]
    result = raw
    for start, end, data in sorted(edits, reverse=True):
        result = result[:start] + data + result[end:]
    ast.parse(result)
    # Every original handler is byte-for-byte preserved, including local v2 additions.
    for branch in body[:-1]:
        start, end = _span(text, branch)
        require(raw[start:end] in result, "BRIDGE_HANDLER_CHANGED")
    return result


def units(release):
    require(release.parent == PREFIX / "releases", "UNEXPECTED_RELEASE_LOCATION")
    revision(release.name)
    service = f"""# Managed by {SCHEMA}; revision={release.name}
[Unit]
Description=Nasuraya persistent local observations and proposed next experiment
After=local-fs.target
[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory={release}
ExecStart=/usr/bin/python3 -B -m tools.nasu_live_integration run
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ReadWritePaths={STATE}
MemoryMax=256M
CPUQuota=50%
TimeoutStartSec=90
"""
    timer = f"""# Managed by {SCHEMA}; revision={release.name}
[Unit]
Description=Nasuraya local integration journal hourly
[Timer]
OnCalendar=hourly
Persistent=true
Unit={SERVICE}
[Install]
WantedBy=timers.target
"""
    dropin = f"# Managed by {SCHEMA}\n[Service]\nEnvironment=NASU_COGNITION_SOURCE_ROOT={release}\n"
    return {SYSTEM / SERVICE: service.encode(), SYSTEM / TIMER: timer.encode(), DROPIN: dropin.encode()}


def unit_state(unit):
    require(unit in (COGNITIVE_SERVICE, COGNITIVE_TIMER, BRIDGE_SERVICE, SERVICE, TIMER), "UNEXPECTED_UNIT")
    properties = ("LoadState", "ActiveState", "UnitFileState", "FragmentPath", "User", "ExecStart", "Result", "ExecMainStatus", "Environment")
    args = ["/usr/bin/systemctl", "show", unit, "--no-pager"] + ["--property=" + p for p in properties]
    result = execute(args, check=False)
    text = result.stdout.decode()
    require(len(text) < 32768, "OVERSIZED_UNIT_STATE")
    row = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    require(result.returncode == 0 or row.get("LoadState") == "not-found", "UNIT_STATE_UNAVAILABLE")
    return row


def systemctl(action, *names, check=True):
    require(action in ("stop", "start", "restart", "enable", "disable", "daemon-reload"), "UNEXPECTED_SYSTEMD_ACTION")
    require(set(names) <= {COGNITIVE_TIMER, BRIDGE_SERVICE, SERVICE, TIMER}, "UNEXPECTED_UNIT")
    return execute(["/usr/bin/systemctl", action, *names], timeout=105, check=check)


def timer_state(unit):
    row = unit_state(unit)
    require(row.get("LoadState") == "loaded" and row.get("ActiveState") in ("active", "inactive") and
            row.get("UnitFileState") in ("enabled", "disabled"), "UNEXPECTED_TIMER_STATE")
    return {"active": row["ActiveState"] == "active", "enabled": row["UnitFileState"] == "enabled"}


def restore_timer(unit, original):
    failed = False
    for action in ("enable" if original["enabled"] else "disable", "start" if original["active"] else "stop"):
        try:
            systemctl(action, unit)
        except BaseException:
            failed = True
    require(not failed, "TIMER_STATE_RESTORE_FAILED")


def quiesce_cognition(original, reason):
    """Pause the timer, never kill its job, and restore it on EVERY refusal."""
    try:
        systemctl("stop", COGNITIVE_TIMER)
        require(unit_state(COGNITIVE_SERVICE).get("ActiveState") in ("inactive", "failed"), reason)
    except BaseException:
        restore_timer(COGNITIVE_TIMER, original)
        raise


class Snapshot:
    """Write-ahead backup of a fixed file set; never backs up private ledgers."""

    def __init__(self, directory, targets=TARGETS, *, owner=0, group=0):
        self.directory = Path(directory)
        self.targets = tuple(Path(x) for x in targets)
        self.owner, self.group = owner, group
        self.manifest = self.directory / "manifest.json"
        self.data = None

    def load(self):
        data = json.loads(read_file(self.manifest, owner=self.owner))
        require(data.get("schema") == SCHEMA and set(data.get("files", {})) == {str(x) for x in self.targets}, "INVALID_BACKUP_MANIFEST")
        revision(data.get("revision"))
        states = data.get("states", {})
        timer = states.get("cognitive_timer", {})
        require(set(states) == {"cognitive_timer", "bridge_active"} and states["bridge_active"] is True and
                set(timer) == {"active", "enabled"} and all(type(v) is bool for v in timer.values()), "INVALID_BACKUP_STATES")
        for index, path in enumerate(self.targets):
            record = data["files"][str(path)]
            require(record.get("backup") == str(index) + ".bin" and type(record.get("existed")) is bool and
                    re.fullmatch(r"[0-9a-f]{64}", record.get("desired_sha", "")), "INVALID_BACKUP_MANIFEST")
            if record["existed"]:
                raw = read_file(self.directory / record["backup"], owner=self.owner)
                require(digest(raw) == record.get("sha256"), "BACKUP_DIGEST_MISMATCH")
                require(type(record.get("mode")) is int and 0 <= record["mode"] <= 0o777 and
                        not record["mode"] & 0o022 and record.get("uid") == self.owner and
                        type(record.get("gid")) is int and record["gid"] >= 0, "INVALID_BACKUP_METADATA")
        self.data = data
        return data

    def create(self, commit, desired, states):
        require(not self.directory.exists(), "BACKUP_ALREADY_EXISTS")
        root_directory(self.directory.parent, owner=self.owner, group=self.group, mode=0o700)
        self.directory.mkdir(mode=0o700)
        os.chown(self.directory, self.owner, self.group)
        files = {}
        for index, path in enumerate(self.targets):
            guarded(path, owner=self.owner)
            record = {"backup": str(index) + ".bin", "existed": path.exists(), "desired_sha": digest(desired[path])}
            if path.exists():
                raw, info = read_file(path, owner=self.owner), path.stat()
                record.update(sha256=digest(raw), mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)
                atomic_write(self.directory / record["backup"], raw, mode=0o600, owner=self.owner, group=self.group)
            files[str(path)] = record
        self.data = {"schema": SCHEMA, "revision": revision(commit), "phase": "prepared", "files": files, "states": states}
        self.save()

    def save(self):
        atomic_write(self.manifest, canonical(self.data), mode=0o600, owner=self.owner, group=self.group)

    def check(self, which):
        require(which in ("original", "desired", "either"), "INVALID_BACKUP_CHECK")
        for path in self.targets:
            record = self.data["files"][str(path)]
            guarded(path, owner=self.owner)
            current = digest(read_file(path, owner=self.owner)) if path.exists() else None
            before = record.get("sha256") if record["existed"] else None
            permitted = ({before} if which == "original" else {record["desired_sha"]} if which == "desired" else {before, record["desired_sha"]})
            require(current in permitted, "TARGET_CHANGED_AFTER_SNAPSHOT")

    def apply(self, desired):
        self.check("original")
        self.data["phase"] = "installing"
        self.save()
        for path in self.targets:
            require(digest(desired[path]) == self.data["files"][str(path)]["desired_sha"], "DESIRED_DIGEST_MISMATCH")
            previous = self.data["files"][str(path)]
            atomic_write(path, desired[path], mode=previous.get("mode", 0o644), owner=self.owner, group=previous.get("gid", self.group))
        self.check("desired")

    def restore_files(self):
        self.check("either")
        for path in reversed(self.targets):
            record = self.data["files"][str(path)]
            if record["existed"]:
                raw = read_file(self.directory / record["backup"], owner=self.owner)
                require(digest(raw) == record["sha256"], "BACKUP_DIGEST_MISMATCH")
                atomic_write(path, raw, mode=record["mode"], owner=self.owner, group=record["gid"])
            elif path.exists():
                guarded(path, owner=self.owner, required=True)
                path.unlink()
        self.check("original")


def release_files(commit):
    guarded(PROJECT, owner=None, required=True, directory=True)
    actual = execute(["/usr/bin/git", "-C", str(PROJECT), "rev-parse", "--verify", commit + "^{commit}"]).stdout.decode().strip()
    require(actual == commit, "REVISION_NOT_AVAILABLE")
    data = {name: git_blob(commit, name) for name in FILES}
    require(data["tools/install_nasu_server_agent.py"] == Path(__file__).read_bytes(), "INSTALLER_REVISION_MISMATCH")
    require(b"NASU_COGNITION_SOURCE_ROOT" in data["tools/nasu_autonomous_cognition.py"], "PINNED_SOURCE_SUPPORT_MISSING")
    return data


def materialize(commit, data):
    release = PREFIX / "releases" / commit
    manifest = canonical({"schema": SCHEMA, "revision": commit, "files": {k: digest(v) for k, v in data.items()}})
    guarded(release, directory=True)
    if release.exists():
        require(read_file(release / "release.json") == manifest, "EXISTING_RELEASE_DIFFERS")
        for name, raw in data.items():
            require(read_file(release / name) == raw, "EXISTING_RELEASE_DIFFERS")
        entries = tuple(release.rglob("*"))
        require(not any(p.is_symlink() for p in entries), "SYMLINKED_RELEASE")
        actual = {str(p.relative_to(release)) for p in entries if not p.is_dir()}
        require(actual == set(data) | {"release.json"}, "UNEXPECTED_RELEASE_FILE")
        expected_dirs = {str(parent) for name in data for parent in Path(name).parents if str(parent) != "."}
        require({str(p.relative_to(release)) for p in entries if p.is_dir()} == expected_dirs, "UNEXPECTED_RELEASE_DIRECTORY")
        for folder in (release, *(p for p in entries if p.is_dir())):
            guarded(folder, required=True, directory=True)
        return release
    root_directory(release.parent)
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=release.parent))
    try:
        os.chmod(stage, 0o755)
        for name, raw in data.items():
            atomic_write(stage / name, raw, mode=0o444)
        atomic_write(stage / "release.json", manifest, mode=0o444)
        for folder in sorted((p for p in stage.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            os.chmod(folder, 0o555)
        os.chmod(stage, 0o555)
        guarded(release, directory=True)
        require(not release.exists(), "RELEASE_APPEARED_DURING_STAGING")
        os.rename(stage, release)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return release


def unprivileged(release, args, *, timeout=105, check=True):
    return execute(["/usr/sbin/runuser", "-u", "nasuraya", "--", "/usr/bin/python3", "-B", *args], cwd=release, timeout=timeout, check=check)


def verify_diagnostics(result):
    """Return only validated public metadata; failed probes have JSON + exit 1."""
    require(result.returncode in (0, 1) and len(result.stdout) <= 8192, "LIVE_DIAGNOSTICS_UNAVAILABLE")
    try:
        receipt = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise DeployError("INVALID_DIAGNOSTIC_RECEIPT") from None
    require(isinstance(receipt, dict) and receipt.get("schema") == "nasuraya-agent-diagnostics/1", "INVALID_DIAGNOSTIC_RECEIPT")
    require(receipt.get("probe", {}).get("state") == "success", "LOCAL_MODEL_PROBE_FAILED")
    require(result.returncode == 0, "LIVE_DIAGNOSTICS_UNAVAILABLE")
    require(receipt.get("executables", {}).get("match") is True, "INSTALLED_COGNITION_HASH_MISMATCH")
    integration = receipt.get("integration", {})
    require(integration.get("state") == "ok" and type(integration.get("records")) is int and integration["records"] >= 1,
            "LIVE_INTEGRATION_JOURNAL_NOT_VERIFIED")
    history = receipt.get("cognition", {})
    require(history.get("state") in ("verified_history", "incomplete") and type(history.get("completed")) is int and
            history["completed"] >= 1 and type(history.get("incomplete")) is int and history["incomplete"] >= 0,
            "EXISTING_COGNITIVE_HISTORY_NOT_VERIFIED")
    return {"state": history["state"], "incomplete": history["incomplete"]}


def preflight():
    account = pwd.getpwnam("nasuraya")
    require(account.pw_uid != 0, "INVALID_SERVICE_ACCOUNT")
    guarded(PREFIX, required=True, directory=True)
    guarded(SYSTEM, required=True, directory=True)
    for path in TARGETS:
        guarded(path)
    for path in (BRIDGE, COGNITION, SYSTEM / COGNITIVE_SERVICE, SYSTEM / COGNITIVE_TIMER, SYSTEM / BRIDGE_SERVICE):
        guarded(path, required=True)
    for path in (DROPIN, SYSTEM / SERVICE, SYSTEM / TIMER, DEPLOYED):
        require(not path.exists(), "UNKNOWN_EXISTING_AGENT_ARTIFACT")
    for name in (SERVICE, TIMER):
        require(unit_state(name).get("LoadState") == "not-found", "UNKNOWN_EXISTING_AGENT_UNIT")
    for name, executable in ((COGNITIVE_SERVICE, COGNITION), (BRIDGE_SERVICE, BRIDGE)):
        row = unit_state(name)
        starts = re.findall(r"argv\[\]=([^;]*);", row.get("ExecStart", ""))
        argv = shlex.split(starts[0]) if len(starts) == 1 else []
        if len(argv) >= 2 and argv[1] in ("-B", "-u"):
            argv.pop(1)
        expected = ["/usr/bin/python3", str(executable)] + (["run"] if name == COGNITIVE_SERVICE else [])
        require(row.get("LoadState") == "loaded" and row.get("User") == "nasuraya" and
                row.get("FragmentPath") == str(SYSTEM / name) and argv == expected, "UNKNOWN_EXISTING_SERVICE")
    bridge = unit_state(BRIDGE_SERVICE)
    require(bridge.get("ActiveState") == "active", "BRIDGE_NOT_ACTIVE")
    states = {"cognitive_timer": timer_state(COGNITIVE_TIMER), "bridge_active": True}
    return account, states


def rollback(snapshot):
    snapshot.load()
    require(snapshot.data["phase"] in ("prepared", "installing", "installed", "rolled_back", "rollback_failed"), "UNKNOWN_BACKUP_PHASE")
    snapshot.check("either")
    # Never interrupt a live cognitive run or leave its timer paused on refusal.
    quiesce_cognition(snapshot.data["states"]["cognitive_timer"], "COGNITION_RUNNING_RETRY_ROLLBACK")
    # Stop only the NEW observer; never stop Awake or Ollama.
    systemctl("stop", TIMER, SERVICE, check=False)
    systemctl("disable", TIMER, check=False)
    snapshot.restore_files()
    systemctl("daemon-reload")
    if snapshot.data["states"]["bridge_active"]:
        systemctl("restart", BRIDGE_SERVICE)
    restore_timer(COGNITIVE_TIMER, snapshot.data["states"]["cognitive_timer"])
    snapshot.data["phase"] = "rolled_back"
    snapshot.save()
    return {"DEPLOYMENT": "ROLLED_BACK", "revision": snapshot.data["revision"], "user_state": "RETAINED"}


def deploy(commit):
    data = release_files(commit)
    snapshot = Snapshot(BACKUPS / commit)
    if snapshot.manifest.exists():
        snapshot.load()
        if snapshot.data["phase"] == "installed":
            snapshot.check("desired")
            materialize(commit, data)
            return {"DEPLOYMENT": "ALREADY_INSTALLED", "revision": commit}
        require(snapshot.data["phase"] in ("prepared", "rolled_back"), "PRIOR_ATTEMPT_REQUIRES_ROLLBACK")
        snapshot.check("original")
    account, states = preflight()
    original = read_file(COGNITION)
    known = {digest(data["tools/nasu_autonomous_cognition.py"])}
    for old in KNOWN_COGNITION:
        try:
            known.add(digest(git_blob(old, "tools/nasu_autonomous_cognition.py")))
        except DeployError:
            pass
    require(digest(original) in known, "UNKNOWN_INSTALLED_COGNITION")
    release = materialize(commit, data)
    # These committed tests are synthetic; run as the service user before writes.
    unprivileged(release, ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"], timeout=180)
    desired = units(release)
    desired[BRIDGE] = patch_bridge(read_file(BRIDGE), release, commit)
    desired[COGNITION] = data["tools/nasu_autonomous_cognition.py"]
    desired[DEPLOYED] = canonical({"schema": SCHEMA, "revision": commit, "release": str(release),
                                  "bridge_sha256": digest(desired[BRIDGE]), "cognition_sha256": digest(desired[COGNITION])})
    if snapshot.data is None:
        snapshot.create(commit, desired, states)
    else:
        require(snapshot.data["states"] == states and all(snapshot.data["files"][str(p)]["desired_sha"] == digest(v) for p, v in desired.items()), "RETRY_STATE_DIFFERS")
    quiesce_cognition(states["cognitive_timer"], "COGNITION_RUNNING_RETRY_LATER")
    try:
        guarded(STATE, owner=None, directory=True)
        if STATE.exists():
            require(STATE.stat().st_uid == account.pw_uid and not STATE.stat().st_mode & 0o077, "UNEXPECTED_INTEGRATION_STATE_PERMISSIONS")
        else:
            guarded(STATE.parent, owner=None, required=True, directory=True)
            STATE.mkdir(mode=0o700)
            os.chown(STATE, account.pw_uid, account.pw_gid, follow_symlinks=False)
        snapshot.apply(desired)
        systemctl("daemon-reload")
        environment = shlex.split(unit_state(COGNITIVE_SERVICE).get("Environment", ""))
        require([item for item in environment if item.startswith("NASU_COGNITION_SOURCE_ROOT=")] ==
                ["NASU_COGNITION_SOURCE_ROOT=" + str(release)], "COGNITIVE_SOURCE_OVERRIDE_FAILED")
        systemctl("start", SERVICE)
        row = unit_state(SERVICE)
        require(row.get("Result") == "success" and row.get("ExecMainStatus") == "0", "FIRST_INTEGRATION_RUN_FAILED")
        # Read the fresh journal and test ONE fixed, bounded local inference.
        history = verify_diagnostics(unprivileged(release, ["-m", "tools.nasu_agent_diagnostics", "probe"], timeout=155, check=False))
        systemctl("enable", TIMER)
        systemctl("start", TIMER)
        systemctl("restart", BRIDGE_SERVICE)
        require(unit_state(BRIDGE_SERVICE).get("ActiveState") == "active" and timer_state(TIMER) == {"active": True, "enabled": True}, "SERVICE_ACTIVATION_FAILED")
        restore_timer(COGNITIVE_TIMER, {"active": True, "enabled": True})
        require(timer_state(COGNITIVE_TIMER) == {"active": True, "enabled": True}, "COGNITIVE_TIMER_ACTIVATION_FAILED")
        snapshot.data["phase"] = "installed"
        snapshot.save()
        return {"DEPLOYMENT": "SUCCESS", "revision": commit, "model_probe": "SUCCESS", "integration": "RECORDED",
                "cognition_source": "PINNED", "cognitive_history": history["state"], "cognition_incomplete": history["incomplete"],
                "cognitive_timer": {"active": True, "enabled": True}, "bridge": "EXTENDED"}
    except BaseException as failure:
        try:
            rollback(snapshot)
        except BaseException:
            snapshot.data["phase"] = "rollback_failed"
            snapshot.save()
            raise DeployError("ROLLBACK_INCOMPLETE_USE_PINNED_ROLLBACK") from None
        reason = str(failure) if isinstance(failure, DeployError) else type(failure).__name__
        raise DeployError("DEPLOYMENT_FAILED_ROLLED_BACK:" + reason) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--revision")
    group.add_argument("--rollback")
    args = parser.parse_args(argv)
    try:
        require(os.geteuid() == 0, "ADMINISTRATOR_REQUIRED")
        os.umask(0o077)
        lock = guarded(Path("/run/lock/nasuraya-agent-deploy.lock"))
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        # The process owns this descriptor until exit; no concurrent deploy/rollback.
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        commit = revision(args.revision or args.rollback)
        output = rollback(Snapshot(BACKUPS / commit)) if args.rollback else deploy(commit)
        print(canonical(output).decode().strip())
        return 0
    except (DeployError, OSError, ValueError, KeyError, SyntaxError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, DeployError) else type(exc).__name__
        print(canonical({"DEPLOYMENT": "BLOCKED", "reason": reason}).decode().strip())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
