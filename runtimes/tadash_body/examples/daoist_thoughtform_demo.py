"""Demonstrate Daoist eight-rule-inspired lifecycle on synthetic fixtures only."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retained_extensions"))
from daoist_thoughtform_v01 import AgentSpec, ThoughtFormFixture


def run_demo() -> dict:
    spec = AgentSpec(
        shape_form="tadash_v2_fixture",
        goal_function="Review trustworthiness of simulated body load before planning.",
        name="nasuraya_thoughtform_v01",
        method_of_contact=("observation", "feedback", "interrupt", "stop"),
        home="tadash_research",
        feed_budget=10, lifespan_ticks=6,
        memory_slots=4, min_confidence=0.8,
    )
    agent = ThoughtFormFixture(spec)
    results = []
    results.append(agent.step({"kind": "observation", "source": "fixture",
                               "value": 0.87, "confidence": 0.95}, 0))
    results.append(agent.step({"kind": "interrupt"}, 1))
    with tempfile.TemporaryDirectory(prefix="tadash-thoughtform-") as work:
        path = Path(work) / "checkpoint.json"
        agent.save(path)
        agent = ThoughtFormFixture.load(path)
        results.append(agent.step({"kind": "observation", "source": "fixture",
                                   "value": 0.18, "confidence": 0.93}, 2))
        results.append(agent.step({"kind": "external_action", "command": "motor_move"}, 3))
        results.append(agent.step({"kind": "observation", "source": "unverified",
                                   "value": 0.8, "confidence": 0.99}, 4))
        results.append(agent.step({"kind": "observation", "source": "fixture",
                                   "value": 0.91, "confidence": 0.99}, 6))
        results.append(agent.step({"kind": "observation", "source": "fixture",
                                   "value": 0.91, "confidence": 0.99}, 7))
    return {
        "protocol": "offline_fixture_only",
        "source": "Jerry Alan Johnson, Daoist Exorcism, pp. 51-53, fig. 1.53",
        "input_events": len(results),
        "proposals": sum(x["decision"] == "propose" for x in results),
        "abstentions": sum(x["decision"] == "abstain" for x in results),
        "rejections": sum(x["decision"] == "reject" for x in results),
        "closed": agent.state["status"] == "closed",
        "close_reason": agent.state["closed_reason"],
        "work_used": agent.state["work_used"],
        "work_budget": spec.feed_budget,
        "audit_events_stored": len(agent.state["audit"]),
        "audit_limit": spec.memory_slots,
        "goal_unchanged_after_restart": agent.spec.goal_function == spec.goal_function,
        "actual_external_effects": 0,
        "claims_of_consciousness": False,
        "trace": results,
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2, sort_keys=True))
