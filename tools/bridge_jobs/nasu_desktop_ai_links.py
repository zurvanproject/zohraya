"""Create two reversible web shortcuts on the VPS public desktop.

No key access, model calls, downloads, browser launch, service, firewall change,
or startup task. Opening and signing in belong to the interactive user.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

LINKS = {
    "Nasuraya - Chat.url": "https://chatgpt.com/",
    "Nasuraya - Images.url": "https://chatgpt.com/images/",
}


def content(url: str) -> bytes:
    return ("[InternetShortcut]\r\nURL=" + url + "\r\n").encode("ascii")


def install(desktop: Path) -> str:
    if not desktop.is_dir():
        return "DESKTOP=NOT_FOUND;CHANGED=0"
    desired = {desktop / name: content(url) for name, url in LINKS.items()}
    # Refuse to overwrite an unrelated or redirected shortcut.
    for path, data in desired.items():
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != data)):
            return "DESKTOP=NAME_CONFLICT;CHANGED=0"
    created = []
    try:
        for path, data in desired.items():
            if not path.exists():
                # Exclusive creation also protects against a concurrent change.
                with path.open("xb") as stream:
                    created.append(path)
                    stream.write(data)
        if not all(path.read_bytes() == data for path, data in desired.items()):
            raise OSError("verification_failed")
    except OSError:
        for path in created:
            try:
                if path.is_file() and path.read_bytes() == desired[path]:
                    path.unlink()
            except OSError:
                pass
        return "DESKTOP=WRITE_FAILED;REVIEW_REQUIRED=1"
    state = "CREATED" if created else "ALREADY_PRESENT"
    return "DESKTOP=" + state + ";CHAT=OK;IMAGES=OK;LOGIN=USER_REQUIRED;MODEL=WEB;API_CALLS=0"


def main() -> None:
    if os.name != "nt":
        summary = "DESKTOP=NOT_WINDOWS;CHANGED=0"
    else:
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            # CSIDL_COMMON_DESKTOPDIRECTORY: visible to the RDP user even when
            # the relay itself runs as SYSTEM in a non-interactive session.
            code = ctypes.windll.shell32.SHGetFolderPathW(None, 0x19, None, 0, buffer)
            summary = install(Path(buffer.value)) if code == 0 else "DESKTOP=LOOKUP_FAILED;CHANGED=0"
        except (OSError, ValueError):
            summary = "DESKTOP=LOOKUP_FAILED;CHANGED=0"
    print(json.dumps({"status": "ok", "summary": summary}))


if __name__ == "__main__":
    main()
