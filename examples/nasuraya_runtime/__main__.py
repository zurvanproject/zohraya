"""Single entry point for a bounded local, restartable research session."""
import argparse
import json
from pathlib import Path

from examples.tadash_interoception.sensory import AfferentFrame, Stimulus, transduce
from .session import Session


def demo_frames(index, intensity):
    """Fixture-side labels stop here; the session receives only numeric frames."""
    raw = transduce(Stimulus('left_palm', intensity, .8, 12.,
                            'mechanical' if intensity else 'none', .025, .2), seed=183)
    return tuple(AfferentFrame(round(f.timestamp + index * 1.6, 8), f.values) for f in raw)


def write(path, value):
    path = Path(path)
    # An evidence file is never silently overwritten.
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def demo(directory, *, native=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    outcomes = {}
    cases = [('workshop', 'workshop', 'normal')]
    if native: cases += [('native', 'native', 'normal'), ('native_sleep', 'native', 'sleep')]
    for name, backend, fixture in cases:
        path = directory / name
        with Session.create(path, backend=backend, fixture=fixture, max_actions=4) as session:
            first = session.step('sample-0', demo_frames(0, 0), expected_revision=0)
            before_resume = session.snapshot()
        with Session(path) as session:
            after_resume = session.snapshot()
            receipts = [first]
            for i, intensity in enumerate((0, .95, 0) if fixture == 'normal' else (0, 0, 0), 1):
                receipts.append(session.step('sample-' + str(i), demo_frames(i, intensity), expected_revision=i))
            replay = session.step('sample-0', demo_frames(0, 0), expected_revision=0)
            end = session.snapshot()
            session.stop()
        with Session(path) as session:
            stopped = session.snapshot()
        write(directory / (name + '-snapshot.json'), end)
        outcomes[name] = {
            'receipts': receipts, 'resume_snapshot_equal': before_resume == after_resume,
            'duplicate_returned_original': replay == first,
            'actions_used': end['actions_used'], 'remaining_after_reopen': stopped['actions_remaining'],
            'stop_survives_reopen': stopped['stopped'] and stopped['dios']['goal']['selected_goal'] is None,
            'final_state_sha': end['snapshot_sha256'], 'event_tail': end['event_tail'],
            'visual_plan_options': len(end['visual_plan']['options']),
            'sensory_hypothesis_stance': end['dios']['sensory_hypothesis_review']['stance'],
            'body_clock': None if end['body'] is None else end['body']['clock'],
            'native_neural_ticks': None if end['body'] is None else end['body']['neural_ticks'],
            'capabilities': end['capabilities']}
    result = {'kind': 'executed_integration_contract_fixture_not_new_blind_benchmark',
              'scenarios': outcomes, 'external_actions_taken': 0,
              'subjective_experience_established': False}
    write(directory / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('--session', type=Path, required=True)
    create.add_argument('--id', default='nasuraya')
    create.add_argument('--backend', choices=['workshop', 'native'], default='workshop')
    create.add_argument('--max-actions', type=int, default=12)
    create.add_argument('--at-utc', default='2026-11-12T12:00:00+00:00')
    for name in ('step', 'snapshot', 'stop'):
        child = sub.add_parser(name)
        child.add_argument('--session', type=Path, required=True)
        child.add_argument('--output', type=Path)
        if name == 'step':
            child.add_argument('--frames', type=Path, required=True)
            child.add_argument('--event-id', required=True)
            child.add_argument('--revision', type=int, required=True)
    demo_parser = sub.add_parser('demo')
    demo_parser.add_argument('--output', type=Path, required=True)
    demo_parser.add_argument('--native', action='store_true')
    args = parser.parse_args()
    if args.command == 'demo':
        result = demo(args.output, native=args.native)
        print(json.dumps({'result': str(args.output / 'result.json'),
                          'backends': list(result['scenarios'])}))
        return
    if args.command == 'create':
        with Session.create(args.session, session_id=args.id, backend=args.backend,
                            max_actions=args.max_actions, at_utc=args.at_utc) as session:
            result = {'created': args.id, 'revision': session.snapshot()['revision']}
    else:
        with Session(args.session) as session:
            if args.command == 'step':
                raw = json.loads(args.frames.read_text(encoding='utf-8'))
                if type(raw) is not list or any(type(row) is not dict or set(row) != {'timestamp', 'values'} for row in raw):
                    raise ValueError('closed numeric frame schema required; no metadata')
                frames = tuple(AfferentFrame(row['timestamp'], tuple(row['values'])) for row in raw)
                result = session.step(args.event_id, frames, expected_revision=args.revision)
            else:
                result = session.stop() if args.command == 'stop' else session.snapshot()
    if getattr(args, 'output', None):
        write(args.output, result)
    else:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__': main()
