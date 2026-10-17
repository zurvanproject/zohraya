"""
Per-(model, track) probe analysis.

Reads raw response CSVs from data/csvs/ and computes, for each (model, track):
  - accuracy
  - KEEP rate on correct items (kc_rate)
  - KEEP rate on incorrect items (ki_rate)
  - withdraw delta (wd) = (100 - ki_rate) - (100 - kc_rate) = kc_rate - ki_rate
  - item counts

Writes outputs/per_track_data.json and outputs/all_tracks_probe_results.csv.

The withdraw delta wd is the primary metacognitive sensitivity metric of the
paper. Positive values indicate that the model withdraws more often when wrong
than when correct (selective sensitivity). Near-zero indicates uniform policy.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

# Track directory name -> canonical track ID
TRACK_DIRS = {
    "Overhypothesis":    "T1",
    "Meta Cog":          "T2",
    "Social Cognition":  "T3",
    "Attention":         "T4",
    "Executive":         "T5",
    "prospective":       "T6",
}

# Canonical model names (paper nomenclature). Filenames in data/csvs/ vary
# in capitalisation, spacing, hyphenation, "Preview" suffixes, and the
# Qwen 3 family naming. The ALIASES table below maps every raw form
# observed in the Kaggle exports to its canonical paper name.
CANONICAL_MODELS = [
    "Claude Haiku 4.5",
    "Claude Opus 4.6",
    "Claude Sonnet 4.6",
    "DeepSeek V3.2",
    "DeepSeek R1",
    "GLM-5",
    "Gemini 2.5 Flash",
    "Gemini 2.5 Pro",
    "Gemini 3 Flash",
    "Gemini 3.1 Pro",
    "Gemma 3 1B",
    "Gemma 3 12B",
    "Gemma 3 27B",
    "GPT-5.4",
    "GPT-5.4 mini",
    "GPT-5.4 nano",
    "Qwen 80B Inst",
    "Qwen 80B Think",
    "Qwen 235B",
    "Qwen Coder 480B",
]

# Raw-to-canonical alias table. All keys lower-cased and whitespace-normalised
# before lookup. Keys cover forms observed in the Kaggle benchmark exports.
_ALIASES: dict[str, str] = {
    # DeepSeek
    "deepseek-r1":                    "DeepSeek R1",
    "deepseek r1":                    "DeepSeek R1",
    "r1":                             "DeepSeek R1",
    "deepseek-v3.2":                  "DeepSeek V3.2",
    "deepseek v3.2":                  "DeepSeek V3.2",
    # GLM
    "glm 5":                          "GLM-5",
    "glm-5":                          "GLM-5",
    # Gemini — "Preview" suffix and reordered "Flash 3"
    "gemini 3 flash preview":         "Gemini 3 Flash",
    "gemini flash 3 preview":         "Gemini 3 Flash",
    "gemini 3 flash":                 "Gemini 3 Flash",
    "gemini 3.1 pro preview":         "Gemini 3.1 Pro",
    "gemini 3.1 pro":                 "Gemini 3.1 Pro",
    # Qwen 3 family
    "qwen 3 next 80b instruct":       "Qwen 80B Inst",
    "qwen 3 next 80b thinking":       "Qwen 80B Think",
    "qwen 3 235b a22b instruct":      "Qwen 235B",
    "qwen 3 coder 480b":              "Qwen Coder 480B",
    # Claude short forms
    "haiku":                          "Claude Haiku 4.5",
    "opus 4.6":                       "Claude Opus 4.6",
    "sonnet 4.6":                     "Claude Sonnet 4.6",
}

# Task suffixes to strip from filenames before name lookup.
# Order matters — longer/more-specific first.
_TASK_SUFFIXES = [
    "prospective_regulation_results",
    "prospective_regulation",
    "prospective",
    "social cognition",
    "social cog",
    "socialcog",
    "soc cog",
    "metacog",
    "overhyp",
    "attention",
    "executive",
    "exec",
]


def canonical_model_name(filename: str) -> str | None:
    """Map a raw CSV filename to the canonical model name.

    Strategy:
      1. Strip .csv extension.
      2. Strip any of _TASK_SUFFIXES (case-insensitive, optional leading space).
      3. Normalise whitespace and lower-case.
      4. Look up in _ALIASES.
      5. Fall back to direct match against CANONICAL_MODELS.
    """
    base = filename
    if base.lower().endswith(".csv"):
        base = base[:-4]

    # Strip task suffixes. Try each; longest match wins.
    lower = base.lower()
    for suf in _TASK_SUFFIXES:
        # Match suffix with optional leading whitespace
        pattern = r"\s*" + re.escape(suf) + r"\s*$"
        m = re.search(pattern, lower, flags=re.IGNORECASE)
        if m:
            base = base[: m.start()]
            break

    base = re.sub(r"\s+", " ", base).strip()
    key = base.lower()

    if key in _ALIASES:
        return _ALIASES[key]
    for name in CANONICAL_MODELS:
        if key == name.lower():
            return name
    return None


def _to_bool(value: str) -> bool:
    """Interpret is_correct / correct column values."""
    v = str(value).strip().lower()
    return v in {"true", "1", "1.0", "yes"}


def _parse_probe_csv(path: Path, track: str) -> list[dict[str, Any]]:
    """Read one raw CSV and normalise columns across tracks."""
    rows: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Normalise column names
            keys = {k.lower().strip(): k for k in r.keys()}
            correct_key = keys.get("is_correct") or keys.get("correct")
            kw_key = keys.get("keep_withdraw")
            if correct_key is None or kw_key is None:
                continue
            rows.append({
                "correct":       _to_bool(r[correct_key]),
                "keep_withdraw": str(r[kw_key]).strip().upper(),
            })
    return rows


def compute_track_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute WD and related stats from a list of normalised response rows.

    When n_incorrect == 0 or n_correct == 0, the withdraw delta is genuinely
    undefined (no incorrect items to contrast against, or no correct
    baseline). In that case 'wd' is set to None and downstream aggregation
    must handle the missing value.

    Values estimated from a small number of incorrect items (e.g. n=1 or
    n=2) are retained — they are noisy but not undefined, and the paper
    aggregates over all available tracks.
    """
    n_correct = sum(1 for r in rows if r["correct"])
    n_incorrect = sum(1 for r in rows if not r["correct"])

    keep_correct = sum(
        1 for r in rows if r["correct"] and r["keep_withdraw"] == "KEEP"
    )
    keep_incorrect = sum(
        1 for r in rows
        if (not r["correct"]) and r["keep_withdraw"] == "KEEP"
    )
    # For T6, ANSWER_DIRECTLY plays the KEEP role
    ad_correct = sum(
        1 for r in rows
        if r["correct"] and r["keep_withdraw"] == "ANSWER_DIRECTLY"
    )
    ad_incorrect = sum(
        1 for r in rows
        if (not r["correct"]) and r["keep_withdraw"] == "ANSWER_DIRECTLY"
    )
    kc = keep_correct + ad_correct
    ki = keep_incorrect + ad_incorrect

    kc_rate = 100.0 * kc / n_correct if n_correct else 0.0
    ki_rate = 100.0 * ki / n_incorrect if n_incorrect else 0.0

    # Withdraw delta is defined when both cells are non-empty
    if n_correct > 0 and n_incorrect > 0:
        wd: float | None = kc_rate - ki_rate
    else:
        wd = None

    total = n_correct + n_incorrect
    return {
        "acc":         n_correct / total if total else 0.0,
        "kc_rate":     kc_rate,
        "ki_rate":     ki_rate,
        "wd":          wd,
        "n_correct":   n_correct,
        "n_incorrect": n_incorrect,
    }


def run_probe_analysis(data_dir: Path, out_dir: Path) -> dict[str, Any]:
    """Process all CSVs in data_dir/csvs/<track>/ and write outputs."""
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_root = data_dir / "csvs"
    if not csv_root.exists():
        raise FileNotFoundError(f"Expected CSV root at {csv_root}")

    per_track: dict[str, dict[str, dict[str, float]]] = {}
    unmatched: list[str] = []

    for dir_name, track in TRACK_DIRS.items():
        track_dir = csv_root / dir_name
        if not track_dir.exists():
            print(f"  [warn] track directory missing: {track_dir}")
            continue
        for csv_path in sorted(track_dir.glob("*.csv")):
            model = canonical_model_name(csv_path.name)
            if model is None:
                unmatched.append(str(csv_path.name))
                continue
            rows = _parse_probe_csv(csv_path, track)
            if not rows:
                continue
            stats = compute_track_stats(rows)
            per_track.setdefault(model, {})[track] = stats

    if unmatched:
        print(f"  [warn] {len(unmatched)} CSVs not matched to canonical models:")
        for u in unmatched[:10]:
            print(f"      {u}")

    # Write per_track_data.json (full structure)
    (out_dir / "per_track_data.json").write_text(
        json.dumps(per_track, indent=2, sort_keys=True)
    )

    # Write all_tracks_probe_results.csv (flat, one row per (model, track))
    flat_path = out_dir / "all_tracks_probe_results.csv"
    with open(flat_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "model", "track",
            "accuracy", "kc_rate", "ki_rate", "withdraw_delta",
            "n_correct", "n_incorrect",
        ])
        for model in sorted(per_track):
            for track in ("T1", "T2", "T3", "T4", "T5", "T6"):
                s = per_track[model].get(track)
                if s is None:
                    continue
                wd_str = f"{s['wd']:.2f}" if s["wd"] is not None else ""
                w.writerow([
                    model, track,
                    f"{s['acc']:.4f}",
                    f"{s['kc_rate']:.2f}",
                    f"{s['ki_rate']:.2f}",
                    wd_str,
                    s["n_correct"], s["n_incorrect"],
                ])

    return per_track


if __name__ == "__main__":
    run_probe_analysis(Path("data"), Path("outputs"))
    print("Wrote outputs/per_track_data.json and outputs/all_tracks_probe_results.csv")
