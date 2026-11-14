"""Read-only connector to the EXISTING frozen self-knowledge receipts.

The PR #94 evidence is forecasting performance in two synthetic fixtures.
It is not evidence that all HOT/PP requirements or phenomenal consciousness
have been met. This module makes no new trial or inference of experience.
"""
import json
from pathlib import Path


DEFAULT_RECEIPT = (Path(__file__).resolve().parents[2] /
                   "docs/evidence/self-knowledge-v01/summary.json")


def prior_forecasting_receipt(path=DEFAULT_RECEIPT):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if (record.get("validation_passed") is not True
            or not isinstance(record.get("validation_checks"), dict)
            or not all(v is True for v in record["validation_checks"].values())
            or record.get("model_api_calls") != 0
            or record.get("physical_actuator_calls") != 0
            or record.get("actual_native_cycles") != 64
            or record.get("training_receipts") != 40
            or record.get("holdout", {}).get("scored") != 24
            or record.get("holdout", {}).get("failed_or_unresolved") != 0
            or record.get("holdout", {}).get("observed_outcome_counts") !=
            {"walk": 6, "observe": 18, "protect": 0, "other": 0}):
        raise ValueError("prior evidence checks failed; no claims")
    h = record["holdout"]
    if not (isinstance(h.get("mean_brier"), (float,int)) and
            isinstance(h.get("mean_pooled_brier"), (float,int)) and
            0 <= h["mean_brier"] < h["mean_pooled_brier"] <= 2):
        raise ValueError("invalid prior metrics")
    return {
        "source": "docs/evidence/self-knowledge-v01/summary.json (PR #94)",
        "scope": "constructed temporal holdout; same two simulator fixture families",
        "train_receipts": 40, "test_receipts": 24,
        "contextual_brier": h["mean_brier"],
        "pooled_brier": h["mean_pooled_brier"],
        "relative_brier_reduction": (h["mean_pooled_brier"] - h["mean_brier"]) /
                                      h["mean_pooled_brier"],
        "status": "prior_functional_forecasting_only",
        "evidence_for_phenomenal_consciousness": "not established",
        "indicator_confirmation": "none: no independent structural/counterfactual audit",
    }
