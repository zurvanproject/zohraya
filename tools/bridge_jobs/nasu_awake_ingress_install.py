"""Opt-in deployment of a separate hourly offline simulated sense->DIOS->Awake task.

Uses only public, immutable sources verified against exact Git blob identities.
Never touches existing Awake timer, Bridge, credentials, main, or patient files.
Not physical sensors or a general autonomous model; no live API calls after setup.
"""
import ast
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
from urllib.request import Request, ProxyHandler, HTTPSHandler, HTTPRedirectHandler, build_opener
import zipfile

REPO = "zurvanproject/zohraya"
PR198 = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"
TREE = "6ba874c28bd8eec67dde94d6e66b0acc2c87223f"
PR205_SOURCE = "320ce8adcc789f11f8966ca2c7251fd860fa44f6"
INGRESS_BLOB = "86cb15862a7e5f7dfe2b20209fb7ea6718e373ff"
TASK = "NasurayaAwakeIngress"

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()

def opener():
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))

def get(url, limit):
    if not (url.startswith("https://codeload.github.com/" + REPO + "/zip/" + PR198)
            or url.startswith("https://api.github.com/repos/" + REPO + "/git/trees/" + TREE)
            or url == "https://raw.githubusercontent.com/" + REPO + "/" + PR205_SOURCE + "/tadash_awake/live_ingress.py"):
        raise ValueError("not a fixed allowed source")
    req = Request(url, headers={"User-Agent": "NasurayaAwakeOfflineInstaller/1"})
    with opener().open(req, timeout=18) as response:
        data = response.read(limit + 1)
    if not 1 <= len(data) <= limit:
        raise ValueError("source download size invalid")
    return data

def manifest():
    url = "https://api.github.com/repos/" + REPO + "/git/trees/" + TREE + "?recursive=1"
    record = json.loads(get(url, 600000).decode("utf-8"))
    if record.get("sha") != TREE or record.get("truncated") is not False:
        raise ValueError("pinned Git tree verification failure")
    items = record.get("tree")
    if type(items) is not list:
        raise ValueError("invalid Git tree")
    entries = {}
    for item in items:
        if item["type"] != "blob":
            continue
        path = item["path"]
        if (item.get("mode") != "100644" or type(path) is not str
                or path.startswith("/") or "\\" in path
                or any(s in ("", ".", "..") for s in path.split("/"))
                or type(item.get("sha")) is not str
                or len(item["sha"]) != 40 or not 0 <= item.get("size", -1) <= 2000000):
            raise ValueError("unsupported Git blob")
        entries[path] = (item["sha"], item["size"])
    if not 550 <= len(entries) <= 700 or sum(size for _, size in entries.values()) > 24000000:
        raise ValueError("unexpected source tree size")
    return entries

def unpack_staged(staging):
    entries = manifest()
    url = "https://codeload.github.com/" + REPO + "/zip/" + PR198
    archive = get(url, 25000000)
    expected_prefix = "zohraya-" + PR198 + "/"
    path = Path(staging) / "source_pr198"
    path.mkdir()
    seen = set()
    with zipfile.ZipFile(BytesIO(archive)) as z:
        if len(z.infolist()) > 900:
            raise ValueError("archive too many entries")
        for member in z.infolist():
            if member.is_dir():
                continue
            name = member.filename
            if not name.startswith(expected_prefix):
                raise ValueError("archive prefix mismatch")
            relative = name[len(expected_prefix):]
            if relative not in entries or relative in seen:
                raise ValueError("unexpected or duplicated archive file")
            expected, size = entries[relative]
            if member.file_size != size or member.file_size > 2000000:
                raise ValueError("archive file size mismatch")
            raw = z.read(member)
            if len(raw) != size or blob_sha(raw) != expected:
                raise ValueError("archive Git blob content mismatch")
            dest = path.joinpath(*relative.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            seen.add(relative)
    if seen != set(entries):
        raise ValueError("missing Git files")
    manifest_body = {"commit": PR198, "tree": TREE,
                     "blobs": {name: sha for name, (sha, _) in entries.items()}}
    Path(staging, "source_manifest.json").write_text(
        json.dumps(manifest_body, sort_keys=True, separators=(",", ":")),
        encoding="utf-8")
    return len(entries)

def fetch_ingress(staging):
    url = ("https://raw.githubusercontent.com/" + REPO + "/" +
           PR205_SOURCE + "/tadash_awake/live_ingress.py")
    raw = get(url, 12000)
    if blob_sha(raw) != INGRESS_BLOB:
        raise ValueError("pinned ingestion module mismatch")
    ast.parse(raw, filename="live_ingress.py")
    dest = Path(staging) / "live_ingress.py"
    dest.write_bytes(raw)

RUNNER = r'''"""Pinned read-only CI-tested synthetic session importer."""
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
EXPECTED = "__INGRESS_BLOB__"

def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()

def main():
    path = ROOT / "tadash_awake" / "live_ingress.py"
    if not path.is_file() or blob_sha(path.read_bytes()) != EXPECTED:
        return 3
    sys.path.insert(0, str(ROOT))
    from tadash_awake.live_ingress import run
    result = run(ROOT)
    return 0 if result["status"] in (
        "imported_simulation", "recovered_uningested", "deferred_hourly",
        "capacity_review", "paused") else 2

if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        sys.exit(2)
'''

def task_script(root):
    # Runs using existing service account, Limited token, no stored password.
    script = r"""
$ErrorActionPreference = 'Stop'
$name='NasurayaAwakeIngress'
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {throw 'already exists'}
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$p=New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
$action=New-ScheduledTaskAction -Execute '__PYTHON__' -Argument '-I -S -X utf8 "__SCRIPT__"' -WorkingDirectory '__ROOT__'
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Description 'Source-pinned offline simulated sense/DIOS ingress; no API or physical sensors' -Action $action -Trigger $trigger -Settings $settings -Principal $p -ErrorAction Stop | Out-Null
Start-ScheduledTask -TaskName $name -ErrorAction Stop
'CREATED'
"""
    repl = {"__PYTHON__": str(Path(sys.executable)),
            "__SCRIPT__": str(root / "ingress_task.py"), "__ROOT__": str(root)}
    for key, value in repl.items():
        if any(c in value for c in "'\r\n"):
            raise ValueError("unsafe task path")
        script = script.replace(key, value)
    return script

def task_state():
    ps = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    query = "$t=Get-ScheduledTask -TaskName 'NasurayaAwakeIngress' -ErrorAction SilentlyContinue; if ($null -eq $t) {'ABSENT'} else {$t.State.ToString()}"
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", query],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12)
    s = result.stdout.strip()
    return s if result.returncode == 0 and s in ("ABSENT", "Ready", "Running", "Disabled") else "UNKNOWN"

def install():
    if sys.version_info < (3, 11):
        return "INGRESS=BLOCKED;CAUSE=PYTHON_OLD"
    if os.name != "nt" and "--self-test" not in sys.argv:
        return "INGRESS=BLOCKED;CAUSE=WINDOWS_ONLY"
    if "--self-test" in sys.argv:
        with tempfile.TemporaryDirectory() as temp:
            num = unpack_staged(temp)
            fetch_ingress(temp)
            from_source = Path(temp, "source_pr198", "examples", "nasuraya_runtime", "session.py")
            if not from_source.is_file():
                raise ValueError("runtime missing from archive")
        return "INGRESS=SELFTEST_OK;SOURCE_FILES="+str(num)+";MODEL_API=0"
    root = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "NasurayaAwake"
    if root.is_symlink() or not (root / "state" / "awake.sqlite3").is_file():
        return "INGRESS=BLOCKED;CAUSE=AWAKE_MISSING"
    if (root / "source_pr198").exists() or (root / "ingress_task.py").exists() or (root / "_ingress_staging").exists():
        return "INGRESS=BLOCKED;CAUSE=EXISTING_PATH"
    if task_state() != "ABSENT":
        return "INGRESS=BLOCKED;CAUSE=TASK_EXISTS_OR_UNKNOWN"
    if shutil.disk_usage(root).free < 100*1024*1024:
        return "INGRESS=BLOCKED;CAUSE=LOW_STORAGE"
    stage = root / "_ingress_staging"
    stage.mkdir(exist_ok=False)
    count = unpack_staged(stage)
    fetch_ingress(stage)
    script = RUNNER.replace("__INGRESS_BLOB__", INGRESS_BLOB)
    ast.parse(script)
    (stage / "ingress_task.py").write_text(script, encoding="utf-8")
    # All expensive verification finished before any file is moved to active root.
    (stage / "source_pr198").replace(root / "source_pr198")
    (stage / "source_manifest.json").replace(root / "source_manifest.json")
    (stage / "live_ingress.py").replace(root / "tadash_awake" / "live_ingress.py")
    (stage / "ingress_task.py").replace(root / "ingress_task.py")
    stage.rmdir()
    ps = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    cmd = task_script(root)
    result = subprocess.run([str(ps), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", cmd],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25)
    if result.returncode != 0 or "CREATED" not in result.stdout or task_state() not in ("Ready","Running"):
        return "INGRESS=BLOCKED;CAUSE=TASK_NOT_VERIFIED"
    return "INGRESS=SCHEDULED;TASK=VERIFIED;SOURCE_FILES="+str(count)+";MODE=SYNTHETIC;API=0"

if __name__ == "__main__":
    try:
        message = install()
    except BaseException:
        message = "INGRESS=BLOCKED;CAUSE=INSTALL_EXCEPTION"
    if len(message) > 170:
        message = "INGRESS=BLOCKED;CAUSE=RECEIPT_LENGTH"
    print(json.dumps({"status":"ok","summary":message}, separators=(",", ":")))
