"""Opt-in fail-closed installer for hourly, fully offline Tadash Awake on Windows.

Only six immutable GitHub blobs from a vetted research commit are downloaded and
verified. Does not touch Bridge, register SYSTEM tasks, access credentials, or
enable unapproved API calls. Task account = current operator, S4U least privilege.
No automatic sensory ingestion: absent evidence produces an honest idle tick.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler

SOURCE = "af98b4c88fceeaf1addaf809e669d6726580a212"
REPO = "zurvanproject/zohraya"
TASK = "NasurayaAwakeHourly"
FOLDER = "NasurayaAwake"
HASHES = {
    "tadash_awake/__init__.py": "cda0c399c941cece1ae031c1b6642a1e3516dd41",
    "tadash_awake/core.py": "70552587b9849fd014b41c057b2ccd625c1df2b7",
    "tadash_awake/bridge.py": "2ae82cbd7fa28de56a97e4b296f9a355dc75b48a",
    "tadash_awake/__main__.py": "3e603870ab8160d20aeecc080c904f4776f1fe40",
    "tadash_awake/test_wake.py": "a59ffa3b9947ecce78336122462ce2e6bd18ff45",
    "tadash_awake/test_bridge.py": "b7c7956891d4e9d5ab067ee27512ccb785f1c0e5",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def downloader():
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))


def fetch_code(directory):
    opener = downloader()
    for rel, expected in HASHES.items():
        url = "https://raw.githubusercontent.com/" + REPO + "/" + SOURCE + "/" + rel
        req = Request(url, headers={"User-Agent": "NasurayaAwakeOptInInstaller/1"})
        with opener.open(req, timeout=12) as response:
            raw = response.read(24001)
        if not 1 <= len(raw) <= 24000 or blob_sha(raw) != expected:
            raise ValueError("package fingerprint or size mismatch")
        target = Path(directory) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)


def test_package(directory):
    bootstrap = (
        "import sys,unittest,io;sys.path.insert(0,sys.argv[1]);"
        "names=['tadash_awake.test_wake','tadash_awake.test_bridge'];"
        "suite=unittest.defaultTestLoader.loadTestsFromNames(names);"
        "buffer=io.StringIO();"
        "result=unittest.TextTestRunner(stream=buffer).run(suite);"
        "sys.exit(0 if result.wasSuccessful() and result.testsRun>=18 else 3)"
    )
    proc = subprocess.run([sys.executable, "-I", "-S", "-c", bootstrap, str(directory)],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=40, check=False)
    if proc.returncode:
        raise ValueError("offline package regression tests failed")


# Pinned and local-only scheduled runner. A task never executes unverified code.
RUNNER = r'''"""Hourly local-only Tadash Awake heartbeat: no model, network or external action."""
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
PINS = __PINS__

def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()

def main():
    for rel, sha in PINS.items():
        path = ROOT / rel
        if not path.is_file() or blob_sha(path.read_bytes()) != sha:
            return 3
    sys.path.insert(0, str(ROOT))
    from tadash_awake import core
    result = core.tick(ROOT / "state")
    status = {"schema": "nasuraya-awake-task/1",
              "at": core.iso(core.clock()), "status": result["status"],
              "source": "__SOURCE__", "mode": "offline_evidence_only",
              "model_calls": 0, "external_actions": 0}
    temp = ROOT / "last_run.tmp"
    final = ROOT / "last_run.json"
    temp.write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    temp.replace(final)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        sys.exit(2)
'''


def runner_source():
    return RUNNER.replace("__PINS__", repr(HASHES)).replace("__SOURCE__", SOURCE)


def task_powershell(python, runner, root):
    # The Windows account already running Bridge is used, but with LIMITED
    # privileges and S4U (no stored password and no network identity).
    ps = r"""
$ErrorActionPreference='Stop'
$name='NasurayaAwakeHourly'
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {throw 'task exists'}
$exe='__PYTHON__'
$script='__RUNNER__'
$folder='__ROOT__'
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
$action=New-ScheduledTaskAction -Execute $exe -Argument ('-I -u "' + $script + '"') -WorkingDirectory $folder
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Description 'Bounded offline research heartbeat; no network or model API' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -ErrorAction Stop | Out-Null
Start-ScheduledTask -TaskName $name -ErrorAction Stop
'CREATED'
"""
    for key, value in {"__PYTHON__": python, "__RUNNER__": runner, "__ROOT__": root}.items():
        if "'" in value or "\r" in value or "\n" in value:
            raise ValueError("unsafe Windows path")
        ps = ps.replace(key, value)
    return ps


def installed_task_state():
    exe = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = "$t=Get-ScheduledTask -TaskName 'NasurayaAwakeHourly' -ErrorAction SilentlyContinue; if ($null -eq $t) {'ABSENT'} else {$t.State.ToString()}"
    p = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-Command", script],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=15, check=False)
    state = p.stdout.strip()
    return state if p.returncode == 0 and state in ("ABSENT", "Ready", "Running", "Disabled", "Queued") else "UNKNOWN"


def report(message):
    if len(message) > 170:
        message = "AWAKE=BLOCKED;CAUSE=OUTPUT_LENGTH"
    print(json.dumps({"status": "ok", "summary": message}, separators=(",", ":")))


def main():
    if "--self-test" in sys.argv:
        with tempfile.TemporaryDirectory() as temp:
            fetch_code(temp)
            test_package(temp)
            (Path(temp) / "awake_task.py").write_text(runner_source(), encoding="utf-8")
            if len(runner_source()) > 12000:
                raise ValueError("task runner too large")
        return "AWAKE=SELFTEST_OK;FILES=6;TESTS=18;EXTERNAL=0"
    if os.name != "nt":
        return "AWAKE=BLOCKED;CAUSE=WINDOWS_ONLY"
    if sys.version_info < (3, 11):
        return "AWAKE=BLOCKED;CAUSE=PYTHON_OLD"
    program = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData"))
    root = program / FOLDER
    if root.exists() or (program / (FOLDER + "_staging_v02")).exists():
        return "AWAKE=BLOCKED;CAUSE=INSTALL_PATH_EXISTS"
    if installed_task_state() != "ABSENT":
        return "AWAKE=BLOCKED;CAUSE=TASK_NOT_ABSENT"
    if shutil.disk_usage(program).free < 100 * 1024 * 1024:
        return "AWAKE=BLOCKED;CAUSE=LOW_DISK"
    stage = program / (FOLDER + "_staging_v02")
    stage.mkdir(exist_ok=False)
    try:
        fetch_code(stage)
        test_package(stage)
        (stage / "awake_task.py").write_text(runner_source(), encoding="utf-8")
        # State and package are separate. Never import, alter or reset a
        # previous Awake database, Bridge journal, model, or user account.
        stage.replace(root)
    except BaseException:
        # Keep failed stage for operator inspection, rather than silently
        # deleting possible diagnostic artifacts.
        raise
    sys.path.insert(0, str(root))
    from tadash_awake import core
    db = core.connect(root / "state")
    db.close()
    core.set_paused(root / "state", False)
    started = core.tick(root / "state")
    if started["status"] != "idle_no_evidence":
        core.set_paused(root / "state", True)
        return "AWAKE=BLOCKED;CAUSE=FIRST_TICK_FAILED"
    ps = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        script = task_powershell(str(Path(sys.executable)), str(root / "awake_task.py"), str(root))
        result = subprocess.run([str(ps), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=30, check=False)
        if result.returncode or "CREATED" not in result.stdout:
            core.set_paused(root / "state", True)
            return "AWAKE=BLOCKED;CAUSE=TASK_REGISTER_FAILED"
        for _ in range(12):
            if (root / "last_run.json").is_file():
                break
            time.sleep(1)
        task = installed_task_state()
        if task not in ("Ready", "Running") or not (root / "last_run.json").is_file():
            core.set_paused(root / "state", True)
            return "AWAKE=BLOCKED;CAUSE=TASK_NOT_VERIFIED"
        last = json.loads((root / "last_run.json").read_text(encoding="utf-8"))
        if last.get("source") != SOURCE or last.get("mode") != "offline_evidence_only":
            core.set_paused(root / "state", True)
            return "AWAKE=BLOCKED;CAUSE=UNEXPECTED_TASK_REPORT"
        return "AWAKE=ACTIVE;SCHEDULE=HOURLY;TASK=VERIFIED;TICKS=1;MODE=OFFLINE;INGEST=0"
    except (ValueError, OSError, subprocess.SubprocessError):
        core.set_paused(root / "state", True)
        return "AWAKE=BLOCKED;CAUSE=SCHEDULER_ERROR"


if __name__ == "__main__":
    try:
        summary = main()
    except BaseException:
        summary = "AWAKE=BLOCKED;CAUSE=INSTALL_EXCEPTION"
    report(summary)
