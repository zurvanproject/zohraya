"""Read only two known .url destinations; never launch or modify either file.

Public output contains only allowlisted classifications, sizes and encoding.
No arbitrary URL, icon path, file body, user identity or error detail is emitted.
"""
import codecs
import configparser
import ctypes
import io
import json
import os
from pathlib import Path

TARGETS = (("Nasuraya - Chat.url", "https://chatgpt.com/"),
           ("Nasuraya - Images.url", "https://chatgpt.com/images/"))


def classify(data, expected):
    if len(data) > 4096:
        return "OVERSIZE", "U", "U"
    encoding = "UTF8"
    try:
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            text = data.decode("utf-16")
            encoding = "UTF16"
        else:
            text = data.decode("utf-8-sig")
            if data.startswith(codecs.BOM_UTF8):
                encoding = "UTF8BOM"
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_file(io.StringIO(text))
        section = parser["InternetShortcut"]
        if parser.defaults():
            return "REVIEW", encoding, "U"
        url = section.get("url", "").strip()
        # Only the exact intended origin/path (plus optional trailing slash).
        result = "TARGET_OK" if url in (expected, expected.rstrip("/")) else "TARGET_OTHER"
        extras = sum(len(parser[s]) for s in parser.sections()) - 1
        return result, encoding, str(max(extras, 0))
    except (UnicodeError, configparser.Error, KeyError, ValueError):
        return "PARSE_FAIL", encoding, "U"


def check(desktop, name, url):
    path = desktop / name
    try:
        if path.is_symlink() or not path.is_file():
            return "NOT_REGULAR", "U", "U", "U"
        size = path.stat().st_size
        if size > 4096:
            return "OVERSIZE", str(size), "U", "U"
        with path.open("rb") as stream:
            data = stream.read(4097)
        result, encoding, extras = classify(data, url)
        return result, str(size), encoding, extras
    except OSError:
        return "READ_FAIL", "U", "U", "U"


def main():
    if os.name != "nt":
        return "LINKCHECK=SKIPPED;REASON=WINDOWS_REQUIRED"
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x19, None, 0, buffer) != 0:
        return "LINKCHECK=DESKTOP_UNKNOWN"
    a, b = [check(Path(buffer.value), name, url) for name, url in TARGETS]
    return ("CHAT=%s;IMAGES=%s;BYTES=%s/%s;ENC=%s/%s;EXTRA=%s/%s;LAUNCH=UNTESTED" %
            (a[0], b[0], a[1], b[1], a[2], b[2], a[3], b[3]))


if __name__ == "__main__":
    try:
        summary = main()
    except Exception:
        summary = "LINKCHECK=FAILED;DETAILS=WITHHELD"
    print(json.dumps({"status": "ok", "summary": summary}, separators=(",", ":")))
