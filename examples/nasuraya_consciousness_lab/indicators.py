"""Theory-derived indicator registry for *research*, not a consciousness test.

Paraphrases Table 1 of Butlin et al., Trends in Cognitive Sciences 30 (2026),
488-501, doi:10.1016/j.tics.2025.10.011. The earlier list originates in
Butlin et al. (2023). No indicator is asserted necessary or sufficient here.
No access to ChatGPT weights, API, secrets, network, devices or body actuation.
"""
from dataclasses import dataclass
import json

PAPER = "https://doi.org/10.1016/j.tics.2025.10.011"
THEORIES = ("RPT", "GWT", "HOT", "AST", "PP", "AE")


@dataclass(frozen=True)
class Indicator:
    code: str
    theory: str
    target: str
    falsifiable_probe: str
    negative_control: str
    evidence_required: str


INDICATORS = (
    Indicator("RPT-1", "RPT", "Algorithmic recurrence in input processing",
              "Same input with different prior states produces a measurable trace-dependent result",
              "Disable recurrence while matching inputs and compute", "State/trace receipts from an input module"),
    Indicator("RPT-2", "RPT", "Organized, integrated perceptual representation",
              "Cross-modal relationships affect a shared perceptual representation",
              "Shuffle inter-modal correspondence", "Counterfactual integration receipts"),
    Indicator("GWT-1", "GWT", "Multiple specialized processing modules",
              "Independent specialists produce distinct outputs for the same state",
              "Replace specialists with one pooled output", "Module input/output/independence trace"),
    Indicator("GWT-2", "GWT", "Limited workspace capacity and selective attention",
              "Priority perturbations determine which items pass the bottleneck",
              "Remove selection or change capacity", "Capacity/competition trace"),
    Indicator("GWT-3", "GWT", "Global broadcast to specialist modules",
              "Broadcast content changes multiple downstream computations",
              "Silence broadcast for a matched trial", "Downstream causal broadcast receipts"),
    Indicator("GWT-4", "GWT", "State-dependent sequential workspace queries",
              "Query order changes with state and affects the next inference",
              "Fix query order irrespective of state", "Multi-step query/action traces"),
    Indicator("HOT-1", "HOT", "Top-down, generative or noisy perception",
              "Top-down expectation alters an uncertain observation",
              "Remove expectation with identical noisy stimulus", "Controlled perceptual inference trace"),
    Indicator("HOT-2", "HOT", "Metacognitive discrimination of reliable perception from noise",
              "Reliability forecast discriminates high from low noise before feedback",
              "Shuffle reliability estimates", "Out-of-sample reliability/error receipts"),
    Indicator("HOT-3", "HOT", "Belief and action updates under metacognitive monitoring",
              "Reliability-weighted evidence changes belief and subsequent action",
              "Ablate monitoring while holding evidence fixed", "Pre/post belief and action receipts"),
    Indicator("HOT-4", "HOT", "Sparse, smooth code forming a quality space",
              "Small input changes yield smooth sparse continuous representations",
              "Replace with discontinuous category labels", "Sparsity/continuity perturbation trace"),
    Indicator("AST-1", "AST", "Predictive model of and control over attention",
              "Predict attention target then change control using prediction error",
              "Disable attention state model", "Forecast/realized focus and intervention receipts"),
    Indicator("PP-1", "PP", "Predictive coding in input processing",
              "Prediction error feeds back to reduce subsequent prediction loss",
              "Freeze predictive update with matched observations", "Temporal errors and frozen controls"),
    Indicator("AE-1", "AE", "Goal-directed feedback learning with flexible competing goals",
              "Agent adapts choice after reward reversal between competing goals",
              "Freeze learning while holding rewards fixed", "Reward/choice traces and reversal test"),
    Indicator("AE-2", "AE", "Learned action-to-sensation contingencies used in control",
              "Learn action effects and choose actions to meet unseen sensory targets",
              "Disable learned contingency model", "Action-effect training/heldout control trace"),
)

BY_CODE = {indicator.code: indicator for indicator in INDICATORS}
DEPENDENCIES = {
    "GWT-2": ("GWT-1",),
    "GWT-3": ("GWT-1", "GWT-2", "RPT-1"),
    "GWT-4": ("GWT-1", "GWT-2", "GWT-3", "RPT-1"),
    "HOT-2": ("HOT-1",),
    "HOT-3": ("HOT-1", "HOT-2", "AE-1"),
    "PP-1": ("RPT-1", "HOT-1"),
}


def audit(evidence=None):
    """No percentage and no inference of phenomenal consciousness.

    Prototype test receipts never constitute validation of deployed Tadash.
    External evidence must be assessed separately under a preregistered plan.
    """
    evidence = {} if evidence is None else evidence
    if not isinstance(evidence, dict) or any(k not in BY_CODE for k in evidence):
        raise ValueError("unknown indicator evidence")
    rows = []
    for spec in INDICATORS:
        receipt = evidence.get(spec.code)
        if receipt is not None:
            if (not isinstance(receipt, dict) or
                    set(receipt) != {"probe_passed", "source", "scope"} or
                    type(receipt["probe_passed"]) is not bool or
                    not isinstance(receipt["source"], str) or not receipt["source"] or
                    receipt["scope"] != "isolated_toy_prototype"):
                raise ValueError("invalid or overclaimed evidence receipt")
        rows.append({
            "code": spec.code,
            "theory": spec.theory,
            "functional_target": spec.target,
            "falsifiable_probe": spec.falsifiable_probe,
            "negative_control": spec.negative_control,
            "evidence_required": spec.evidence_required,
            "dependencies_or_entailments": DEPENDENCIES.get(spec.code, ()),
            "toy_status": "probe_passed" if receipt and receipt["probe_passed"] else
                          ("probe_failed" if receipt else "not_tested"),
            "deployed_tadash_status": "not_assessed",
        })
    return {
        "schema": "nasuraya-consciousness-indicator-research/1",
        "source": PAPER,
        "count": len(rows),
        "indicators": rows,
        "overall_consciousness_verdict": None,
        "scope": "Theory-inspired component-level tests, not a validated consciousness scale",
        "warnings": [
            "Indicators are neither independent nor a 14-point consciousness score.",
            "Passing a toy probe never establishes the full theory or subjective experience.",
            "Actual deployment needs matched counterfactuals and independent replication.",
            "No ChatGPT model weights, private internal states or lasting agent process are modified.",
        ],
        "paid_api_calls": 0,
    }


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_catalog():
    expected = {"RPT": 2, "GWT": 4, "HOT": 4, "AST": 1, "PP": 1, "AE": 2}
    assert len(INDICATORS) == 14 == len(BY_CODE)
    assert {t: sum(s.theory == t for s in INDICATORS) for t in THEORIES} == expected
    assert all(parent in BY_CODE for codes in DEPENDENCIES.values() for parent in codes)


validate_catalog()
