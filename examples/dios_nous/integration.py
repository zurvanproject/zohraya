"""Join synthetic evidence review and dissent safeguards without an executor."""
from __future__ import annotations

from pathlib import Path
from .cognition import (AdvisoryGoalPlanner, CognitiveSession, EvidenceEvent,
                        GoalOption, PreferenceProfile)
from .dissent import review_decision


def critical_review(session: CognitiveSession, *, scope: int, claim: int,
                    as_of: int, proposal: str, origin: str = "agent",
                    decision_signals: dict | None = None) -> dict:
    """Compare A/B fixture evidence, then retain all action/privacy boundaries.

    The observations are simulated. A SUPPORTED result is neither a real-world
    truth certificate nor permission to perform an action. Input validation of
    dissent signals precedes memory mutation, so malformed signals fail closed.
    """
    request = {"decision": {"origin": origin, "summary":
               f"Synthetic decision scope={scope} claim={claim} time={as_of} proposal={proposal}"},
               "decision_signals": {} if decision_signals is None else decision_signals}
    boundary = review_decision(request)
    evidence = session.assess(scope, claim, as_of, proposal, origin)
    if evidence["verdict"] == "DISSENT":
        request["observations"] = [{"concern": "contradictory_decision",
                                    "basis": "Latest synthetic evidence opposes the proposal",
                                    "provenance": "synthetic_test"}]
        boundary = review_decision(request)
    stance = (boundary["stance"] if boundary["reason_codes"] else evidence["verdict"])
    return {"schema": "dios.nous.synthetic-critical-review.v1",
            "stance": stance, "evidence_review": evidence, "boundary_review": boundary,
            "review_path": "inspect_source_roots_then_documented_review",
            "what_would_change_view": evidence["what_would_change_view"],
            "real_source_authentication": False, "execution_permitted": False,
            "external_actions_taken": 0}


def demo(directory: Path) -> dict:
    """Run a new disposable research episode, retaining inspectable local files."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("demo_requires_empty_directory")
    db, anchor = directory / "memory.sqlite", directory / "memory.anchor"
    with CognitiveSession(db, anchor) as session:
        session.append(EvidenceEvent(1, 1, 1, "A", 1, 1))
        first = critical_review(session, scope=1, claim=1, as_of=1, proposal="A")
        session.append(EvidenceEvent(2, 1, 1, "B", 2, 2))
        correction = critical_review(session, scope=1, claim=1, as_of=2, proposal="A")
        blocked = critical_review(session, scope=1, claim=1, as_of=2, proposal="B",
                                  origin="platform", decision_signals={
                                      "external_action_proposed": True,
                                      "explicit_authorization_present": True})
    with CognitiveSession(db, anchor) as recovered:
        resumed = critical_review(recovered, scope=1, claim=1, as_of=2, proposal="B")
    planner = AdvisoryGoalPlanner(directory / "goal.json", directory / "goal.anchor", 1)
    options = (GoalOption(1, 10, 9), GoalOption(2, 7, 1))
    goal = planner.plan(options, PreferenceProfile())
    stopped = planner.plan((), PreferenceProfile(), stop=True)
    return {"kind": "executed_offline_synthetic_demo", "initial": first,
            "self_correction": correction, "unverified_authorization": blocked,
            "recovered": resumed, "goal": goal, "stopped": stopped,
            "external_actions_taken": 0}
