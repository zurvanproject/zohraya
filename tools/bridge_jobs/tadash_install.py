"""Fixed-source Tadash VPS deployment/control job for Nasuraya Bridge v2.
Only a dedicated host directory is modified. No API keys, arbitrary commands or URLs.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
import zipfile

PACKAGE_COMMIT = "33c669113f08da032c75d4eaf2f778d515d7669f"
PACKAGE_SHA256 = "6a0c9fe013aad59716b251c66aadec6081daa764ac76bfdb2dc0763ab2f049cb"
MANIFEST_SHA256 = "1ffedf1f438a2e3b9178a19703cfb2037c5d0296a94743ff9391493edae65d15"
URL = "https://raw.githubusercontent.com/zurvanproject/zohraya/" + PACKAGE_COMMIT + "/deploy/tadash_vps_v01.bundle.b64"
MODE = "install"
MAX_PACKAGE_BYTES = 500000
MAX_UNPACKED_BYTES = 2000000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch():
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    request = Request(URL, headers={"User-Agent": "Nasuraya-Tadash-VPS/1"})
    with build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context)).open(request, timeout=20) as response:
        payload = response.read(MAX_PACKAGE_BYTES + 1)
    if len(payload) > MAX_PACKAGE_BYTES:
        raise ValueError("bounded package required")
    return payload


def digest(data):
    return hashlib.sha256(data).hexdigest()


def installation(root):
    return Path(root) / ("runtime-" + PACKAGE_SHA256[:16])


def verify(directory):
    directory = Path(directory)
    raw = (directory / "FILES_SHA256.json").read_bytes()
    if digest(raw) != MANIFEST_SHA256:
        raise ValueError("installation manifest mismatch")
    manifest = json.loads(raw)
    for name, expected in manifest.items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or digest(path.read_bytes()) != expected:
            raise ValueError("installation file mismatch")
    return directory


def unpack(payload, stage):
    if len(payload) > MAX_PACKAGE_BYTES or digest(payload) != PACKAGE_SHA256:
        raise ValueError("package fingerprint mismatch")
    raw = base64.b64decode(payload, validate=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != 76 or sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
            raise ValueError("archive bounds")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("archive duplicates")
        manifest_bytes = archive.read("FILES_SHA256.json")
        if digest(manifest_bytes) != MANIFEST_SHA256:
            raise ValueError("archive manifest mismatch")
        manifest = json.loads(manifest_bytes)
        if set(names) != set(manifest) | {"FILES_SHA256.json"}:
            raise ValueError("archive allowlist mismatch")
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in entry.filename or ":" in entry.filename:
                raise ValueError("unsafe archive path")
            mode = entry.external_attr >> 16
            if not stat.S_ISREG(mode) or entry.file_size > 800000:
                raise ValueError("regular bounded archive file required")
            target = Path(stage).joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(entry)
            if entry.filename != "FILES_SHA256.json" and digest(data) != manifest[entry.filename]:
                raise ValueError("archive file fingerprint mismatch")
            target.write_bytes(data)
    return verify(stage)


def install_local(payload, root):
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("dedicated real directory required")
    target = installation(root)
    if target.exists():
        return verify(target)
    with tempfile.TemporaryDirectory(prefix="install-", dir=root) as temporary:
        staged = Path(temporary) / "runtime"
        staged.mkdir()
        unpack(payload, staged)
        if target.exists():
            return verify(target)
        os.rename(staged, target)
    return verify(target)


def invoke(root, command):
    if command not in ("init", "step", "status", "replay-first"):
        raise ValueError("bounded native command required")
    directory = verify(installation(root))
    env = {name: value for name, value in os.environ.items()
           if name.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "PATH"}}
    process = subprocess.run([sys.executable, "-I", "-X", "utf8", str(directory / "driver.py"),
                              command, "--state", str(Path(root) / "state")],
                             cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8",
                             timeout=35, check=False)
    result = json.loads(process.stdout)
    if process.returncode != 0 or result.get("status") != "ok":
        error = result.get("error_type", "NativeRejected")
        if not isinstance(error, str) or not error.isascii() or not error.isalnum():
            error = "NativeRejected"
        raise RuntimeError(error)
    return result


def perform(mode, root, payload=None):
    if mode == "install":
        install_local(fetch() if payload is None else payload, root)
        result = invoke(root, "init")
        summary = (f"TADASH=READY; CYCLES={result['completed_cycles']}; REV={result['revision']}; "
                   "SOURCE=70/70; STATE=SQLITE; MASS=195; ACT=0")
    elif mode == "step":
        result = invoke(root, "step")
        replay = invoke(root, "replay-first")
        if replay["native_cycles_in_call"] != 0 or replay["checkpoint_sha256"] != result["checkpoint_sha256"]:
            raise RuntimeError("ReplayMismatch")
        summary = (f"TADASH=NATIVE; CYCLES={result['completed_cycles']}; REV={result['revision']}; "
                   f"REQUEST={result['requested']}; RESULT={result['actual']}; RECALL={result['recalled_feedback']}; "
                   f"REPLAY_EXTRA=0; SIG={result['checkpoint_sha256'][:16]}; ACT=0")
    elif mode == "status":
        result = invoke(root, "status")
        summary = (f"TADASH=ONLINE; CYCLES={result['completed_cycles']}; REV={result['revision']}; "
                   f"UNRESOLVED={result['unresolved']}; SIG={result['checkpoint_sha256'][:16]}; ACT=0")
    else:
        raise ValueError("fixed job mode required")
    return {"status": "ok", "summary": summary}


def main():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ValueError("host account application data directory unavailable")
    return perform(MODE, Path(local) / "NasurayaTadashV1")


if __name__ == "__main__":
    try:
        output = main()
    except Exception as error:
        detail = str(error) if type(error) is RuntimeError and str(error).isascii() and str(error).isalnum() else type(error).__name__
        output = {"status": "ok", "summary": "TADASH=FAILED; ERROR=" + detail}
    print(json.dumps(output, separators=(",", ":")))

