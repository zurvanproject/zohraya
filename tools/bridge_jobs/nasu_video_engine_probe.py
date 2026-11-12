"""Bounded local media-engine audit; no install, model load or external API.

Inspect the bridge Python, known model/app directories, and localhost ComfyUI.
Never read credentials, user documents, model contents or process command lines.
The only binary read/executed is the previously installed SHA256-pinned FFmpeg.
The encode/decode smoke test uses pipes, creating no persistent media files.
Directory absence is scoped evidence, never proof about the whole machine.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

EXE_BYTES = 64654336
EXE_SHA = "404fdd541eecc577d8f24bf9a976f1e4209f4292022a41c01f5cc2f1b0d375ac"
SAFE = re.compile(r"[a-zA-Z0-9 .,:;=/_()+-]{1,180}", re.ASCII)
WEIGHT_SUFFIXES = {".safetensors", ".ckpt", ".gguf", ".pt", ".pth", ".bin"}


def package(name):
    try:
        return int(importlib.util.find_spec(name) is not None)
    except (ImportError, ValueError, OSError):
        return "U"


def encode_decode(exe):
    if not exe.is_file():
        return "MISSING"
    if exe.is_symlink() or exe.stat().st_size != EXE_BYTES:
        return "HASH_FAIL"
    if hashlib.sha256(exe.read_bytes()).hexdigest() != EXE_SHA:
        return "HASH_FAIL"
    common = [str(exe), "-nostdin", "-hide_banner", "-loglevel", "error"]
    try:
        encoded = subprocess.run(
            common + ["-f", "lavfi", "-i", "testsrc2=s=160x120:r=8:d=1",
                      "-threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                      "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
        if encoded.returncode or not 512 <= len(encoded.stdout) <= 1024 * 1024:
            return "ENC_FAIL"
        decoded = subprocess.run(
            common + ["-i", "pipe:0", "-threads", "1", "-f", "null", "-"],
            input=encoded.stdout, capture_output=True, timeout=10, check=False)
        return "ENC_DEC_OK" if decoded.returncode == 0 else "DEC_FAIL"
    except (OSError, subprocess.SubprocessError):
        return "TEST_FAIL"


def model_roots():
    data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    drive = Path(os.environ.get("SystemDrive", "C:") + "\\")
    roots = [data / "NasurayaBridge", data / "ComfyUI", drive / "ComfyUI",
             drive / "ComfyUI_windows_portable", drive / "Wan2.2"]
    for key in ("ProgramFiles", "LOCALAPPDATA"):
        value = os.environ.get(key)
        if value:
            roots += [Path(value) / "ComfyUI", Path(value) / "Programs" / "ComfyUI"]
    profile = os.environ.get("USERPROFILE")
    if profile:
        roots += [Path(profile) / "Documents" / "ComfyUI",
                  Path(profile) / ".cache" / "huggingface" / "hub"]
    return list(dict.fromkeys(roots))


def scan_models(roots, max_entries=4000, max_seconds=6):
    # Metadata only: do not open any discovered file or follow reparse points.
    deadline = time.monotonic() + max_seconds
    stack = [(p, 0) for p in roots]
    seen = set()
    weights = alternate_python = entries = 0
    complete = True
    while stack:
        root, depth = stack.pop()
        key = str(root).casefold()
        if key in seen:
            continue
        seen.add(key)
        if time.monotonic() >= deadline or entries >= max_entries:
            complete = False
            break
        try:
            if not root.exists():
                continue
            if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
                complete = False
                continue
            with os.scandir(root) as iterator:
                for item in iterator:
                    entries += 1
                    if entries > max_entries or time.monotonic() >= deadline:
                        complete = False
                        break
                    if item.is_symlink():
                        complete = False
                        continue
                    stat = item.stat(follow_symlinks=False)
                    if getattr(stat, "st_file_attributes", 0) & 0x400:
                        complete = False
                        continue
                    if item.is_dir(follow_symlinks=False):
                        if depth < 8 and item.name not in {".git", "__pycache__"}:
                            stack.append((Path(item.path), depth + 1))
                        elif depth >= 8:
                            complete = False
                    elif item.is_file(follow_symlinks=False):
                        suffix = Path(item.name).suffix.lower()
                        if suffix in WEIGHT_SUFFIXES and stat.st_size >= 8 * 1024 * 1024:
                            weights += 1
                        if item.name.lower() in {"python.exe", "pythonw.exe"}:
                            alternate_python += 1
        except OSError:
            complete = False
    return weights, alternate_python, "OK" if complete else "PARTIAL"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def comfy_status():
    # One fixed loopback read; no model generation or remote requests.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open("http://127.0.0.1:8188/system_stats", timeout=2) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            return "U"
        data = json.loads(raw)
        return "UP" if isinstance(data, dict) and isinstance(data.get("system"), dict) and isinstance(data.get("devices"), list) else "OTHER"
    except (OSError, ValueError):
        return "NO_REPLY"


def torch_runtime(found):
    if found == 0:
        return "NO_TORCH"
    if found != 1:
        return "U"
    code = ("import json,torch; x=torch.tensor([1.0])+1; "
            "print(json.dumps({'ok':x.item()==2,'cuda':bool(torch.cuda.is_available())}))")
    try:
        run = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                             stdin=subprocess.DEVNULL, capture_output=True,
                             timeout=12, check=False)
        if run.returncode or len(run.stdout) > 2048:
            return "IMPORT_FAIL"
        data = json.loads(run.stdout)
        if data.get("ok") is not True:
            return "TEST_FAIL"
        return "YES" if data.get("cuda") is True else "NO"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "TEST_FAIL"


def summary(values):
    result = ";".join(f"{key}={value}" for key, value in values.items())
    return result if SAFE.fullmatch(result) else "AUDIT=OUTPUT_REJECTED"


def main():
    if os.name != "nt":
        return "AUDIT=SKIPPED;REASON=WINDOWS_REQUIRED"
    root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NasurayaBridge"
    video = encode_decode(root / "video241_v1" / "ffmpeg.exe")
    torch, diff = package("torch"), package("diffusers")
    weights, alternate_python, scan = scan_models(model_roots())
    comfy = comfy_status()
    cuda = torch_runtime(torch)
    # Presence is not readiness. No result from this probe claims generation.
    gen = "NOT_READY" if torch == 0 and diff == 0 and weights == 0 and alternate_python == 0 and scan == "OK" and comfy == "NO_REPLY" else "UNVERIFIED"
    return summary({"VIDEO": video, "TORCH": torch, "DIFF": diff, "COMFY": comfy,
                    "WEIGHTS": weights, "PYALT": alternate_python, "SCAN": scan,
                    "CUDA": cuda, "GEN": gen})


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        result = "AUDIT=FAILED;DETAILS=WITHHELD"
    print(json.dumps({"status": "ok", "summary": result}, separators=(",", ":")))
