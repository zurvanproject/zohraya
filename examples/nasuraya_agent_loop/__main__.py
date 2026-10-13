"""python -m examples.nasuraya_agent_loop --output-dir /tmp/nasuraya-run"""

import argparse
import json
from pathlib import Path

from .local import Journal, State, ToolHost, run_local, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Isolated synthetic Nasuraya/Tadash agent loop")
    parser.add_argument("--backend", choices=["offline", "agents-api"], default="offline")
    parser.add_argument("--mode", choices=["observe", "bounded"], default="bounded")
    parser.add_argument("--max-actions", type=int, default=12)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--model", help="Required for live API; no assumed account access")
    parser.add_argument("--output-dir", type=Path, help="New directory; refuses overwrite")
    parser.add_argument("--check-api", action="store_true", help="Check prerequisites without any API request")
    parser.add_argument("--prompt-api-key", action="store_true", help="Read key from a hidden terminal prompt")
    args = parser.parse_args(argv)
    if args.check_api:
        from .agents_api import check_api_environment
        result = check_api_environment()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready_for_live_run"] else 2
    if not args.output_dir:
        parser.error("--output-dir required for execution")
    if args.prompt_api_key and args.backend != "agents-api":
        parser.error("--prompt-api-key applies only to agents-api")
    if args.backend == "agents-api" and not args.model:
        parser.error("--model required for agents-api")
    if not 0 <= args.max_actions <= 100 or not 0 <= args.max_steps <= 100:
        parser.error("action/step limits must be 0..100")
    if not 1 <= args.max_calls <= 100 or not 1 <= args.timeout_seconds <= 300:
        parser.error("calls must be 1..100 and timeout 1..300 seconds")
    client = None
    if args.backend == "agents-api":
        from .agents_api import make_client
        try:
            client = make_client(prompt_api_key=args.prompt_api_key)
        except (ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    try:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        journal = Journal(args.output_dir / "events.jsonl")
        host = ToolHost(State(), journal, mode=args.mode, max_actions=args.max_actions)
        if client:
            from .agents_api import run_api
            result = run_api(host, client, model=args.model, max_calls=args.max_calls,
                             timeout_seconds=args.timeout_seconds, live_service=True)
        else:
            result = run_local(host, max_steps=args.max_steps)
        with (args.output_dir / "summary.json").open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        write_report(args.output_dir / "report.md", result, journal)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "completed" else 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
