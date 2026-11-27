#!/usr/bin/env python3
"""Stage, verify and offline-smoke the *installed* Ollama qwen3:4b-instruct.

Not a downloader, installer or production service controller. Intended to be
called by the opt-in PR #234 restic snapshot and on an independent Linux host.
Never runs model-provided code. All artifacts remain in operator-selected paths.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

TAG = "qwen3:4b-instruct"
TAG_REL = "manifests/registry.ollama.ai/library/qwen3/4b-instruct"
MODEL_ARCHIVE = "ollama-qwen3-4b-models.tar.gz"
RUNTIME_ARCHIVE = "ollama-qwen3-4b-runtime.tar.gz"
INFO_FILE = "ollama-qwen3-4b-info.json"
ARTIFACTS = (MODEL_ARCHIVE, RUNTIME_ARCHIVE, INFO_FILE)
SCHEMA = "nasuraya-ollama-qwen3-4b/1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_MODEL_FILES = 64
MAX_MODEL_BYTES = 20 * 1024 ** 3
MAX_RUNTIME_FILES = 4096
MAX_RUNTIME_BYTES = 8 * 1024 ** 3


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha(fileobj):
    h = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


def no_links(path, kind="source"):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"Missing or linked {kind}")
    return p


def ensure_dir(p):
    p = Path(p)
    if not p.is_dir() or p.is_symlink():
        raise ValueError("Missing or linked source directory")
    return p


def layers_for_manifest(manifest_bytes):
    if len(manifest_bytes) > 4 * 1024 * 1024:
        raise ValueError("Oversized Ollama tag manifest")
    doc = json.loads(manifest_bytes)
    entries = [doc.get("config")] + doc.get("layers", [])
    if not isinstance(entries, list) or not 2 <= len(entries) <= MAX_MODEL_FILES:
        raise ValueError("Invalid model layer list")
    blobs = {}
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("digest"), str):
            raise ValueError("Malformed Ollama descriptor")
        value = item["digest"]
        if not value.startswith("sha256:") or not SHA_RE.fullmatch(value[7:]):
            raise ValueError("Unsupported/unsafe Ollama descriptor")
        size = item.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("Missing descriptor size")
        name = "blobs/sha256-" + value[7:]
        if name in blobs and blobs[name] != size:
            raise ValueError("Duplicate layer has conflicting sizes")
        blobs[name] = size
    return blobs


def write_tar(dest, sources, max_files, max_bytes):
    if len(sources) > max_files or sum(p.stat().st_size for p in sources.values()) > max_bytes:
        raise ValueError("Asset set exceeds declared backup limits")
    # All tar members are regular files with normalized relative paths. No links.
    with tarfile.open(dest, "w:gz") as tar:
        for name, path in sorted(sources.items()):
            validate_name(name)
            source = no_links(path)
            item = tarfile.TarInfo(name)
            item.size = source.stat().st_size
            item.mode = 0o755 if name == "runtime/bin/ollama" else 0o600
            item.mtime = 0
            item.uid = item.gid = 0
            item.uname = item.gname = ""
            with source.open("rb") as stream:
                tar.addfile(item, stream)


def validate_name(name):
    p = PurePosixPath(name)
    if (not name or name.startswith("/") or "\\" in name or ".." in p.parts
            or "." in p.parts or "//" in name or str(p) != name):
        raise ValueError("Unsafe archive member name")


def runtime_sources(binary, libdir):
    binary = no_links(binary, "Ollama binary")
    libdir = ensure_dir(libdir)
    sources = {"runtime/bin/ollama": binary}
    for p in sorted(libdir.rglob("*")):
        if p.is_dir() and not p.is_symlink():
            continue
        # Resolve internal symlinked shared libraries into regular archive files.
        resolved = p.resolve(strict=True)
        if not resolved.is_relative_to(libdir.resolve()) or not resolved.is_file():
            raise ValueError("Ollama library symlink escapes its source directory")
        rel = p.relative_to(libdir).as_posix()
        name = "runtime/lib/ollama/" + rel
        validate_name(name)
        sources[name] = resolved
    if len(sources) < 2:
        raise ValueError("Ollama runtime libraries absent")
    return sources


def host_information(binary):
    info = {"arch": platform.machine(), "os_id": None, "os_version_id": None,
            "ollama_version_output": "", "ldd_output": ""}
    release = Path("/etc/os-release")
    if release.is_file():
        for line in release.read_text(encoding="utf-8").splitlines():
            for key, out in (("ID", "os_id"), ("VERSION_ID", "os_version_id")):
                if line.startswith(key + "="):
                    info[out] = line.split("=", 1)[1].strip().strip('"')
    try:
        check = subprocess.run([str(binary), "--version"], capture_output=True,
                               text=True, timeout=12, check=False)
        info["ollama_version_output"] = (check.stdout + check.stderr)[-1024:]
        if check.returncode:
            raise ValueError("Installed Ollama binary version check failed")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Installed Ollama version cannot be checked") from exc
    try:
        check = subprocess.run(["ldd", str(binary)], capture_output=True, text=True,
                               timeout=12, check=False)
        deps = (check.stdout + check.stderr)[-8192:]
        if "not found" in deps:
            raise ValueError("Missing Ollama shared-library dependency")
        info["ldd_output"] = deps
    except FileNotFoundError:
        raise ValueError("ldd missing; runtime dependency status unknown")
    try:
        check = subprocess.run(["dpkg-query", "-W", "-f=${binary:Package}=${Version}\n",
            "libc6", "libstdc++6", "libgcc-s1", "python3", "iproute2", "util-linux",
            "git", "restic"], capture_output=True, text=True, timeout=12, check=False)
        info["os_package_versions"] = check.stdout.splitlines()[:20]
    except (OSError, subprocess.TimeoutExpired):
        info["os_package_versions"] = ["UNAVAILABLE: dependency inventory not verified"]
    return info


def stage(stage_dir, models_dir, binary, libdir):
    stage_dir = ensure_dir(stage_dir)
    models_dir = ensure_dir(models_dir)
    tag = no_links(models_dir / TAG_REL, "model manifest")
    manifest_bytes = tag.read_bytes()
    blobs = layers_for_manifest(manifest_bytes)
    model_sources = {"models/" + TAG_REL: tag}
    for rel, size in blobs.items():
        blob = no_links(models_dir / rel, "Ollama model blob")
        if blob.stat().st_size != size or digest(blob) != rel.rsplit("-", 1)[-1]:
            raise ValueError("Ollama model layer size/hash mismatch")
        model_sources["models/" + rel] = blob
    runtime = runtime_sources(binary, libdir)
    if len(model_sources) > MAX_MODEL_FILES:
        raise ValueError("Too many model layers")
    metadata = {
        "schema": SCHEMA, "tag": TAG, "host": host_information(binary),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "model_files_sha256": {key: digest(path) for key, path in sorted(model_sources.items())},
        "runtime_files_sha256": {key: digest(path) for key, path in sorted(runtime.items())},
    }
    # Write archives via temporary files, then rename atomically in staging.
    created = []
    try:
        for name, sources, limit_files, limit_bytes in (
            (MODEL_ARCHIVE, model_sources, MAX_MODEL_FILES, MAX_MODEL_BYTES),
            (RUNTIME_ARCHIVE, runtime, MAX_RUNTIME_FILES, MAX_RUNTIME_BYTES),
        ):
            dest = stage_dir / name
            if dest.exists() or dest.is_symlink():
                raise ValueError("Refusing to overwrite staged model artifacts")
            tmp = stage_dir / (name + ".partial")
            if tmp.exists() or tmp.is_symlink():
                raise ValueError("Stale staged partial archive")
            created.append(tmp)
            write_tar(tmp, sources, limit_files, limit_bytes)
            tmp.replace(dest)
            created.append(dest)
        metadata["archives_sha256"] = {
            MODEL_ARCHIVE: digest(stage_dir / MODEL_ARCHIVE),
            RUNTIME_ARCHIVE: digest(stage_dir / RUNTIME_ARCHIVE),
        }
        info = stage_dir / INFO_FILE
        if info.exists() or info.is_symlink():
            raise ValueError("Refusing to overwrite staged metadata")
        info.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        created.append(info)
        verify_bundle(stage_dir)
        return {"tag": TAG, "artifact_names": list(ARTIFACTS),
                "model_blobs": len(blobs), "archive_bytes": sum((stage_dir / x).stat().st_size
                                                       for x in (MODEL_ARCHIVE, RUNTIME_ARCHIVE))}
    except BaseException:
        for p in reversed(created):
            p.unlink(missing_ok=True)
        raise


def verify_archive(archive, expected, max_files, max_bytes):
    if not isinstance(expected, dict) or not expected or len(expected) > max_files:
        raise ValueError("Invalid archive inventory")
    if any(not isinstance(k, str) or not isinstance(v, str) or not SHA_RE.fullmatch(v)
           for k, v in expected.items()):
        raise ValueError("Invalid inventory member or checksum")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) != len(expected) or sum(m.size for m in members) > max_bytes:
            raise ValueError("Archive membership/size violates bounds")
        observed = {}
        for m in members:
            validate_name(m.name)
            if not m.isfile() or m.name in observed or m.name not in expected:
                raise ValueError("Link, special, duplicate, or unexpected archive member")
            stream = tar.extractfile(m)
            if stream is None:
                raise ValueError("Unreadable archive member")
            observed[m.name] = file_sha(stream)
        if observed != expected:
            raise ValueError("Archived contents mismatch inventory")


def verify_bundle(root):
    root = ensure_dir(root)
    info_path = no_links(root / INFO_FILE, "Ollama inventory")
    if info_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Oversized bundle metadata")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("schema") != SCHEMA or info.get("tag") != TAG:
        raise ValueError("Unexpected model bundle format or tag")
    host = info.get("host")
    if not isinstance(host, dict) or not host.get("arch") or not host.get("os_id"):
        raise ValueError("Missing target OS/architecture metadata")
    for name in (MODEL_ARCHIVE, RUNTIME_ARCHIVE):
        archive = no_links(root / name, "Ollama archive")
        expected = info.get("archives_sha256", {}).get(name)
        if not isinstance(expected, str) or digest(archive) != expected:
            raise ValueError("Ollama archive hash mismatch")
    model_expected = info.get("model_files_sha256")
    runtime_expected = info.get("runtime_files_sha256")
    if not isinstance(model_expected, dict) or not isinstance(runtime_expected, dict):
        raise ValueError("Model/runtime inventory absent")
    manifest_name = "models/" + TAG_REL
    if manifest_name not in model_expected or "runtime/bin/ollama" not in runtime_expected:
        raise ValueError("Model tag or Ollama binary missing from archive inventory")
    if not all(k.startswith("models/blobs/sha256-") or k == manifest_name
               for k in model_expected):
        raise ValueError("Unexpected model payload path")
    if not all(k.startswith("runtime/lib/ollama/") or k == "runtime/bin/ollama"
               for k in runtime_expected) or len(runtime_expected) < 2:
        raise ValueError("Unexpected/incomplete runtime payload")
    verify_archive(root / MODEL_ARCHIVE, model_expected, MAX_MODEL_FILES, MAX_MODEL_BYTES)
    verify_archive(root / RUNTIME_ARCHIVE, runtime_expected, MAX_RUNTIME_FILES,
                   MAX_RUNTIME_BYTES)
    # Read the manifest inside the archive to prove every referenced digest exists.
    with tarfile.open(root / MODEL_ARCHIVE, "r:gz") as tar:
        m = tar.extractfile(manifest_name)
        if m is None:
            raise ValueError("Model tag manifest absent")
        manifest_bytes = m.read(4 * 1024 * 1024 + 1)
    if hashlib.sha256(manifest_bytes).hexdigest() != info.get("source_manifest_sha256"):
        raise ValueError("Model tag manifest checksum mismatch")
    blobs = layers_for_manifest(manifest_bytes)
    if set(model_expected) != {manifest_name} | {"models/" + x for x in blobs}:
        raise ValueError("Referenced model blobs missing or extra")
    for rel in blobs:
        if model_expected["models/" + rel] != rel.rsplit("-", 1)[-1]:
            raise ValueError("Ollama descriptor differs from archived blob SHA")
    return {"status": "ollama_4b_assets_verified", "model_tag": TAG,
            "model_blobs": len(blobs), "arch": host["arch"],
            "runtime_files": len(runtime_expected), "offline_inference_pass": False}


def _unshare_probe_command(root, python_bin):
    return ["unshare", "--net", "--fork", "--", python_bin, "-I",
            str(Path(__file__).resolve()), "_child", str(root)]


def smoke(root, runner=subprocess.run, isolator="unshare", python_bin=sys.executable):
    root = Path(root).resolve(strict=True)
    details = verify_bundle(root)
    host = json.loads((root / INFO_FILE).read_text())["host"]
    if host["arch"] != platform.machine():
        raise ValueError("Recovery architecture mismatch")
    os_release = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k in ("ID", "VERSION_ID"):
                os_release[k] = v.strip().strip('"')
    if (host.get("os_id") != os_release.get("ID") or
            host.get("os_version_id") != os_release.get("VERSION_ID")):
        raise ValueError("Recovery OS release differs from archived runtime baseline")
    if not shutil.which("ip") or not (shutil.which(isolator) or Path(isolator).is_file()):
        raise RuntimeError("Missing ip/unshare: cannot prove offline inference")
    cmd = _unshare_probe_command(root, python_bin)
    cmd[0] = isolator
    outcome = runner(cmd, text=True, capture_output=True, timeout=390, check=False)
    if outcome.returncode:
        raise RuntimeError("Offline Ollama cold-start/inference failed")
    try:
        receipt = json.loads(outcome.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("Offline Ollama smoke did not emit a valid receipt") from exc
    if receipt.get("status") != "offline_model_recovery_smoke_pass":
        raise RuntimeError("Recovered Ollama did not generate text")
    return {**details, **receipt, "independent_host": "operator_attestation_required"}


def _smoke_child(root):
    # Refuse direct execution without a distinct Linux network namespace.
    if os.stat("/proc/self/ns/net").st_ino == os.stat("/proc/1/ns/net").st_ino:
        raise RuntimeError("Not in a separate network namespace")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True,
                   stdout=subprocess.DEVNULL, timeout=10)
    with tempfile.TemporaryDirectory(prefix="nasu-ollama-restore-") as td:
        temp = Path(td)
        for name in (MODEL_ARCHIVE, RUNTIME_ARCHIVE):
            with tarfile.open(root / name, "r:gz") as tar:
                # Strict check was completed in the parent. Repeat no-link check
                # before extraction; data filter also blocks escaping paths.
                for m in tar.getmembers():
                    validate_name(m.name)
                    if not m.isfile():
                        raise ValueError("Unsafe Ollama extraction member")
                tar.extractall(temp, filter="data")
        binpath = temp / "runtime/bin/ollama"
        if not binpath.is_file() or not os.access(binpath, os.X_OK):
            raise ValueError("Recovered Ollama executable missing")
        libpath = temp / "runtime/lib/ollama"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(temp), "LANG": "C.UTF-8",
               "OLLAMA_MODELS": str(temp / "models"), "OLLAMA_NO_CLOUD": "1",
               "OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_MAX_LOADED_MODELS": "1",
               "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_KEEP_ALIVE": "0",
               "LD_LIBRARY_PATH": str(libpath)}
        logfile = (temp / "server.log").open("wb")
        process = subprocess.Popen([str(binpath), "serve"], cwd=temp, env=env,
                                   stdout=logfile, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            base = "http://127.0.0.1:11434"
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Recovered Ollama service exited during startup")
                try:
                    with urllib.request.urlopen(base + "/api/version", timeout=2) as resp:
                        if resp.status == 200:
                            break
                except (OSError, ValueError):
                    time.sleep(1)
            else:
                raise RuntimeError("Recovered Ollama service startup timeout")
            body = json.dumps({"model": TAG, "prompt": "Give one reason to test backup restores.",
                               "stream": False, "options": {"num_predict": 80,
                               "num_ctx": 1024, "num_thread": 2}}).encode()
            req = urllib.request.Request(base + "/api/generate", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=270) as response:
                result = json.loads(response.read(1024 * 1024))
            generated = result.get("response", "")
            if result.get("done") is not True or not isinstance(generated, str) or len(generated.strip()) < 12:
                raise RuntimeError("Recovered Ollama inference returned no substantive text")
            return {"status": "offline_model_recovery_smoke_pass", "model": TAG,
                    "output_sha256": hashlib.sha256(generated.encode()).hexdigest(),
                    "model_process_network": "isolated_linux_namespace"}
        finally:
            # Ollama may spawn model runners; stop the whole temporary session.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            logfile.close()


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("stage")
    s.add_argument("snapshot_dir", type=Path)
    s.add_argument("--models-dir", type=Path, default=Path("/usr/share/ollama/.ollama/models"))
    s.add_argument("--ollama-bin", type=Path, default=Path(shutil.which("ollama") or "/usr/bin/ollama"))
    s.add_argument("--ollama-lib", type=Path, default=Path("/usr/lib/ollama"))
    for name in ("verify", "smoke", "_child"):
        sub.add_parser(name).add_argument("snapshot_dir", type=Path)
    a = p.parse_args(argv)
    try:
        if a.action == "stage":
            result = stage(a.snapshot_dir, a.models_dir, a.ollama_bin, a.ollama_lib)
        elif a.action == "verify":
            result = verify_bundle(a.snapshot_dir)
        elif a.action == "smoke":
            result = smoke(a.snapshot_dir)
        else:
            result = _smoke_child(a.snapshot_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # Avoid leaking source paths, keys or model-generated text in the receipt.
        print(json.dumps({"status": "failed", "error_class": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
