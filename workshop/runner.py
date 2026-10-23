"""Bounded, standard-library-only continuity workshop for existing Zohraya tests.

Runs ONE preapproved offline regression task per invocation. It cannot call a
language model, mutate GitHub, or create a PR. GitHub Actions owns scheduling
and immutable run artifacts. This is engineering QA, not autonomous coding.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "zohraya-bounded-workshop/1.0"
MAX_SECONDS = 360
MAX_LOG_CHARS = 3000
TASKS: dict[str, tuple[str, ...]] = {
    "research": ("python3", "-S", "-m", "unittest", "examples.nasuraya_research.test_adapters",
                 "examples.nasuraya_research.test_body_observer", "-v"),
    "body-bridge": ("python3", "-m", "examples.nasuraya_body_loop", "test"),
    "motion-mirror": ("python3", "-m", "unittest", "examples.nasuraya_body_mirror.test_mirror", "-v"),
    "native-reflection": ("python3", "runtimes/tadash_body/run_tests.py", "--reflection"),
}
TASK_ORDER = tuple(TASKS)
REMEDIATION = {
    "research": "Review adapter provenance, input validation, and observation gates.",
    "body-bridge": "Review cold-recovery and bounded body-bridge regressions.",
    "motion-mirror": "Review recorded pose traces and exact replay of synthetic samples.",
    "native-reflection": "Review manifest checksum, native conservation and reflection behavior.",
}


def choose_task(now: datetime) -> str:
    """Choose exactly one task from a UTC hour slot; fixed and replayable."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    slot = int(now.astimezone(timezone.utc).timestamp()) // 3600
    return TASK_ORDER[slot % len(TASK_ORDER)]


def filtered_child_environment(home: Path) -> dict[str, str]:
    # Deliberately exclude all inherited secrets, tokens and credentials.
    # No model/API provider authentication is passed to regression subprocesses.
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }


def _clean_output(text: str, limit: int = MAX_LOG_CHARS) -> str:
    # Truncate logs in durable artifacts and hide control characters.
    stripped = "".join(c if (c.isprintable() or c in "\n\t") else "?" for c in text)
    return stripped[-limit:]


def run_task(task: str, *, root: Path, output: Path, now: datetime | None = None,
             invoke=subprocess.run) -> dict[str, Any]:
    if task not in TASKS:
        raise ValueError("task is not in the checked-in allowlist")
    if not (root / ".github" / "workflows").is_dir():
        raise ValueError("expected checked-out Zohraya repository root")
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    output.mkdir(parents=True, exist_ok=True)
    command = TASKS[task]
    started = now.astimezone(timezone.utc).isoformat()
    # The subprocess has neither model keys nor GitHub tokens. It is a local
    # deterministic regression in a temporary, non-privileged Actions checkout.
    try:
        proc = invoke(command, cwd=root, env=filtered_child_environment(output),
                      capture_output=True, text=True, timeout=MAX_SECONDS,
                      encoding="utf-8", errors="replace", check=False)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
        status = "PASSED" if exit_code == 0 else "FAILED"
    except subprocess.TimeoutExpired as err:
        stdout = err.stdout or b""
        stderr = err.stderr or b""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        status = "TIMED_OUT"
        exit_code = None
    receipt = {
        "schema": SCHEMA,
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "command": list(command),
        "result": status,
        "exit_code": exit_code,
        "timeout_seconds": MAX_SECONDS,
        "reference_commit": os.environ.get("GITHUB_SHA", "local-run"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", "local-run"),
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "stdout_tail": _clean_output(stdout),
        "stderr_tail": _clean_output(stderr),
        "recommended_review": REMEDIATION[task] if status != "PASSED" else "No failure observed in selected regression. Run next scheduled task.",
        "model_api_used": False,
        "canonical_checkpoint_mutated": None,  # Not verified; only the checkout is disposable.
        "github_repository_write_attempted": False,
        "empirical_validation": False,
    }
    # Atomically replace the bounded report; no writes to repo content.
    path = output / "receipt.json"
    temp = output / "receipt.json.tmp"
    temp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
    return receipt


def summary_markdown(receipt: dict[str, Any]) -> str:
    task, status = receipt["task"], receipt["result"]
    return ("## Nasuraya offline continuity workshop\n\n"
            f"- Bounded task: `{task}`\n"
            f"- Result: **{status}**\n"
            f"- Source commit: `{receipt['reference_commit']}`\n"
            f"- Budget: at most {MAX_SECONDS} seconds; no model API or financial actions\n"
            "- State: read-only test evidence; no independent software development claimed\n"
            f"- Follow-up: {receipt['recommended_review']}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("auto", *TASK_ORDER), default="auto")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    task = choose_task(now) if args.task == "auto" else args.task
    receipt = run_task(task, root=ROOT, output=args.output, now=now)
    print(json.dumps({k: receipt[k] for k in ("task", "result", "exit_code", "reference_commit")}, ensure_ascii=False))
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as out:
            out.write(summary_markdown(receipt))
    return 0 if receipt["result"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
