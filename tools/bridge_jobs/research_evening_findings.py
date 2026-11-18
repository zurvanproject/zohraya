"""Read committed evening samples and return only bounded numeric findings."""
import json
import os
from pathlib import Path

SESSION = "nasuraya-model-worker/1"
SCHEMA = "tadash-research-20261108/1"


def read(path, limit):
    if path.stat().st_size > limit:
        raise ValueError("oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value, precision=0):
    if value is None:
        return "NA"
    if not isinstance(value, (int, float)) or not -100000 <= value <= 100000:
        raise ValueError("invalid metric")
    return format(value, "." + str(precision) + "f")


def findings(root):
    if not root.is_dir():
        return "FIND=NOT_INSTALLED"
    if read(root / "owner.json", 2048) != {"schema": SCHEMA}:
        raise ValueError("session mismatch")
    target = root / "final.json"
    if not target.exists():
        target = root / "progress.json"
    if not target.exists():
        return "FIND=AWAITING_FIRST"
    data = read(target, 65536)
    state = data["state"]
    count = data["slots"]
    science = data["scientific"]
    if state not in ("ACTIVE", "FINAL") or count != science["slots"] or not 0 <= count <= 48:
        return "FIND=INCOHERENT"
    if count == 0:
        return "FIND=NO_SAMPLES"
    seen = []
    for i in range(min(48, data["last_slot"]+1)):
        path = root / "results" / ("slot-%02d.json" % i)
        if path.is_file():
            row = read(path, 200000)
            if row["slot"] != i or row["schema"] != "nasuraya-evening-v1":
                return "FIND=INCOHERENT"
            p = row["physiology"]
            seen.append((p["input_intensity"], p["traces"], i))
    if len(seen) != count:
        return "FIND=INCOHERENT"
    # The representative intensity is the tested input closest to .95.
    # First passing coarse duration is a grid observation at 0.5s resolution.
    amp, traces, slot = min(seen, key=lambda v: (abs(v[0]-.95),v[2]))
    hit = min((t["cutoff_s"] for t in traces if t["peaks"] > 0), default=None)
    rev = science["reversal_results"]
    c = science["context_results"]
    error_rate = max(c, key=float)
    delta = c[error_rate]["clean"] - c[error_rate]["noisy"]
    summary = (f"FIND={state};S={count};AMP={fmt(amp,5)};HIT_S={fmt(hit,1)};"
               f"NOISE={fmt(float(error_rate),2)};LOSS={fmt(delta,4)};M8={fmt(rev['8']['median_blocks'],1)};"
               f"M96={fmt(rev['96']['median_blocks'],1)};SW512={fmt(rev['512']['switched'])}/"
               f"{fmt(rev['512']['trials'])};CTRL={fmt(science['control_peak_count'])}")
    if not summary.isascii() or len(summary)>180:
        raise ValueError("receipt format")
    return summary


if __name__ == "__main__":
    try:
        parent = Path(os.environ["PROGRAMDATA"]) / "NasurayaModelWorker"
        if read(parent / "owner.json", 2048) != {"schema": SESSION}:
            raise ValueError("worker mismatch")
        summary = findings(parent / "research-20261108")
    except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
        summary = "FIND=READ_FAILED;ERROR=" + type(exc).__name__
    print(json.dumps({"status": "ok", "summary": summary},separators=(",",":")))
