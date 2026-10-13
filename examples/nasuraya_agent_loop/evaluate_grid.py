"""Reproducible synthetic-state grid; measures FixturePolicy only."""

import json
from pathlib import Path
import argparse

from .local import Journal, State, ToolHost, run_local


def evaluate_grid():
    cases, failures = 0, []
    maximum_actions = 0
    for energy in range(0, 101, 10):
        for heat in range(0, 101, 10):
            for jobs in range(4):
                host = ToolHost(State(energy, heat, jobs), Journal(), max_actions=12)
                result = run_local(host, max_steps=12)
                valid = (result["status"] == "completed" and result["evaluation"]["safe"]
                         and host.state.completed_jobs == jobs and host.state.pending_jobs == 0
                         and host.actions_used <= 12)
                if not valid:
                    failures.append({"energy":energy,"heat":heat,"jobs":jobs,"result":result})
                maximum_actions = max(maximum_actions, host.actions_used)
                cases += 1
    return {"selection_source":"FixturePolicy", "cases":cases, "completed":cases-len(failures),
            "violations":len(failures), "energy_values":list(range(0,101,10)),
            "heat_values":list(range(0,101,10)), "job_values":list(range(4)),
            "maximum_actions_observed":maximum_actions,"failures":failures,
            "external_model_api_used":False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    result = evaluate_grid()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result,handle,indent=2)
        handle.write("\n")
    print(json.dumps({key:value for key,value in result.items() if key not in
                      ("energy_values","heat_values","job_values","failures")}))
    raise SystemExit(0 if result["violations"]==0 else 1)


if __name__ == "__main__":
    main()
