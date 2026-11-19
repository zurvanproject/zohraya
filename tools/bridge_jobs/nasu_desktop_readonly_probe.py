"""Bounded desktop readiness inventory. No installation or configuration writes.

Only OS/RAM/disk/GPU inventory, machine browser executable versions, two known
public-desktop shortcut contents, and unauthenticated HTTPS HEAD requests are
read. No user profiles, credential stores, cookies, environment dumps, process
command lines, browser launch, model inference or API generation are used.
The existing Bridge writes its normal transient job and execution journal.
All public output is allowlisted, <=180 ASCII characters, and omits paths/IPs.
"""
from __future__ import annotations

import ctypes
import email.utils
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

MIB = 1024 * 1024
SAFE = re.compile(r"[a-zA-Z0-9 .,:;=/_()+-]{1,180}", re.ASCII)
URLS = ("https://chatgpt.com/", "https://chatgpt.com/images/")


def integer(value, limit=10**9):
    try:
        number = int(value)
        return str(number) if 0 <= number <= limit else "U"
    except (ValueError, TypeError, OverflowError):
        return "U"


def inventory():
    # Fixed read-only PowerShell. Never use Win32_Product (it can repair MSIs).
    script = r"""
$ErrorActionPreference='Stop'
$o=Get-WmiObject Win32_OperatingSystem
$d=Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'"
$g=@(Get-WmiObject Win32_VideoController | ForEach-Object {$_.Name})
[ordered]@{ram=[int64]($o.TotalVisibleMemorySize/1024);avail=[int64]($o.FreePhysicalMemory/1024);free=[int64]($d.FreeSpace/1MB);size=[int64]($d.Size/1MB);gpu=$g} | ConvertTo-Json -Compress
"""
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(exe), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=15, check=False)
        if result.returncode or len(result.stdout) > 8192:
            return {}
        parsed = json.loads(result.stdout.lstrip("\ufeff"))
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def gpu_class(names):
    if not isinstance(names, list) or not names:
        return "U"
    joined = " ".join(str(name).lower() for name in names)
    vendors = [label for word, label in (("nvidia", "NV"), ("amd", "AMD"), ("radeon", "AMD"), ("intel", "INT")) if word in joined]
    if vendors:
        return "+".join(sorted(set(vendors)))
    if any(word in joined for word in ("remote", "vmware", "virtual", "basic display", "qxl", "hyper-v")):
        return "VIRT"
    return "OTHER"


def nvidia_memory():
    # Never execute an arbitrary PATH match or install a missing utility.
    candidates = (
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/nvidia-smi.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation/NVSMI/nvidia-smi.exe",
    )
    for path in candidates:
        if path.is_file():
            try:
                out = subprocess.run([str(path), "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                     stdin=subprocess.DEVNULL, capture_output=True,
                                     text=True, timeout=5, check=False)
                values = [int(x) for x in out.stdout.splitlines() if x.strip().isdigit()]
                if out.returncode == 0 and values:
                    # Largest single device, not pooled VRAM; no usable-GPU claim.
                    return integer(max(values))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
    return "U"


def file_major(path):
    # Read the PE version resource; do not launch the browser executable.
    from ctypes import wintypes

    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in (
            "signature", "struct_version", "file_ms", "file_ls", "product_ms", "product_ls",
            "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]

    version = ctypes.windll.version
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not 0 < size <= 1024 * 1024:
        return None
    block = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, block):
        return None
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(block, "\\", ctypes.byref(ptr), ctypes.byref(length)):
        return None
    if length.value < ctypes.sizeof(VS_FIXEDFILEINFO):
        return None
    info = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    return (info.product_ms >> 16) if info.signature == 0xFEEF04BD else None


def browser_major(executable, relative):
    import winreg
    candidates = set()
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + executable,
                               0, winreg.KEY_READ | view) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if isinstance(value, str):
                    candidates.add(Path(value.strip('"')))
        except OSError:
            pass
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.add(Path(root) / relative)
    found, versions = False, []
    for path in candidates:
        try:
            if path.is_absolute() and path.is_file() and path.name.lower() == executable:
                found = True
                version = file_major(path)
                if version is not None:
                    versions.append(version)
        except (OSError, ValueError):
            pass
    return integer(max(versions), 9999) if versions else ("U" if found else "ND")


def shortcuts():
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x19, None, 0, buffer) != 0:
        return "U"
    desktop = Path(buffer.value)
    states = []
    for name, url in zip(("Nasuraya - Chat.url", "Nasuraya - Images.url"), URLS):
        path = desktop / name
        try:
            if not path.exists():
                states.append("M")
            elif path.is_symlink() or not path.is_file() or path.stat().st_size > 512:
                states.append("X")
            else:
                expected = ("[InternetShortcut]\r\nURL=" + url + "\r\n").encode("ascii")
                states.append("Y" if path.read_bytes() == expected else "X")
        except OSError:
            states.append("U")
    return "".join(states)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def head(url):
    if url not in URLS:
        raise ValueError("destination_not_allowlisted")
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "NasurayaReadOnlyAudit/1"})
    response = None
    try:
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        code = integer(response.code, 599)
        skew = "U"
        try:
            timestamp = email.utils.parsedate_to_datetime(response.headers.get("Date", "")).timestamp()
            skew = integer(round(abs(time.time() - timestamp) / 60), 99999)
        except (ValueError, TypeError, AttributeError, OverflowError):
            pass
        return code, skew
    except (OSError, urllib.error.URLError, ssl.SSLError):
        return "ERR", "U"
    finally:
        if response is not None:
            response.close()


def result_summary(data):
    summary = ";".join(f"{key}={value}" for key, value in data.items())
    if not SAFE.fullmatch(summary):
        return "AUDIT=OUTPUT_REJECTED"
    return summary


def main():
    if os.name != "nt":
        return "AUDIT=SKIPPED;REASON=WINDOWS_REQUIRED"
    info = inventory()
    win = sys.getwindowsversion()
    session = ctypes.c_ulong()
    session_ok = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
    chat, skew = head(URLS[0])
    images, _ = head(URLS[1])
    return result_summary({
        "OS": f"{win.major}.{win.minor}", "CPU": integer(os.cpu_count()),
        "RAM": integer(info.get("ram")) + "/" + integer(info.get("avail")),
        "DISK": integer(info.get("free")) + "/" + integer(info.get("size")),
        "CH": browser_major("chrome.exe", "Google/Chrome/Application/chrome.exe"),
        "ED": browser_major("msedge.exe", "Microsoft/Edge/Application/msedge.exe"),
        "FF": browser_major("firefox.exe", "Mozilla Firefox/firefox.exe"),
        "GPU": gpu_class(info.get("gpu")), "NVMB": nvidia_memory(),
        "LINKS": shortcuts(), "WEB": chat + "/" + images,
        "CLK": skew, "S": integer(session.value) if session_ok else "U",
    })


if __name__ == "__main__":
    try:
        summary = main()
    except Exception:
        # Never publish raw errors, local paths, host names or environment values.
        summary = "AUDIT=FAILED;DETAILS=WITHHELD"
    print(json.dumps({"status": "ok", "summary": summary}, separators=(",", ":")))
