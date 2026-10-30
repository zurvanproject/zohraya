"""Time one real body audit and reject results that differ from the frozen reference."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter


AUDITS = {
    "single": ("rare_breath_audit", "cloud-breath-audit"),
    "multi": ("multistep_breath_audit", "multistep-breath"),
}
# These digest fields identify a particular execution. Keep all observed features,
# forecasts, feedback and actual actions in their original order for comparison.
RUN_FIELDS = {
    ("single", "forecasts.jsonl"): {"checkpoint", "fit_digest"},
    ("single", "receipts.jsonl"): {"checkpoint", "native_record_sha256"},
    ("multi", "forecasts.jsonl"): {"checkpoint"},
    ("multi", "receipts.jsonl"): {"before", "after", "native_record_sha256"},
}


def comparable_rows(path, run_fields):
    rows = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        for field in run_fields:
            del row[field]
        rows.append(row)
    return rows


def verify(audit, output):
    reference = Path("docs/evidence") / AUDITS[audit][1]
    for name in ("protocol.json", "summary.json"):
        if (output / name).read_bytes() != (reference / name).read_bytes():
            raise ValueError(f"{audit} {name} differs from the frozen reference")
    for name in ("forecasts.jsonl", "receipts.jsonl"):
        skip = RUN_FIELDS[audit, name]
        if comparable_rows(output / name, skip) != comparable_rows(reference / name, skip):
            raise ValueError(f"{audit} {name} contains different observations or outcomes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", choices=AUDITS)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    module = "examples.nasuraya_body_loop." + AUDITS[args.audit][0]
    start = perf_counter()
    subprocess.run([sys.executable, "-m", module, "--output-dir", str(args.output)], check=True)
    verify(args.audit, args.output)
    print("AUDIT_TIMING " + json.dumps({"audit": args.audit, "seconds": round(perf_counter() - start, 4)}))


if __name__ == "__main__":
    main()
