"""Replayable history of computational genome proposals; no body write API.

Integrity and ancestry are relative to the supplied baseline and trusted host.
Hashes do not authenticate an author, a reason, or an external approval.
"""
from copy import deepcopy
import json
from pathlib import Path

from .chromosomes import digest
from .strict_json import loads as strict_loads
from .traits import BODY, baseline, checkpoint, closed, mutate, restore

SCHEMA = 'nasuraya.genome.proposal-history/1'


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(label + ' must be nonempty text')


def create():
    """Start at the source-bound canonical baseline, never an arbitrary root."""
    root = checkpoint(baseline())
    payload = dict(schema=SCHEMA, root=root, events=[], head_sha256=root['sha256'])
    return dict(payload=payload, sha256=digest(payload))


def verify(saved, *, expected_head_sha256=None):
    """Replay the history, optionally requiring an independently trusted head.

    Without an expected head this checks internal integrity only. The expected
    value must come from a trusted record, not from the history being checked.
    It identifies one exact accepted history, not authorship or body permission.
    """
    if expected_head_sha256 is not None and (
            type(expected_head_sha256) is not str or len(expected_head_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_head_sha256)):
        raise ValueError('expected_head_sha256 must be 64 lowercase hexadecimal characters')
    closed(saved, ('payload', 'sha256'), 'history')
    p = saved['payload']
    closed(p, ('schema', 'root', 'events', 'head_sha256'), 'history payload')
    if p['schema'] != SCHEMA or saved['sha256'] != digest(p):
        raise ValueError('history schema or checksum mismatch')
    if p['root'] != checkpoint(baseline()):
        raise ValueError('history root must match the current source-bound baseline')
    if type(p['events']) is not list:
        raise ValueError('history events must be a list')
    genotype = restore(p['root'])
    head = p['root']['sha256']
    for event in p['events']:
        closed(event, ('payload', 'sha256'), 'event')
        e = event['payload']
        closed(e, ('parent_event_sha256', 'parent_genotype_sha256', 'reason',
                   'edits', 'result'), 'event payload')
        _text(e['reason'], 'reason')
        if event['sha256'] != digest(e) or e['parent_event_sha256'] != head:
            raise ValueError('broken event history')
        if e['parent_genotype_sha256'] != digest(genotype):
            raise ValueError('parent genotype mismatch')
        next_genotype = mutate(genotype, e['edits'], expected_revision=genotype['revision'])
        # Python container equality treats True == 1 and False == 0. Compare
        # the canonical JSON records, including their nested checkpoint hash,
        # so malformed typed results cannot pass replay with a stale checksum.
        if digest(e['result']) != digest(checkpoint(next_genotype)):
            raise ValueError('event result does not match replayed edits')
        genotype, head = next_genotype, event['sha256']
    if p['head_sha256'] != head:
        raise ValueError('history head mismatch')
    if expected_head_sha256 is not None and head != expected_head_sha256:
        raise ValueError('history does not match the independently trusted head')
    return deepcopy(genotype)


def verify_json(text, *, expected_head_sha256=None):
    """Decode external JSON without silent overwrites, then replay the history.

    Call this at the file/text boundary. verify(dict) cannot recover duplicate
    keys discarded by a caller's earlier permissive JSON decoder.
    """
    return verify(strict_loads(text), expected_head_sha256=expected_head_sha256)


def append(saved, edits, *, reason, expected_head_sha256):
    """Return a new complete proposal history or fail without changing the input.

    The head check distinguishes divergent branches with equal revision numbers.
    It is an in-memory precondition, not a filesystem multiwriter lock.
    """
    genotype = verify(saved)
    _text(reason, 'reason')
    head = saved['payload']['head_sha256']
    if type(expected_head_sha256) is not str or expected_head_sha256 != head:
        raise ValueError('stale or foreign history head')
    proposed = mutate(genotype, edits, expected_revision=genotype['revision'])
    event = dict(parent_event_sha256=head, parent_genotype_sha256=digest(genotype),
                 reason=reason, edits=deepcopy(edits), result=checkpoint(proposed))
    record = dict(payload=event, sha256=digest(event))
    p = deepcopy(saved['payload'])
    p['events'].append(record)
    p['head_sha256'] = record['sha256']
    return dict(payload=p, sha256=digest(p))


def demo():
    history = create()
    for edits, reason in (
        ([dict(chromosome='P09A', locus='P09.L010', value=1.02)],
         'Synthetic tail proposal for history replay; no physical benefit asserted.'),
        ([dict(chromosome='P08B', locus='P08.L010', value=5.)],
         'Synthetic appearance metadata proposal; no user aesthetic rating inferred.'),
    ):
        history = append(history, edits, reason=reason,
                         expected_head_sha256=history['payload']['head_sha256'])
    verify(json.loads(json.dumps(history)))
    return history


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--demo-output', type=Path)
    group.add_argument('--verify', type=Path)
    parser.add_argument('--expected-head-sha256',
                        help='independently trusted exact history head; requires --verify')
    args = parser.parse_args()
    if args.expected_head_sha256 is not None and args.verify is None:
        parser.error('--expected-head-sha256 requires --verify')
    if args.demo_output:
        if args.demo_output.resolve().is_relative_to(BODY.resolve()):
            parser.error('native runtime destinations are forbidden')
        # Exclusive creation: this demonstration cannot overwrite an existing file.
        with args.demo_output.open('x', encoding='utf-8') as stream:
            json.dump(demo(), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    else:
        try:
            saved = strict_loads(args.verify.read_text(encoding='utf-8'))
            genotype = verify(saved, expected_head_sha256=args.expected_head_sha256)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(dict(revision=genotype['revision'], genotype_sha256=digest(genotype),
                              head_sha256=saved['payload']['head_sha256'],
                              trusted_head_matched=args.expected_head_sha256 is not None,
                              events=len(saved['payload']['events']), native_apply_allowed=False)))
