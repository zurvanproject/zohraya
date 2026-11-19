"""Local fault-injection control: count original byte-recovery operations for one claim."""
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from .evidence_lineage import decide_claim


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _execute(run_dir, label, *, damage_recovery_source=False):
    event_dir = run_dir / label
    event_dir.mkdir()
    source = event_dir / "reference.bin"
    backup = event_dir / "backup.bin"
    target = event_dir / "working.bin"
    # Each event constructs its own reproducible payload and uses its own files.
    source.write_bytes(hashlib.shake_256(label.encode("ascii")).digest(256))
    expected = _digest(source)
    shutil.copyfile(source, backup)
    shutil.copyfile(source, target)
    with target.open("r+b") as handle:
        first = handle.read(1)[0]
        handle.seek(0)
        handle.write(bytes([first ^ 1]))
    corrupted = _digest(target)
    if corrupted == expected:
        raise RuntimeError("Fault injection did not alter the target.")
    if damage_recovery_source:
        with backup.open("ab") as handle:
            handle.write(b"bad backup")
    shutil.copyfile(backup, target)
    recovered = _digest(target)
    event_id = uuid.uuid4().hex
    row = {
        "receipt_id": f"execute-{event_id}", "root_id": event_id, "kind": "execution",
        "scope": "public", "verified": True,
        "verdict": "support" if recovered == expected else "oppose",
    }
    evidence = {"label": label, "expected_sha256": expected, "damaged_sha256": corrupted,
                "after_recovery_sha256": recovered, "observation": row}
    receipt = event_dir / "receipt.json"
    receipt.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    return receipt


def run_file_control():
    """Run three primary operations and construct two derivative views of the first."""
    with tempfile.TemporaryDirectory() as temp:
        run_dir = Path(temp)
        receipts = [_execute(run_dir, "first"), _execute(run_dir, "second"),
                    _execute(run_dir, "bad-backup", damage_recovery_source=True)]
        traces = [json.loads(path.read_text(encoding="utf-8")) for path in receipts]
        first, second, failed = [trace["observation"] for trace in traces]
        mirror = run_dir / "mirror.json"
        shutil.copyfile(receipts[0], mirror)
        if _digest(receipts[0]) != _digest(mirror):
            raise RuntimeError("Mirrored receipt differs from the primary receipt.")
        derivatives = []
        for kind, saved in (("replay", receipts[0]), ("mirror", mirror)):
            saved_row = json.loads(saved.read_text(encoding="utf-8"))["observation"]
            derivatives.append(dict(saved_row, kind=kind,
                                    receipt_id=f"{kind}-{saved_row['root_id']}"))
        return {
            "claim": "Copying the recovery source restored the expected bytes.",
            "traces": traces,
            "derivative_observations": derivatives,
            "one_with_derivatives": decide_claim([first, *derivatives]),
            "two_primary_successes": decide_claim([first, second]),
            "with_contrary_failure": decide_claim([first, second, failed]),
        }


if __name__ == "__main__":
    print(json.dumps(run_file_control(), indent=2))
