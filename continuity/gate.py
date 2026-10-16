"""Pure control-state transitions. GitHub ref CAS must persist claims BEFORE work.

This does not launch workers, issue body grants, or enforce an OS timeout.
The existing body scheduler remains the authority for any future body wakeup.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

DAY = timedelta(hours=24)
SCHEMA = 'nasuraya-absence-control/1'


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def validate(state, now):
    if state.get('schema') != SCHEMA or type(state.get('enabled')) is not bool:
        raise ValueError('invalid control schema or enabled flag')
    current = timestamp(now)
    contact = timestamp(state['last_contact_at'])
    claimed = timestamp(state['last_claimed_at']) if state['last_claimed_at'] is not None else None
    if contact > current or (claimed is not None and claimed > current):
        raise ValueError('clock regression or future control timestamp')
    for key in ('inflight_run_id', 'last_completed_run_id'):
        value = state[key]
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value)):
            raise ValueError('invalid run id')
    return current, contact, claimed


def evaluate(state, now):
    try:
        current, contact, claimed = validate(state, now)
    except (KeyError, TypeError, ValueError) as exc:
        return dict(eligible=False, reason='invalid_state', detail=str(exc))
    if not state['enabled']:
        return dict(eligible=False, reason='paused')
    if state['inflight_run_id'] is not None:
        return dict(eligible=False, reason='unresolved_previous_run')
    if current-contact < DAY:
        return dict(eligible=False, reason='recent_contact')
    if claimed is not None and current-claimed < DAY:
        return dict(eligible=False, reason='daily_budget_used')
    return dict(eligible=True, reason='absence_window_elapsed')


def claim(state, now, run_id):
    decision = evaluate(state, now)
    if not decision['eligible']:
        raise ValueError(decision['reason'])
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', run_id):
        raise ValueError('invalid run id')
    if run_id == state['last_completed_run_id']:
        raise ValueError('completed run cannot be replayed')
    updated = deepcopy(state)
    updated.update(last_claimed_at=timestamp(now).isoformat(), inflight_run_id=run_id)
    return updated


def finish(state, now, run_id):
    validate(state, now)
    if not isinstance(run_id, str) or run_id != state['inflight_run_id']:
        raise ValueError('only the exact claimed run may finish')
    updated = deepcopy(state)
    updated.update(inflight_run_id=None, last_completed_run_id=run_id)
    return updated


def operator_contact(state, now, pause=False):
    """Operator action, never an autonomous renewal or run-budget reset."""
    validate(state, now)
    updated = deepcopy(state)
    updated.update(last_contact_at=timestamp(now).isoformat(),
                   contact_source='Explicit operator heartbeat')
    if pause:
        updated['enabled'] = False
    return updated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--now', required=True, help='actual trusted time with explicit timezone')
    parser.add_argument('--mode', choices=['evaluate', 'claim', 'finish', 'heartbeat', 'pause'], default='evaluate')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    state = json.loads(Path(args.state).read_text())
    if args.mode == 'evaluate':
        result = evaluate(state, args.now)
    elif args.mode in ('claim', 'finish'):
        result = globals()[args.mode](state, args.now, args.run_id)
    else:
        result = operator_contact(state, args.now, pause=args.mode == 'pause')
    print(json.dumps(result, ensure_ascii=False, indent=2))
