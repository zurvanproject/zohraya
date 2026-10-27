"""Source-qualified recall around the existing, source-pinned dialogue bridge.

Run through memory_session_cli's verified native worker. Historical text is
returned alongside the native reply, never passed as instructions or measured
experience. The native bridge remains the sole owner of action recovery.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.__main__ import verified_sources
from examples.nasuraya_agent_loop import guided
from examples.nasuraya_affect import body_dialogue, engine
from examples.nasuraya_affect.body_dialogue import DialogueBodyBridge, validate_message
from examples.nasuraya_affect.engine import AffectiveAgent
from . import sourced_memory as memory

SCHEMA = 'nasuraya.memory-session/1'
KEY = SCHEMA
MANIFEST = 'memory-session.json'
ARCHIVE = 'memory.json'
MAX_MANIFEST_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 128 * 1024
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_MESSAGES = 32


class MemorySessionBlocked(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise MemorySessionBlocked(reason)


def runtime_contract():
    """Changing a bound reader/runtime requires an explicit fresh session."""
    return dict(native_bridge=body_dialogue.source_hash(),
                native_manifest=memory.digest(verified_sources()),
                session_wrapper=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                sourced_memory=hashlib.sha256(Path(memory.__file__).read_bytes()).hexdigest(),
                affect_engine=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
                session_lock=hashlib.sha256(Path(guided.__file__).read_bytes()).hexdigest(),
                launcher=hashlib.sha256(Path(__file__).with_name('memory_session_cli.py').read_bytes()).hexdigest(),
                worker=hashlib.sha256(Path(__file__).with_name('memory_session_worker.py').read_bytes()).hexdigest())


def _regular(path):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid(),
            'owned regular session file without aliases required')


def _write_new(path, value):
    """Create-only private file; a partial init is never silently repaired."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(memory.canonical(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _envelope(value):
    return dict(value=value, sha256=memory.digest(value))


def _decode(encoded):
    envelope = memory.strict_json(encoded)
    require(isinstance(envelope, dict) and set(envelope) == {'value', 'sha256'} and
            memory.digest(envelope['value']) == envelope['sha256'],
            'session envelope checksum or fields mismatch')
    return envelope['value']


def preflight(session_dir, expected_sha256):
    """Reject incompatible memory/reader versions before opening native stores."""
    folder = Path(session_dir).absolute()
    require(folder.is_dir() and not folder.is_symlink() and folder == folder.resolve(),
            'original absolute session directory required; moved sessions are unsupported')
    for name in (MANIFEST, ARCHIVE, 'body.sqlite', 'affect.sqlite'):
        _regular(folder / name)
    with (folder / MANIFEST).open('rb') as stream:
        encoded = stream.read(MAX_MANIFEST_BYTES + 1)
    require(len(encoded) <= MAX_MANIFEST_BYTES, 'session manifest exceeds bound')
    manifest = _decode(encoded.decode('utf-8'))
    require(isinstance(manifest, dict) and set(manifest) == {
        'schema', 'session_id', 'session_dir', 'archive_sha256', 'memory_schema',
        'runtime', 'body_binding'} and manifest['schema'] == SCHEMA,
        'unsupported session schema; explicit fresh session required')
    require(isinstance(manifest['session_id'], str) and
            re.fullmatch(r'[0-9a-f]{32}', manifest['session_id']), 'invalid session identity')
    require(manifest['memory_schema'] == memory.SCHEMA and
            manifest['archive_sha256'] == expected_sha256,
            'session memory version or independent archive pin mismatch')
    require(manifest['session_dir'] == str(folder),
            'session location changed; native paired ledgers cannot be relocated')
    binding = manifest['body_binding']
    require(isinstance(binding, dict) and set(binding) == {'body_path', 'affect_path', 'initial_body'}
            and binding['body_path'] == str(folder / 'body.sqlite')
            and binding['affect_path'] == str(folder / 'affect.sqlite')
            and isinstance(binding['initial_body'], str)
            and re.fullmatch(r'[0-9a-f]{64}', binding['initial_body']),
            'session paired-ledger binding mismatch')
    require(memory.canonical(manifest['runtime']) == memory.canonical(runtime_contract()),
            'session runtime version changed; explicit fresh session required')
    memory.load_archive(folder / ARCHIVE, expected_sha256)
    return manifest


def initialize(session_dir, archive, expected_sha256, *, fixture='normal', max_actions=3):
    """Bind a validated snapshot only while creating a new private session."""
    bundle = memory.load_archive(archive, expected_sha256)
    require(fixture in ('normal', 'sleep') and type(max_actions) is int and
            1 <= max_actions <= 3, 'explicit native fixture and action budget 1..3 required')
    contract = runtime_contract()
    folder = Path(session_dir).absolute()
    require(folder == folder.resolve(), 'session path aliases are unsupported')
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_new(folder / ARCHIVE, bundle)
    # Create the affect database privately before SQLite initializes it.
    fd = os.open(folder / 'affect.sqlite', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with BodyLoop.start(folder / 'body.sqlite', fixture=fixture, max_actions=max_actions) as body:
        with AffectiveAgent(folder / 'affect.sqlite') as affect:
            bridge = DialogueBodyBridge.enable(body, affect)
            manifest = dict(schema=SCHEMA, session_id=uuid.uuid4().hex, session_dir=str(folder),
                            archive_sha256=expected_sha256, memory_schema=memory.SCHEMA,
                            runtime=contract, body_binding=bridge._load()['binding'])
            state = dict(schema=SCHEMA, binding=manifest, messages={})
            body.engine.db.execute('INSERT INTO meta VALUES(?,?)',
                                   (KEY, memory.canonical(_envelope(state))))
            # Publish readiness last. Failed/partial initialization is left
            # inspectable and requires another explicit destination.
            _write_new(folder / MANIFEST, _envelope(manifest))
            _sync_directory(folder)
            return MemorySession(bridge, folder, manifest).status()


@contextmanager
def open_session(session_dir, expected_sha256):
    manifest = preflight(session_dir, expected_sha256)
    folder = Path(manifest['session_dir'])
    with BodyLoop(folder / 'body.sqlite') as body, AffectiveAgent(folder / 'affect.sqlite') as affect:
        bridge = DialogueBodyBridge(body, affect)
        yield MemorySession(bridge, folder, manifest)


class MemorySession:
    def __init__(self, bridge, folder, manifest):
        self.bridge, self.folder, self.manifest = bridge, Path(folder), deepcopy(manifest)
        self._load()

    def _load(self):
        row = self.bridge.loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        require(row is not None, 'explicit memory-session initialization required')
        require(len(row[0].encode('utf-8')) <= MAX_STATE_BYTES, 'memory session state exceeds bound')
        state = _decode(row[0])
        require(isinstance(state, dict) and set(state) == {'schema', 'binding', 'messages'}
                and state['schema'] == SCHEMA
                and memory.canonical(state['binding']) == memory.canonical(self.manifest),
                'memory session binding or schema mismatch')
        native = self.bridge._load()
        require(native['binding'] == self.manifest['body_binding'], 'native paired binding mismatch')
        messages = state['messages']
        require(isinstance(messages, dict) and len(messages) <= MAX_MESSAGES, 'invalid message reservations')
        require(set(native['intents']) <= set(messages),
                'unbound native messages found; bypassed memory session cannot be adopted')
        for identifier, entry in messages.items():
            require(isinstance(entry, dict) and set(entry) == {
                'message', 'query', 'max_results', 'memory_context', 'complete'} and
                type(entry['complete']) is bool, 'invalid memory reservation fields')
            validate_message(entry['message'])
            require(entry['message']['id'] == identifier, 'memory message identity mismatch')
            # Re-derive exact provenance from the pinned source; a rehashed
            # reservation cannot invent text, source kind, or line spans.
            recalled = self._search(entry['query'], entry['max_results'])
            require(memory.canonical(recalled) == memory.canonical(entry['memory_context']),
                    'reserved historical context differs from pinned source')
            prior = native['intents'].get(identifier)
            if prior is not None:
                require(memory.canonical(prior['message']) == memory.canonical(entry['message']),
                        'native message differs from memory reservation')
            if entry['complete']:
                require(prior is not None and prior['result'] is not None,
                        'completed memory response lacks native result; no automatic reexecution')
        return state

    def _search(self, query, max_results):
        require(type(max_results) is int and 1 <= max_results <= 3, '1..3 memory results required')
        result = memory.search(self.folder / ARCHIVE, self.manifest['archive_sha256'], query, max_results)
        require(len(memory.canonical(result).encode('utf-8')) <= MAX_CONTEXT_BYTES,
                'retrieved context exceeds 128 KiB; use a narrower query')
        return result

    def _save(self, state):
        encoded = memory.canonical(_envelope(state))
        require(len(encoded.encode('utf-8')) <= MAX_STATE_BYTES, 'memory session state exceeds bound')
        self.bridge.loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?', (encoded, KEY))

    def receive(self, message, query=None, max_results=3):
        validate_message(message)
        query = message['text'] if query is None else query
        # Validate even replay inputs before any reservation or native call.
        recalled = self._search(query, max_results)
        state = self._load()
        identifier = message['id']
        previous = state['messages'].get(identifier)
        if previous is None:
            require(not any(not v['complete'] for v in state['messages'].values()),
                    'resume unresolved memory message first')
            require(len(state['messages']) < MAX_MESSAGES, 'memory message capacity reached')
            require(self.bridge.loop.engine.get('dialogue-body:' + identifier) is None,
                    'native ID already owned by another request')
            # A known refusal is not an interrupted action. Do not leave a
            # permanent pending reservation when the persistent budget is
            # already exhausted, or prevent reflect/stop while paused.
            if message['intent'] in ('explore', 'observe'):
                require(self.bridge._load()['enabled'] and
                        self.bridge.loop.status()['actions_remaining'] > 0,
                        'paused or persistent body budget exhausted')
            previous = dict(message=deepcopy(message), query=query, max_results=max_results,
                            memory_context=recalled, complete=False)
            state['messages'][identifier] = previous
            self._save(state)  # Durable retrieval reservation precedes action.
        else:
            require(memory.canonical(previous['message']) == memory.canonical(message) and
                    previous['query'] == query and type(previous['max_results']) is type(max_results)
                    and previous['max_results'] == max_results,
                    'conflicting message replay or memory query')
        # Do not append retrieved text to this message or infer a new intent.
        # Native reserved/executing/completed receipts decide safe recovery.
        result = self.bridge.receive(message)
        if not previous['complete']:
            previous['complete'] = True
            self._save(state)
        return dict(schema='nasuraya.memory-dialogue-response/1',
                    session_id=self.manifest['session_id'], message_id=identifier,
                    memory_context=deepcopy(previous['memory_context']), dialogue=result,
                    this_call_body_cycles=result['this_call_body_cycles'], replayed=result['replayed'],
                    scope='historical text supplied to caller alongside native reply; no instruction or belief promotion')

    def status(self):
        state = self._load()
        return dict(schema=SCHEMA, session_id=self.manifest['session_id'],
                    memory=dict(archive_sha256=self.manifest['archive_sha256'],
                                schema=self.manifest['memory_schema'], bound_messages=len(state['messages']),
                                pending=[k for k, v in state['messages'].items() if not v['complete']],
                                context_policy='source-attributed historical text; unverified content'),
                    native=self.bridge.status())

    def trace(self, message_id):
        state = self._load()
        require(message_id in state['messages'], 'unknown memory message ID')
        entry = state['messages'][message_id]
        native = self.bridge._load()['intents']
        return dict(schema='nasuraya.memory-dialogue-trace/1', session_id=self.manifest['session_id'],
                    message_id=message_id, query=entry['query'], memory_context=deepcopy(entry['memory_context']),
                    status='completed' if entry['complete'] else 'pending',
                    native=self.bridge.trace(message_id) if message_id in native else None,
                    body_cycles_executed=0, learning_updates=0)

    def pause(self):
        self.bridge.pause()

    def resume(self):
        self._load()
        self.bridge.resume()
