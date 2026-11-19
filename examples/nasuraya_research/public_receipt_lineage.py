"""Offline adapter for the ten public Issue 149 receipts cited by PR 169."""
import hashlib
import json
import re
from pathlib import Path

from .evidence_lineage import decide_claim

FIXTURE = Path(__file__).resolve().parents[2] / "docs/evidence/rule-transfer-lineage/receipts.json"
FIXTURE_SHA256 = "86dd396718f3f807c38b47c1e723300471103d4f44f33f1b7e96f44dff166486"
ISSUE = "https://github.com/zurvanproject/zohraya/issues/149#issuecomment-"

# The paired commands are execution/readback of a shared record. The action and
# qualifying conditions below come from the pinned bridge implementations, not
# the experiment's synthetic cue labels.
PAIRS = {
    "capture_public_episode": (
        "MEM", ("memory_capture", "SAVED"), ("memory_recall", "RECALLED"),
        {"TREE": "1", "CHECKS": "4/4"}),
    "wait_on_unchanged_thread": (
        "FOLLOW", ("memory_compare", "COMPARED"), ("memory_report", "RECOVERED"),
        {"NEXT": "WAIT", "WHY": "NO_CONTENT_CHANGE", "NEW": "0", "CHG": "0"}),
    "recheck_synthetic_failure": (
        "REFLECT", ("reflection_train", "TRAINED"), ("reflection_report", "RECOVERED"),
        {"SYNTH": "1", "BASE": "CACHED", "MEM": "RECHECK"}),
    "recover_after_injected_corruption": (
        "RECOVERY", ("recovery_run", "EXECUTED"), ("recovery_report", "RECOVERED"),
        {"FAULT": "INJECTED", "ORIG": "OK", "BASE": "FAIL/FAIL", "MEM": "FAIL/READY"}),
    "read_locally_after_verified_repair": (
        "REPAIR", ("repair_retest", "RUN"), ("repair_retest", "REPLAY"),
        {"PROBE": "FORCED", "BEFORE": "WEB", "BYTES": "WEB", "AFTER": "LOCAL",
         "COLD": "LOCAL", "LOCAL": "OK", "GET": "0"}),
}


def _fields(result):
    fields = {}
    if not result.startswith("OK "):
        raise ValueError("unsuccessful bridge receipt")
    for item in result[3:].split(";"):
        key, separator, value = item.partition("=")
        if separator != "=" or not value or key in fields:
            raise ValueError("invalid bridge result fields")
        fields[key] = value
    if not re.fullmatch(r"[0-9a-f]{16}", fields.get("SIG", "")):
        raise ValueError("missing or malformed record fingerprint")
    return fields


def _pairs(receipts):
    indexed = {}
    for receipt in receipts:
        if receipt["url"] != ISSUE + str(receipt["comment_id"]):
            raise ValueError("unexpected public receipt URL")
        fields = _fields(receipt["result"])
        for claim, (marker, first, second, conditions) in PAIRS.items():
            command_and_mode = (receipt["command"], fields.get(marker))
            for index, (command, mode) in enumerate((first, second)):
                if command_and_mode == ("moltbook_" + command, mode):
                    break
            else:
                continue
            key = (claim, index)
            if key in indexed or not conditions.items() <= fields.items():
                raise ValueError("duplicate receipt role or unmet claim conditions")
            indexed[key] = (receipt, fields)
            break
        else:
            raise ValueError("unrecognized bridge command or mode")
    if len(indexed) != 2 * len(PAIRS):
        raise ValueError("incomplete receipt pairs")
    return indexed


def audit(path=FIXTURE):
    """Return per-proposition counts, the underlying evidence rows and gate result."""
    # Git checkouts may translate LF to CRLF. Pin all remaining UTF-8 bytes.
    payload = Path(path).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(payload).hexdigest() != FIXTURE_SHA256:
        raise ValueError("public receipt snapshot checksum mismatch")
    receipts = json.loads(payload)["receipts"]
    pairs = _pairs(receipts)
    anchor = pairs["capture_public_episode", 0][1]["SIG"]
    if not anchor.startswith(pairs["wait_on_unchanged_thread", 0][1]["BASE"]):
        raise ValueError("follow-up is not anchored to the captured episode")

    # For THIS inspected corpus: recovery copies the stored observation from
    # the comparison; repair forks that recovery ledger and reuses its fetch.
    # This is the shared upstream experiment, not a hash of every copy's bytes.
    episode_root = "pr169:anchored-thread:" + anchor
    propositions = {}
    signatures = set()
    for claim in PAIRS:
        first, second = (pairs[claim, i] for i in (0, 1))
        signature = first[1]["SIG"]
        if signature != second[1]["SIG"] or signature in signatures:
            raise ValueError("execution/readback record fingerprint mismatch or reuse")
        signatures.add(signature)
        synthetic = claim == "recheck_synthetic_failure"
        root_id = "synthetic-feedback:" + signature if synthetic else episode_root
        rows = []
        for kind, (receipt, _) in zip(("execution", "replay"), (first, second)):
            rows.append({
                "receipt_id": receipt["url"], "root_id": root_id, "verdict": "support",
                "verified": True, "scope": "public", "kind": "synthetic" if synthetic else kind,
            })
        propositions[claim] = {
            "receipt_count": len(rows),
            "naive_url_support": len({row["receipt_id"] for row in rows}),
            "rows": rows,
            **decide_claim(rows),
        }
    return {"receipt_count": len(receipts), "signature_pair_count": len(signatures),
            "propositions": propositions}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
