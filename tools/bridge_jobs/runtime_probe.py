"""Minimal first job: no secrets or identifying machine data are read."""
import json
import platform
import sys

result = {
    "status": "ok",
    "summary": "PYTHON=" + platform.python_version() + "; ARCH=" + platform.machine().replace(" ", "_") + "; JOBS=enabled",
}
print(json.dumps(result, separators=(",", ":")))
