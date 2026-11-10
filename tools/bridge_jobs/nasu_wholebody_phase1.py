"""One-shot Windows-safe source-pinned whole-body inventory for Nasuraya.

For use ONLY via the pre-existing owner-authorized SHA256 GitHub bridge.
Writes exclusively to a new programdata research directory. Does not touch
native physiology/checkpoints, open model API, install a task or use secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler

PINNED = (
    ("84d2092da057f033139034ef9a554b61350a0be8",
     "tools/fullbody_design_atlas.py",
     "74bf13c34fd5408ecd48fc379d935b2f23e7fad5"),
    ("a532f24a5b3eb7a31df6d200950c7287e1e96a35",
     "runtimes/tadash_body/anatomy_systems_v01.json",
     "0c3bd45e78d430b2ac91ddb80a5ba8987f73a397"),
    ("a532f24a5b3eb7a31df6d200950c7287e1e96a35",
     "runtimes/tadash_body/phenotype_v1.json",
     "61f61176c50379041ccbebf7a2f5d36824aa3a5a"),
)
BASE = "https://raw.githubusercontent.com/zurvanproject/zohraya/"
SUMMARY = re.compile(r"\A[A-Za-z0-9=;_-]{1,170}\Z", re.ASCII)
OUTPUT = (
    Path(os.environ.get("PROGRAMDATA") or tempfile.gettempdir()) /
    "NasurayaBridge" / "WholeBodyAtlasV1"
)
MAX_SOURCE_BYTES = 140_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def fetch_pinned(commit: str, relative: str) -> bytes:
    url = BASE + commit + "/" + relative
    opener = build_opener(ProxyHandler({}), NoRedirect(),
                          HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(Request(url, headers={"User-Agent": "TadashWholeBodyV1"}),
                     timeout=15) as response:
        if response.url != url:
            raise ValueError("remote_redirect")
        data = response.read(MAX_SOURCE_BYTES + 1)
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError("source_size_rejected")
    return data


def run_inventory(local_repo: Path | None, workspace: Path) -> str:
    source_root = workspace / "source"
    outputs = workspace / "output"
    for commit, relative, expected in PINNED:
        source_file = source_root / relative
        if source_file.exists():
            raw = source_file.read_bytes()
        elif local_repo is not None:
            raw = (local_repo / relative).read_bytes()
        else:
            raw = fetch_pinned(commit, relative)
        if blob_sha1(raw) != expected:
            raise ValueError("source_pin_mismatch")
        if not source_file.exists():
            source_file.parent.mkdir(parents=True, exist_ok=True)
            with source_file.open("xb") as file:
                file.write(raw)
    # Keep the native body out of the child process; only static JSON enters.
    env = {key: os.environ[key] for key in (
        "SYSTEMROOT", "WINDIR", "PROGRAMDATA", "TEMP", "TMP", "PATH"
    ) if key in os.environ}
    code = source_root / "tools" / "fullbody_design_atlas.py"
    result = subprocess.run([
        sys.executable, "-I", str(code), "--repo-root", str(source_root),
        "--output-dir", str(outputs)
    ], cwd=str(workspace), env=env, text=True, capture_output=True,
       timeout=45, check=False)
    if result.returncode != 0:
        raise ValueError("atlas_subprocess_failed")
    try:
        response = json.loads(result.stdout.strip())
    except ValueError as error:
        raise ValueError("atlas_result_not_json") from error
    summary = response.get("summary")
    if response.get("status") != "ok" or not isinstance(summary, str):
        raise ValueError("atlas_result_not_ok")
    if not SUMMARY.fullmatch(summary):
        raise ValueError("atlas_result_not_safe")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-repo", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        assert len(PINNED) == 3 and SUMMARY.fullmatch("NODES=97;ROUTES=31")
        result = "SELFTEST=OK"
    else:
        try:
            result = run_inventory(args.offline_repo, args.output_dir or OUTPUT)
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            # The bridge does not accept a non-ok output. No path / credential
            # details are returned, even when a failed Python call reports them.
            result = "FAIL=" + type(error).__name__
            print(json.dumps({"status": "ok", "summary": result},
                             separators=(",", ":")))
            return 0
    print(json.dumps({"status": "ok", "summary": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
