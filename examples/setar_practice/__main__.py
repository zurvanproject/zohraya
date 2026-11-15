"""Run only the explicitly selected local setar operation."""
import argparse
import json
from pathlib import Path
from .skill import SetarSkill


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'evaluate', 'practice'])
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--episodes', type=int, default=60)
    parser.add_argument('--seed', type=int, default=4110000)
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument('--realtime', action='store_true')
    timing.add_argument('--accelerated', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'practice' and (args.output_dir is None or not (args.realtime or args.accelerated)):
        parser.error('practice requires a fresh --output-dir and explicit --realtime or --accelerated')
    if args.command != 'practice' and (args.realtime or args.accelerated or args.output_dir is not None):
        parser.error('scheduling/output-directory options are for practice only')
    try:
        skill = SetarSkill(args.checkpoint)
        if args.command == 'status':
            result = skill.status()
        elif args.command == 'evaluate':
            result = skill.evaluate()
        else:
            result = skill.practice(args.output_dir, episodes=args.episodes, realtime=args.realtime, seed=args.seed)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
