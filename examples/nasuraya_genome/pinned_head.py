"""Create-only, independently supplied history references for a trusted host.

No reference is inferred from a candidate history and no existing reference is
advanced. Atomic publication uses a same-directory hard link on a local POSIX
filesystem. A caller controlling both the reference and history is still trusted.
"""
import json
import os
from pathlib import Path
import tempfile

from .chromosomes import digest
from .history import SCHEMA as HISTORY_SCHEMA, verify_json
from .strict_json import loads
from .traits import BODY, closed

SCHEMA = 'nasuraya.genome.pinned-head/1'


def _head(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('trusted_head_sha256 must be 64 lowercase hexadecimal characters')
    return value


def pin(path, *, trusted_head_sha256):
    """Publish a complete new reference, never replace an existing destination.

    The host must obtain the head independently and authorize this explicit pin.
    File and directory fsync complete before success. If publication succeeds but
    a later filesystem operation fails, the reference may exist: inspect it;
    retries never overwrite it. Unsupported filesystems fail without fallback.
    """
    head = _head(trusted_head_sha256)
    path = Path(path)
    if path.resolve().is_relative_to(BODY.resolve()):
        raise ValueError('native runtime destinations are forbidden')
    record = dict(schema=SCHEMA, history_schema=HISTORY_SCHEMA, head_sha256=head)
    temporary = None
    try:
        # NamedTemporaryFile creates an owner-only file; keep the same directory
        # so link publication cannot cross filesystems or expose a partial write.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.trusted-head-', delete=False) as stream:
            temporary = stream.name
            json.dump(record, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic create-only: competing initializers cannot replace it.
    finally:
        if temporary is not None:
            os.unlink(temporary)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return head


def load(path):
    """Read a strict, versioned reference; missing/corrupt data never defaults."""
    record = loads(Path(path).read_text(encoding='utf-8'))
    closed(record, ('schema', 'history_schema', 'head_sha256'), 'pinned history head')
    if record['schema'] != SCHEMA or record['history_schema'] != HISTORY_SCHEMA:
        raise ValueError('unsupported pinned head or history schema')
    return _head(record['head_sha256'])


def verify_pinned_json(text, *, anchor_path):
    """Replay against one reference snapshot and return a read-only receipt."""
    head = load(anchor_path)
    genotype = verify_json(text, expected_head_sha256=head)
    return dict(schema='nasuraya.genome.pinned-verification/1',
                revision=genotype['revision'], genotype_sha256=digest(genotype),
                head_sha256=head, trusted_head_matched=True, native_apply_allowed=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('pin', help='explicitly save an independently trusted head once')
    initialize.add_argument('--anchor', type=Path, required=True)
    initialize.add_argument('--head', required=True)
    check = commands.add_parser('verify', help='verify external JSON using an existing reference')
    check.add_argument('--anchor', type=Path, required=True)
    check.add_argument('--history', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'pin':
            head = pin(args.anchor, trusted_head_sha256=args.head)
            result = dict(anchor_created=True, head_sha256=head, native_apply_allowed=False)
        else:
            result = verify_pinned_json(args.history.read_text(encoding='utf-8'), anchor_path=args.anchor)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))
