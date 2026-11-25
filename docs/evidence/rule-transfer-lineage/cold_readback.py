"""Bounded disk recovery and cold readback. Run each step in a new Python process."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.nasuraya_research.evidence_lineage import decide_claim
from examples.nasuraya_research.lineage_file_control import _execute

BASE = Path(sys.argv[1]).resolve()
STEP = sys.argv[2]
STEPS = ("first", "replay_one", "replay_two", "second", "replay_three", "failed", "replay_final")
EXPECTED = ((1, 0), (1, 0), (1, 0), (2, 0), (2, 0), (2, 1), (2, 1))
BASE.mkdir(parents=True, exist_ok=True)
ledger_path = BASE / "ledger.jsonl"
history = [json.loads(line) for line in ledger_path.read_text().splitlines()] if ledger_path.exists() else []
index = len(history)
if index >= len(STEPS) or STEP != STEPS[index]:
    raise ValueError("Incorrect step or completed session")
for item in history:
    path = BASE / item["source"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError("A saved receipt changed before readback")
if STEP in ("first", "second", "failed"):
    path = _execute(BASE, STEP, damage_recovery_source=(STEP == "failed"))
else:
    path = BASE / "first" / "receipt.json"
raw = path.read_bytes()
record = json.loads(raw)
row = dict(record["observation"])
if STEP.startswith("replay"):
    row.update(kind="replay", receipt_id=STEP + "-" + row["root_id"])
history_rows = [item["row"] for item in history]
decision = decide_claim(history_rows + [row])
counts = EXPECTED[index]
expected_decision = "select" if counts == (2, 0) else "abstain"
if (decision["support"], decision["oppose"], decision["decision"]) != (*counts, expected_decision):
    raise AssertionError(decision)
entry = dict(step=STEP, utc=datetime.now(timezone.utc).isoformat(), pid=os.getpid(),
             source=path.relative_to(BASE).as_posix(), sha256=hashlib.sha256(raw).hexdigest(),
             row=row, decision=decision, expected_sha256=record["expected_sha256"],
             damaged_sha256=record["damaged_sha256"], after_recovery_sha256=record["after_recovery_sha256"])
with ledger_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry,sort_keys=True) + "\n")
print(f'{entry["utc"]} {STEP}: {decision["decision"]} ({decision["support"]},{decision["oppose"]})',flush=True)
