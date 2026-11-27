#!/usr/bin/env python3
"""Fresh-machine GGUF recovery test. No production paths or external services.

Run on a separately controlled recovery machine. The model process MUST enter
a new Linux network namespace; failure to create it fails the test closed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

from nasu_verify_restored_snapshot import verify

MODEL_NAME = "Qwen3-1.7B-Q8_0.gguf"
MAX_MEMBERS = 500
MAX_RUNTIME_BYTES = 512 * 1024 * 1024


def exercise(restored, runner=subprocess.run, isolator=None):
    restored = Path(restored).resolve(strict=True)
    report = verify(restored)
    if not report["model_present"]:
        raise ValueError("Backup lacks a verified local model and runtime")
    model = restored / MODEL_NAME
    runtime = restored / "llama-runtime.tar.gz"
    if model.is_symlink() or runtime.is_symlink():
        raise ValueError("Refusing symlinked recovery content")
    isolation_bin = isolator or shutil.which("unshare")
    if not isolation_bin:
        raise RuntimeError("Network namespace utility unavailable: NO OFFLINE PASS")
    with tempfile.TemporaryDirectory(prefix="nasu-recover-") as work:
        workspace = Path(work)
        with tarfile.open(runtime, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_MEMBERS or sum(m.size for m in members) > MAX_RUNTIME_BYTES:
                raise ValueError("Runtime archive exceeds recovery bounds")
            for member in members:
                p = PurePosixPath(member.name)
                if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "llama-bin":
                    raise ValueError("Unsafe runtime archive path")
                if member.isdev() or member.isfifo():
                    raise ValueError("Unexpected special runtime archive file")
            # Python 3.12+ data filter rejects escaping links and unsafe metadata.
            archive.extractall(workspace, filter="data")
        cli = workspace / "llama-bin" / "llama-cli"
        if not cli.is_file() or cli.is_symlink() or not os.access(cli, os.X_OK):
            raise ValueError("Recovered llama-cli not executable")
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": work,
            "LANG": "C.UTF-8",
            "LD_LIBRARY_PATH": str(workspace / "llama-bin"),
        }
        command = [
            isolation_bin, "--net", "--fork", "--",
            str(cli), "--model", str(model), "--threads", "2",
            "--ctx-size", "1024", "--single-turn", "--no-display-prompt",
            "--n-predict", "80",
            "--prompt", "/no_think Explain in one sentence why a backup must be restored to test it.",
        ]
        outcome = runner(command, cwd=work, env=env, text=True,
                         capture_output=True, timeout=300, check=False)
        if outcome.returncode != 0 or len(outcome.stdout.strip()) < 12:
            raise RuntimeError("Network-isolated model inference failed or returned empty text")
        output_hash = hashlib.sha256(outcome.stdout.encode("utf-8")).hexdigest()
    return {
        "status": "offline_model_recovery_smoke_pass",
        "model_process_network": "isolated_linux_namespace",
        "output_sha256": output_hash,
        "independent_machine": "operator_attestation_required",
        "backups_verified": report["file_count"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("restored_snapshot_dir", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(exercise(args.restored_snapshot_dir), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_class": type(exc).__name__}),
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
