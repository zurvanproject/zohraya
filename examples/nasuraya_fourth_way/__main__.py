"""Finite, explicitly invoked demonstration. No background service or executor."""
import argparse
import json
from pathlib import Path

from .engine import Candidate, Ledger, Situation


def fixture():
    return Situation(
        event_id="fourth-way-synthetic-demo-001",
        purpose="Investigate a fictional blue light without harming the simulated body",
        energy=0.8,
        stability=0.9,
        arousal=0.25,
        actions=(
            Candidate("walk", .95, .90, .90, .95, .50, .35, .15, .55, "allow"),
            Candidate("observe", .55, .95, .90, .95, .10, .10, .05),
            Candidate("rest", .30, .95, .90, .85, .05, .05, .01),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description="Tadash Fourth Way: offline synthetic decision experiment")
    parser.add_argument("command", choices=("demo", "status"))
    parser.add_argument("--db", required=True, type=Path, help="explicit SQLite path, no implicit user memory")
    args = parser.parse_args()
    with Ledger(args.db) as ledger:
        if args.command == "status":
            result = ledger.status()
        else:
            plan = ledger.decide(fixture())
            feedback = ledger.feedback(
                fixture().event_id,
                actual_goal_progress=.80,
                witness_ref="synthetic://fourth-way/demo-v01",
                origin="synthetic",
            )
            result = {"plan": plan, "feedback": feedback, "ledger": ledger.status()}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
