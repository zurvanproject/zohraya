"""Session worker launched only with a copied, verified native body runtime."""
import json
from pathlib import Path
import sys

from nasuraya.memory_session import initialize, open_session
from nasuraya.sourced_memory import strict_json

MAX_REQUEST_BYTES = 64 * 1024
MAX_MESSAGE_BYTES = 32 * 1024


def _read_message(path):
    with Path(path).open('rb') as stream:
        encoded = stream.read(MAX_MESSAGE_BYTES + 1)
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError('message JSON exceeds 32 KiB')
    value = strict_json(encoded.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('explicit message JSON object required')
    return value


def main(args):
    if not isinstance(args, dict) or set(args) != {
            'command', 'session_dir', 'expected_sha256', 'archive', 'message',
            'message_id', 'query', 'max_results', 'fixture', 'max_actions'}:
        raise ValueError('exact explicit worker arguments required')
    command = args['command']
    if command not in ('init', 'message', 'status', 'trace', 'pause', 'resume'):
        raise ValueError('unknown memory-session command')
    if command == 'init':
        if args['archive'] is None:
            raise ValueError('archive is required for explicit initialization')
        result = initialize(args['session_dir'], args['archive'], args['expected_sha256'],
                            fixture=args['fixture'], max_actions=args['max_actions'])
    else:
        # Parse the message before opening a native store. Invalid input cannot
        # cause any body execution or ledger changes through this worker.
        message = _read_message(args['message']) if command == 'message' else None
        with open_session(args['session_dir'], args['expected_sha256']) as session:
            if command == 'message':
                result = session.receive(message, query=args['query'], max_results=args['max_results'])
            elif command == 'trace':
                result = session.trace(args['message_id'])
            else:
                if command == 'pause':
                    session.pause()
                elif command == 'resume':
                    session.resume()
                result = session.status()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        encoded = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError('worker request exceeds 64 KiB')
        raise SystemExit(main(strict_json(encoded.decode('utf-8'))))
    except Exception as exc:
        print(json.dumps(dict(status='rejected', kind=type(exc).__name__, reason=str(exc)),
                         ensure_ascii=False))
        raise SystemExit(1)
