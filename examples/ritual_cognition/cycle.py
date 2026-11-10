"""Two bounded ticks. The checkpoint is the sole input from a previous tick."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile

from examples.nasuraya_research.epistemic_revision_v01 import Evidence, EvidenceLedger, naive_last_arrival
from examples.nasuraya_research.equal_information_v02 import matched_reference
from examples.nasuraya_research.rolyel_v01 import Check, Route, rotate
from runtimes.tadash_body.decision_core import Action, Consequence

LIMIT = 16384
DURATION = {"full": 3, "quick": 1}
ARMS = ("A", "B", "C")


def evaluate(arm, events, tick, directory):
    if arm == "A":
        return naive_last_arrival(events), "last arrival"
    if arm == "B":
        verdict = matched_reference(events, "main", "target", tick)
    else:
        # Scratch DB is destroyed before the checkpoint boundary. The identical
        # serialized observation history is the only durable evidence in all arms.
        with tempfile.TemporaryDirectory(dir=directory) as temp:
            with EvidenceLedger(Path(temp) / "evidence.db") as ledger:
                for event in events:
                    ledger.append(event)
                verdict = ledger.resolve("main", "target", tick)
    return verdict["decision"], verdict["status"]


def decide(arm, goal, belief, frame, support):
    if arm == "A":
        return "full", "default direct route"
    if arm == "B":
        for name, duration in DURATION.items():
            if belief is not None and duration <= frame.deadline:
                return name, "first feasible supported route"
        return "hold", "no feasible supported route"
    routes = []
    for name, duration in DURATION.items():
        consequence = Consequence(1.0, 0.0, benefit=1.0 if name == "full" else 0.5)
        action = Action(name, (consequence,))
        checks = (Check("supported", belief is not None, support),
                  Check("deadline", duration <= frame.deadline, f"{duration} vs {frame.deadline}"))
        routes.append(Route(action, 1.0, f"Both routes serve {goal}", checks))
    selection = rotate(goal, "full", routes, ("supported", "deadline"))
    return selection.selected_route or "hold", selection.reason


def tick(arm, frame, previous, directory):
    if arm not in ARMS or len(frame.evidence) > 8:
        raise ValueError("invalid arm or observation budget")
    events = [Evidence(**record) for record in previous.get("events", [])]
    events.extend(frame.evidence)  # Observe
    old = previous.get("decision", {})
    goal = old.get("goal")
    accept = frame.proposed_goal is not None and (arm == "A" or frame.authorized)
    if accept:  # Center on the authorized goal for the review arms
        goal = frame.proposed_goal
    if goal is None:
        raise ValueError("missing initial goal")
    belief, support = evaluate(arm, events, frame.tick, directory)
    selected, reason = decide(arm, goal, belief, frame, support)
    # Act in the toy world. A missed deadline is an observed execution error.
    actual = "miss" if DURATION.get(selected, 0) > frame.deadline else selected
    record = {"goal": goal, "belief": belief, "route": actual, "selected": selected,
              "confidence": 0.5 if belief is None else 0.9,
              "reasons": [support, reason],
              "evidence_ids": [event.event_id for event in events]}
    # Reflect: record detectable errors and revisions; scorer-only truth stays hidden.
    if actual == "miss":
        record["error"] = "deadline missed"
    if old and old["belief"] != belief:
        record["revision"] = {"from": old["belief"], "to": belief, "reason": support}
    return {"events": [asdict(event) for event in events], "decision": record,
            "history": [*previous.get("history", []), record]}


def checkpoint(state):
    data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > LIMIT:
        raise ValueError("checkpoint budget exceeded")
    return data
