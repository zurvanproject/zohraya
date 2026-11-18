#!/usr/bin/env python3
"""Verify a restored Nasuraya snapshot on an unrelated host, offline.

No source VPS, API, network, credentials, or production-path mutations needed.
Supply the exact directory containing the restored manifest.json.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import sys
import tarfile

MODEL_SHA = "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_cognitive_chain(path):
    """Independently recalculate every completed growth receipt's hash chain."""
    columns = ("slot", "stamp", "topic", "source_path", "source_sha",
               "fixed_result", "model_status", "proposal", "next_topic", "previous_sha")
    last = "0" * 64
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        rows = db.execute("""SELECT slot,stamp,topic,source_path,source_sha,
            fixed_result,model_status,proposal,next_topic,previous_sha,receipt_sha
            FROM cycles WHERE state='completed' ORDER BY slot""").fetchall()
        for row in rows:
            body = dict(zip(columns, row[:-1]))
            digest = hashlib.sha256(json.dumps(body, sort_keys=True,
                   ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
            if row[-2] != last or row[-1] != digest:
                raise ValueError("Modified cognitive growth receipt")
            last = row[-1]
    return len(rows)


def verify(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Restored directory missing or symlinked")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("Missing trusted restic manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") not in ("nasuraya-restic-offsite/2", "nasuraya-restic-offsite/3"):
        raise ValueError("Unexpected backup schema")
    files = manifest.get("files_sha256")
    required = {"awake.sqlite3", "continuity.sqlite3", "zohraya.bundle"}
    if not isinstance(files, dict) or not required.issubset(files):
        raise ValueError("Incomplete backup manifest")
    if manifest.get("credentials_included") is not False:
        raise ValueError("Unexpected secret material flag")
    for filename, checksum in files.items():
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("Unsafe name in manifest")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise ValueError("Invalid file checksum")
        target = root / filename
        if not target.is_file() or target.is_symlink() or digest(target) != checksum:
            raise ValueError("Missing, linked, or modified file: " + filename)
        if filename.endswith(".sqlite3"):
            with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Corrupt SQLite: " + filename)
        if filename.endswith(".tar.gz"):
            with tarfile.open(target, "r:gz") as archive:
                for item in archive.getmembers():
                    name = PurePosixPath(item.name)
                    if name.is_absolute() or ".." in name.parts or item.isdev() or item.isfifo():
                        raise ValueError("Unsafe archived path or device")
                    if item.issym() or item.islnk():
                        link = PurePosixPath(item.linkname)
                        if link.is_absolute() or ".." in link.parts:
                            raise ValueError("Unsafe archive symlink")
    if manifest.get("model_present"):
        if files.get("Qwen3-1.7B-Q8_0.gguf") != MODEL_SHA or "llama-runtime.tar.gz" not in files:
            raise ValueError("Model or offline binaries missing")
    if manifest.get("workload_archives_present") and "workload-imports.tar.gz" not in files:
        raise ValueError("Historical imports missing")
    if manifest.get("research_journal_present") and "research.sqlite3" not in files:
        raise ValueError("Offline research journal missing")
    if manifest.get("cognitive_journal_present"):
        if "cognitive-growth.sqlite3" not in files:
            raise ValueError("Cognitive growth journal missing")
        verify_cognitive_chain(root / "cognitive-growth.sqlite3")
    elif "cognitive-growth.sqlite3" in files:
        raise ValueError("Cognitive growth manifest flag missing")
    flag = manifest.get("ollama_qwen3_4b_recoverable")
    if type(flag) is not bool or (manifest["schema"].endswith("/3")) != flag:
        raise ValueError("Inconsistent Ollama model recovery manifest")
    if manifest.get("ollama_qwen3_4b_independent_smoke_pass", False) is not False:
        raise ValueError("Only a witnessed independent test can claim offline inference")
    from nasu_ollama_4b_recovery import ARTIFACTS, verify_bundle
    if flag:
        if not set(ARTIFACTS).issubset(files):
            raise ValueError("4B model or runtime missing from backup manifest")
        verify_bundle(root)
    elif set(ARTIFACTS).intersection(files):
        raise ValueError("Ollama assets present but manifest flag is false")
    result = subprocess.run(["git", "bundle", "list-heads", str(root / "zohraya.bundle")],
                            capture_output=True, check=False, timeout=15)
    if result.returncode or not result.stdout:
        raise ValueError("Git code bundle invalid")
    return {"status": "verified", "file_count": len(files),
            "model_present": bool(manifest.get("model_present")),
            "workload_archives_present": bool(manifest.get("workload_archives_present")),
            "research_journal_present": bool(manifest.get("research_journal_present")),
            "cognitive_journal_present": bool(manifest.get("cognitive_journal_present")),
            "ollama_qwen3_4b_recoverable": bool(flag),
            "independent_offline_smoke_pass": False,
            "sqlite_files": sum(name.endswith(".sqlite3") for name in files),
            "independent_host": "must_be_confirmed_by_operator"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("restored_snapshot_dir", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.restored_snapshot_dir), sort_keys=True))
    except BaseException as e:
        print(json.dumps({"status": "failed", "error_class": type(e).__name__}), file=sys.stderr)
        raise SystemExit(2)
