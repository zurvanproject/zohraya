"""Read the finite research session's published aggregate on the owner's VPS."""
import json
import os
import time
from pathlib import Path

MODE = "status"


def main():
    root = Path(os.environ["PROGRAMDATA"]) / "NasurayaModelWorker/research-20261108"
    final = root / "final.json"
    target = final if final.exists() else root / "progress.json"
    if not target.exists():
        error=root/"last-error.json"
        if error.exists():
            return "EVENING=FAILED;ERROR="+json.loads(error.read_text(encoding="utf-8"))["error"][:45]
        return "EVENING=AWAITING_FIRST" if (root/"config.json").exists() else "EVENING=NOT_INSTALLED"
    data = json.loads(target.read_text(encoding="utf-8"))
    science = data["scientific"]
    age = max(0, int(time.time()-data["last_host_epoch"]))
    if MODE == "scientific":
        stats=science.get("context_results",{})
        # Read the highest tested cue-corruption level, on matched observations.
        try:
            key=max(stats,key=float)
            row=stats[key]
            clean=float(row["clean"])
            noisy=float(row["noisy"])
            drift=f";NOISE={float(key):.2f};CLEAN={clean:.4f};CUE={noisy:.4f}"
        except (KeyError,ValueError):
            drift=""
        return (f"SCI={data['state']};S={data['slots']};PULSEPOS={science['peak_grid_cells']};"
                f"CTRLPEAK={science['control_peak_count']};REVALGAIN={science['reversal_gain']:.5f}"+drift)
    health = data.get("latest_health") or {}
    return (f"EVENING={data['state']};S={data['slots']}/{data['expected']};PHYS={science['physiology_cases']};"
            f"CHOICES={science['heldout_choices']};REVTEST={science['reversal_trials']};"
            f"BAD={data['health_bad']};R={health.get('native_revision')};U={health.get('unresolved')};AGE={age};FULL={int(data['complete'])};END=2100TEHRAN")


if __name__=="__main__":
    try:
        summary=main()
    except Exception as exc:
        summary="EVENING=REPORT_FAILED;ERROR="+type(exc).__name__
    print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
