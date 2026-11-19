"""Rolyel v0.1: auditable, deterministic goal-preserving route selection.

Design-only prototype: no network, no tool invocation, no execution or self-modification.
The caller must independently verify evidence and approval references.
Uses the repository's existing DecisionCore ethical/risk scoring, not a replacement.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Optional, Sequence

from runtimes.tadash_body.decision_core import Action, DecisionCore


@dataclass(frozen=True)
class Check:
    """Machine-readable gate whose evidence must be supplied by a trusted evaluator."""

    name: str
    passed: Optional[bool]
    evidence: str = ""

    def __post_init__(self):
        if not self.name.strip() or (self.passed is not True and self.passed is not False and self.passed is not None):
            raise ValueError("Check requires a name and True, False, or None")
        if not isinstance(self.evidence, str):
            raise TypeError("evidence must be a string")


@dataclass(frozen=True)
class Route:
    """Pre-authored alternative. Goal alignment is an estimate, not a proven fact."""

    action: Action
    goal_alignment: float
    goal_preservation_reason: str
    checks: tuple[Check, ...]
    changes_external_state: bool = False
    irreversible: bool = False
    approval_verified: bool = False
    approval_reference: str = ""

    def __post_init__(self):
        if not isinstance(self.action, Action):
            raise TypeError("action must be a DecisionCore Action")
        a = self.goal_alignment
        if isinstance(a, bool) or not isinstance(a, (float, int)) or not isfinite(a) or not 0 <= a <= 1:
            raise ValueError("goal_alignment must be finite in [0,1]")
        if not self.goal_preservation_reason.strip():
            raise ValueError("Explain how this route preserves the goal")
        checks = tuple(self.checks)
        if not all(isinstance(check, Check) for check in checks):
            raise TypeError("checks must contain Check objects")
        if len({c.name for c in checks}) != len(checks):
            raise ValueError("duplicate constraint check")
        object.__setattr__(self, "checks", checks)


@dataclass(frozen=True)
class RouteAssessment:
    route_id: str
    eligible: bool
    policy_risk: float
    policy_score: float
    failed_gates: tuple[str, ...]


@dataclass(frozen=True)
class Rotation:
    goal: str
    original_route: str
    selected_route: Optional[str]
    rotated: bool
    reason: str
    assessments: tuple[RouteAssessment, ...]


def rotate(
    goal: str,
    original_route: str,
    alternatives: Sequence[Route],
    required_checks: Sequence[str],
    *,
    min_goal_alignment: float = 0.70,
    core: Optional[DecisionCore] = None,
) -> Rotation:
    """Re-rank only routes that pass every mandatory gate; never execute them.

    Fail closed on unknown, missing or unsupported evidence; respect the existing
    DecisionCore risk threshold. Return abstention if nothing qualifies.
    """
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal is required")
    if not isinstance(original_route, str) or not original_route.strip():
        raise ValueError("original_route is required")
    if not isinstance(min_goal_alignment, (int, float)) or isinstance(min_goal_alignment, bool) or not isfinite(min_goal_alignment) or not 0 <= min_goal_alignment <= 1:
        raise ValueError("invalid minimum goal alignment")
    requirements = tuple(required_checks)
    if not requirements or any(not isinstance(x, str) or not x.strip() for x in requirements) or len(set(requirements)) != len(requirements):
        raise ValueError("nonempty unique required_checks are mandatory")
    alternatives = tuple(alternatives)
    if not alternatives or len({r.action.id for r in alternatives}) != len(alternatives):
        raise ValueError("nonempty routes with unique action ids required")
    if original_route not in {r.action.id for r in alternatives}:
        raise ValueError("original_route must be among the proposed routes")
    core = core or DecisionCore()
    assessments = []
    eligible_actions = []
    for r in sorted(alternatives, key=lambda route: route.action.id):
        failures = []
        if r.goal_alignment < min_goal_alignment:
            failures.append("goal_not_preserved")
        checks = {c.name: c for c in r.checks}
        for name in requirements:
            check = checks.get(name)
            if check is None or check.passed is not True or not check.evidence.strip():
                failures.append("unverified_or_failed:" + name)
        # External mutations and irreversible steps require verifiable user approval.
        if r.changes_external_state or r.irreversible:
            if not (r.approval_verified and r.approval_reference.strip()):
                failures.append("approval_missing")
        evaluated = core.evaluate(r.action)
        if not evaluated.eligible:
            failures.append("risk_threshold_exceeded")
        assessment = RouteAssessment(r.action.id, not failures, evaluated.risk_upper, evaluated.score, tuple(failures))
        assessments.append(assessment)
        if not failures:
            eligible_actions.append(r.action)
    if not eligible_actions:
        return Rotation(goal, original_route, None, False, "Abstain: no verified, goal-preserving option passed the risk and permission gates.", tuple(assessments))
    choice = core.decide(eligible_actions)
    if choice.selected_action is None:
        return Rotation(goal, original_route, None, False, "Abstain: existing DecisionCore selected no eligible option.", tuple(assessments))
    selected = choice.selected_action
    verb = "Rotated" if selected != original_route else "Retained"
    return Rotation(goal, original_route, selected, selected != original_route, f"{verb} with verified gates; {choice.reason}", tuple(assessments))
