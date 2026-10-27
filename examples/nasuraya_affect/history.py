"""Read-only, source-aware recovery of paired dialogue ledgers.

No BodyLoop/AffectiveAgent is opened on the source. No request is executed,
learned, re-signed or imported into an active session. Checksums establish
internal consistency, not authenticity of an unsigned historical ledger.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from .engine import (SCHEMA as AFFECT_SCHEMA, canonical, digest, validate_event,
                     validate_options, initial_state, evolve, number)
from .body_dialogue import KEY, validate_message
from examples.nasuraya_body_loop.host import SCHEMA as BODY_SCHEMA, describe
from examples.nasuraya_body_loop.experience import KEY as EXPERIENCE_KEY, METRICS, metrics, context
from reflection_cycle import (SCHEMA as NATIVE_SCHEMA, validate_request,
                              action_signature, outcome_matches)
from unified_body_v2 import UnifiedBody

SCHEMA = 'nasuraya-dialogue-history/1'
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 10000
# Exact, inspected historical contracts; schema /1 alone is NOT compatibility.
PROFILES = {
    '717fccdcd9113c2c1749d010fd42b840f0a1800e4b82d7f31c89cbaa44c59736':
        ('8e952de53dbbb8c5c6a8f9d5620f9823e1c7932d', False),
    '4b7a053763ffd630a9631ba3409737d3c063554907719ef74437c3f0d5f154c6':
        ('a6e6f451e4383383082a536b19966755a9ac09a1', False),
    'aa5008a7c3ed6161c30154d7989e3d2265544ba25f5c8ab74a9cbfcc51a81216':
        ('6281c5389b5a7a75d4bf6c6505a24699c98beb70', True),
}
AFFECT_HASH = 'b243e2b67aa418bf1188e8fcf473076bab3b826a41460b2cfa1b3731d9d7ecbe'
NATIVE_HASH = '50acd252e816a83c002477d14a377dd990e932471cafd39f8be7dee247b503e5'
RUNTIME_HASH = '8a6f3036fc4b68e9e6d806896e666e07c921bf1d52b467e33f1be77227b91275'


class HistoryBlocked(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise HistoryBlocked(reason)


def strict_json(encoded):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON field: ' + key)
            value[key] = item
        return value
    def constant(value):
        raise HistoryBlocked('non-finite JSON number: ' + value)
    return json.loads(encoded, object_pairs_hook=pairs, parse_constant=constant)


def envelope(encoded):
    value = strict_json(encoded)
    require(set(value) == {'value', 'sha256'}, 'unknown envelope schema')
    require(digest(value['value']) == value['sha256'], 'envelope checksum mismatch')
    return value['value']


@contextmanager
def _locked_file(path):
    # Read-only descriptor; do not create/tighten permissions on source files.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                'regular unaliased source/lock required')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)


def _bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_BYTES,
                'bounded regular source file required')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        require(len(data) <= MAX_BYTES, 'source exceeds size limit')
        return data
    finally:
        os.close(fd)


def _source_bytes(folder):
    values = {}
    for name in ('body.sqlite', 'affect.sqlite'):
        values[name] = _bytes(folder / name)
        try:
            values[name + '-wal'] = _bytes(folder / (name + '-wal'))
        except FileNotFoundError:
            pass
    return values


def _tables(path):
    # SQLite may create/rebuild SHM only in this private temporary copy. WAL
    # must be included; immutable=1 on the original would silently lose commits.
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SQLite integrity check failed')
        result = {}
        for row in db.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            name = row['name']
            require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) and
                    'VIRTUAL' not in row['sql'].upper(), 'unsupported SQLite table')
            values = [dict(r) for r in db.execute('SELECT * FROM "' + name + '" LIMIT ?', (MAX_ROWS + 1,))]
            require(len(values) <= MAX_ROWS, 'table exceeds recovery bound')
            # Deterministic logical snapshot, independent of SQLite page layout.
            result[name] = sorted(values, key=canonical)
        return result
    finally:
        db.close()


def capture(folder):
    """Capture a quiescent pair, including committed WAL, without source writes."""
    folder = Path(folder)
    require(not folder.is_symlink(), 'source folder must not be a symlink')
    folder = folder.resolve(strict=True)
    with ExitStack() as stack:
        stack.enter_context(_locked_file(folder / 'body.sqlite'))
        # The bridge uses body first, then this existing affect lock.
        stack.enter_context(_locked_file(folder / 'affect.sqlite.lock'))
        before = _source_bytes(folder)
        with tempfile.TemporaryDirectory(prefix='nasuraya-history-read-') as tmp:
            root = Path(tmp)
            for name, data in before.items():
                (root / name).write_bytes(data)
            tables = {name: _tables(root / name) for name in ('body.sqlite', 'affect.sqlite')}
        require(before == _source_bytes(folder), 'source changed during capture; quiesce writers and retry')
    return dict(schema=SCHEMA, original_location=str(folder), tables=tables,
                file_sha256={name: hashlib.sha256(data).hexdigest() for name, data in before.items()})


def _meta(tables):
    rows = tables['meta']
    require(all(set(r) == {'key', 'value'} for r in rows), 'unknown metadata columns')
    require(len({r['key'] for r in rows}) == len(rows), 'duplicate metadata key')
    return {r['key']: r['value'] for r in rows}


def _affect(tables):
    require(set(tables) == {'meta', 'events'}, 'unknown affect tables')
    meta = _meta(tables)
    require(strict_json(meta['contract']) == dict(schema=AFFECT_SCHEMA, engine_hash=AFFECT_HASH),
            'unsupported affect source/version')
    state = envelope(meta['state'])
    events = {}
    previous = initial_state()
    for sequence, row in enumerate(sorted(tables['events'], key=lambda r: r['seq']), 1):
        require(set(row) == {'id', 'seq', 'context', 'topic', 'request_sha', 'record'}, 'unknown affect event columns')
        record = envelope(row['record']); event = validate_event(record['event'])
        require(event['id'] not in events and type(row['seq']) is int and row['seq'] == sequence and event['id'] == row['id'] and
                event['context'] == row['context'] and event['topic'] == row['topic'],
                'affect event identity/sequence mismatch')
        validate_options(record['options'])
        require(record['engine_hash'] == AFFECT_HASH, 'affect event source mismatch')
        require(type(record['decision']['affect_enabled']) is bool and type(record['use_memory']) is bool,
                'invalid affect feature flags')
        request = dict(event=event, options=record['options'],
                       use_affect=record['decision']['affect_enabled'], use_memory=record['use_memory'])
        require(row['request_sha'] == digest(request), 'affect request checksum mismatch')
        after, pulse = evolve(previous, event)
        require(record['state_before'] == previous and record['state_after'] == after and
                record['pulse'] == pulse, 'affect state transition mismatch')
        for memory in record['recalled']:
            source = events.get(memory['event_id'])
            require(source is not None and source['event']['source'] == memory['source'] and
                    source['event']['summary'] == memory['summary'], 'unresolved affect memory provenance')
        events[event['id']] = record
        previous = after
    require(previous == state, 'affect final state/revision mismatch')
    return meta, events


def _native(tables, config):
    require(set(tables) == {'meta', 'decisions', 'runtime', 'commitments', 'feedback_index'},
            'unknown native tables')
    require(_meta(tables)['schema'] == NATIVE_SCHEMA, 'unknown native schema')
    records, snapshots = {}, {}
    previous_checkpoint, previous_revision = config['initial_checkpoint_sha256'], 0
    unresolved = False
    for sequence, row in enumerate(sorted(tables['decisions'], key=lambda r: r['seq']), 1):
        require(set(row) == {'id', 'seq', 'fingerprint', 'context', 'topic', 'status', 'record'},
                'unknown native decision columns')
        r = strict_json(row['record'])
        require(r['schema'] == NATIVE_SCHEMA and r['engine_fingerprint'] == NATIVE_HASH,
                'unsupported native source/version')
        request = validate_request(r['request'])
        require(not unresolved, 'native record follows an unresolved operation')
        require(request['evidence'][0]['source_sha256'] == previous_checkpoint and
                request['evidence'][0]['claim'] == dict(key='body_revision', value=previous_revision),
                'native checkpoint chain mismatch')
        require(type(r['use_memory']) is bool, 'invalid native memory flag')
        fingerprint = digest(dict(request=request, engine=NATIVE_HASH, use_memory=r['use_memory']))
        require(type(row['seq']) is int and type(r['sequence']) is int and
                row['id'] == r['id'] == request['id'] and row['seq'] == r['sequence'] == sequence and
                row['fingerprint'] == r['request_fingerprint'] == fingerprint and
                row['context'] == r['context'] == request['context'] == config['context'] and
                row['topic'] == r['topic'] == request['topic'] and row['status'] == r['status'] and
                r['status'] in ('planned', 'running', 'complete'), 'native identity/fingerprint mismatch')
        selected = next((a for a in request['actions'] if a['id'] == r['selected_action']), None)
        require(r['action_signature'] == (action_signature(selected) if selected else None),
                'native action signature mismatch')
        require(r['expected_outcome'] == (selected['expected_outcome'] if selected else None),
                'native expected outcome mismatch')
        if r['status'] == 'complete':
            actual, feedback = r['actual_outcome'], r['feedback']
            require(actual.get('status') == 'completed', 'native completion lacks a measured body receipt')
            require(feedback['verified'] is True and
                    feedback['success'] == outcome_matches(r['expected_outcome'], actual),
                    'native feedback mismatch')
            witnesses = feedback['evidence']
            require(any(w['source_sha256'] == RUNTIME_HASH and w['kind'] == 'observed' and
                        w['source_ref'] == 'runtime://UnifiedBody.cycle' and
                        w['locator'] == 'event/reflection:' + r['id'] for w in witnesses),
                    'native runtime witness mismatch')
            if actual.get('status') == 'completed':
                checkpoint, receipt = actual['body_checkpoint'], actual['body_receipt']
                restored = UnifiedBody.restore(checkpoint)  # validation only, never cycle()
                require(receipt['event_id'] == 'reflection:' + r['id'] and
                        checkpoint['payload']['results'][receipt['event_id']] == receipt and
                        receipt['revision'] == restored.revision and
                        actual['selected_action'] == receipt['owner']['selected_action'],
                        'native receipt/checkpoint mismatch')
                snapshots[r['id']] = describe(restored)
                require(restored.revision == previous_revision + 1, 'native revision gap')
                previous_checkpoint, previous_revision = checkpoint['sha256'], restored.revision
        else:
            require(r['actual_outcome'] is None and r['feedback'] is None, 'unresolved native has an outcome')
            unresolved = True
        require(r['id'] not in records, 'duplicate native ID')
        records[r['id']] = r
    runtime = tables['runtime']
    require(len(runtime) == 1 and set(runtime[0]) == {'key', 'digest', 'value'} and
            runtime[0]['key'] == 'nasuraya-body-loop', 'unsupported runtime set')
    checkpoint = strict_json(runtime[0]['value'])
    require(runtime[0]['digest'] == digest(checkpoint), 'runtime checksum mismatch')
    restored = UnifiedBody.restore(checkpoint)
    completed = [r for r in records.values() if r['id'] in snapshots]
    if completed:
        require(checkpoint == completed[-1]['actual_outcome']['body_checkpoint'], 'runtime/receipt head mismatch')
    else:
        require(checkpoint['sha256'] == config['initial_checkpoint_sha256'] and restored.revision == 0,
                'runtime differs from initial checkpoint without a receipt')
    return records, snapshots


def _experience(meta, config, native, snapshots):
    state = envelope(meta[EXPERIENCE_KEY])
    require(state['schema'] == EXPERIENCE_KEY and state['native_config'] == config,
            'experience version/config mismatch')
    require(set(state['flags']) == {'affect', 'prediction', 'memory', 'consolidation'} and
            all(type(v) is bool for v in state['flags'].values()), 'invalid experience flags')
    episodes = {}
    for episode in state['episodes']:
        identifier = episode['id']
        require(identifier not in episodes, 'duplicate experience episode')
        intent = state['intents'][identifier]; result = intent['result']
        r = native[intent['native_id']]
        require(result is not None and intent['native_id'] in snapshots, 'experience without completed receipt')
        source = 'native-decision://' + r['id'] + '/' + digest(r)
        prediction = result['prediction']
        receipt = result['native_receipt']
        require(result['request_id'] == identifier and receipt['decision_id'] == r['id'] and
                receipt['actual_action'] == r['actual_outcome']['selected_action'] and
                receipt['self_model_after'] == snapshots[r['id']], 'experience cached receipt mismatch')
        require(episode['source'] == prediction['source'] == source and
                episode['kind'] == 'observed_software_outcome' and
                episode['actual_action'] == r['actual_outcome']['selected_action'] and
                episode['preferred'] == intent['plan']['preferred'] and
                episode['context'] == intent['plan']['context'], 'experience provenance mismatch')
        require(prediction['actual'] == metrics(snapshots[r['id']]) and
                prediction['before'] == metrics(intent['snapshot']), 'experience observation mismatch')
        expected = intent['plan']['prediction']
        require(all(prediction[k] == v for k, v in expected.items()), 'forecast changed after reservation')
        error = sum(abs(prediction['actual'][k] - prediction['expected'][k]) for k in METRICS) / len(METRICS)
        require(prediction['mean_absolute_error'] == error, 'prediction error mismatch')
        harm = max(float(episode['actual_action'] == 'protect'),
                   max(0., min(1., prediction['actual']['pain'] - prediction['before']['pain'])))
        require(episode['harm'] == harm and episode['importance'] == max(.2, harm, error),
                'episode outcome appraisal mismatch')
        number(episode['strength'], 'historical episode strength')
        require(type(episode['archived']) is bool and type(episode['accesses']) is int and episode['accesses'] >= 0,
                'invalid historical episode state')
        episodes[identifier] = episode
    for identifier, intent in state['intents'].items():
        require(intent.get('external') is True and intent['native_id'] == 'dialogue-body:' + identifier,
                'non-dialogue experience requires another adapter')
        record = native.get(intent['native_id'])
        if record:
            require({k: v for k, v in record['request'].items() if k != 'execution'} == intent['native_request'],
                    'experience/native request mismatch')
        if intent['result'] is not None and intent['result']['prediction'].get('actual') is not None:
            require(identifier in episodes, 'learned result without source episode')
        forecast = intent['plan']['prediction']
        require(forecast['before'] == metrics(intent['snapshot']) and
                intent['plan']['context'] == context(forecast['before']) and
                set(forecast['expected']) == set(METRICS), 'forecast observation/context mismatch')
        for value in forecast['expected'].values():
            number(value, 'forecast metric')
        history = []
        require(len(forecast['history_ids']) == len(set(forecast['history_ids'])), 'duplicate forecast history ID')
        for prior_id in forecast['history_ids']:
            prior = state['intents'][prior_id]
            require(prior_id in episodes and prior_id != identifier and
                    prior['plan']['preferred'] == intent['plan']['preferred'] and
                    snapshots[prior['native_id']]['revision'] <= intent['snapshot']['revision'] and
                    (record is None or native[prior['native_id']]['sequence'] < record['sequence']),
                    'forecast history must precede this receipt and match its preference')
            p = prior['result']['prediction']
            history.append(dict(id=prior_id, fixture=prior['plan']['context'], duration_s=prior['duration_s'],
                observed=p['before'], actual_metrics=p['actual'],
                actual_action=prior['result']['native_receipt']['actual_action']))
        require(forecast['history_sha256'] == digest(history), 'forecast history checksum mismatch')
        from experiments.affect_api_20261023.paired_comparison import baselines
        observation = dict(id=identifier, fixture=intent['plan']['context'], duration_s=intent['duration_s'],
                           observed=forecast['before'], proposed_host_preference=intent['plan']['preferred'])
        local = baselines(observation, history)['nearest_episode']
        available = any(e['fixture'] == observation['fixture'] for e in history)
        if intent['plan']['preferred'] == 'observe' and not available:
            local['predicted_action'] = 'observe'
        method = 'nearest_episode' if available else 'persistence_fallback'
        require(forecast['expected'] == local['predicted_metrics'] and
                forecast['predicted_action'] == local['predicted_action'] and
                forecast['method'] == forecast['action_method'] == method and
                forecast['new_api_calls'] == 0 and forecast['numeric_gate']['eligible'] is False,
                'forecast differs from supported local contract')
        if identifier in episodes:
            require(intent['result']['prediction']['action_correct'] ==
                    (forecast['predicted_action'] == episodes[identifier]['actual_action']),
                    'action forecast score mismatch')
    return state, episodes


def _validate(snapshot):
    require(snapshot['schema'] == SCHEMA, 'unknown history schema')
    bt, at = (snapshot['tables'][name] for name in ('body.sqlite', 'affect.sqlite'))
    bm = _meta(bt); state = envelope(bm[KEY])
    require(state['schema'] == KEY and state['source_hash'] in PROFILES, 'unsupported dialogue source/version')
    commit, integrated = PROFILES[state['source_hash']]
    require(state.get('experience_integrated', False) is integrated and type(state['enabled']) is bool,
            'dialogue integration marker mismatch')
    require(set(state) == {'schema', 'source_hash', 'binding', 'enabled', 'intents'} |
            ({'experience_integrated'} if integrated else set()), 'unknown dialogue state fields')
    config = strict_json(bm[BODY_SCHEMA])
    require(config['mode'] == 'bounded' and type(config['max_actions']) is int and
            1 <= config['max_actions'] <= 3, 'unsupported body budget/mode')
    am, events = _affect(at)
    binding = state['binding']
    require(set(binding) == {'body_path', 'affect_path', 'initial_body'} and
            binding == strict_json(am[KEY]) and binding['body_path'] != binding['affect_path'] and
            binding['initial_body'] == config['initial_checkpoint_sha256'], 'paired-ledger binding mismatch')
    # Paths are provenance, not instructions. Archived pairs may be relocated.
    require(all(isinstance(binding[k], str) and Path(binding[k]).is_absolute()
                for k in ('body_path', 'affect_path')), 'absolute historical binding required')
    native, snapshots = _native(bt, config)
    if integrated:
        experience, episodes = _experience(bm, config, native, snapshots)
    else:
        require(EXPERIENCE_KEY not in bm, 'unexpected legacy experience store')
        experience, episodes = None, {}
    require(len(state['intents']) <= 32, 'message bound exceeded')
    binding_id = digest(dict(binding=binding, source_hash=state['source_hash']))
    archive_id = digest(snapshot)
    recovered = []
    for identifier, intent in sorted(state['intents'].items()):
        message = intent['message']; validate_message(message)
        require(message['id'] == identifier and intent['native_id'] == 'dialogue-body:' + identifier,
                'message/native identity mismatch')
        event = validate_event(intent['event'])
        expected_event = validate_message(message)
        if intent['restrictions']:
            checks = expected_event['appraisal']
            checks['threat'] = max(checks['threat'], .8)
            checks['controllability'] = min(checks['controllability'], .3)
        require(event['id'] == 'dialogue:' + identifier and event['summary'] == message['text'] and
                event == expected_event,
                'message/event provenance mismatch')
        event_record = events.get(event['id'])
        if event_record:
            require(event_record['event'] == event and canonical(event_record['options']) == canonical([dict(action=asdict(a), tendencies=t)
                    for a, t in validate_options(intent['choices'])]),
                    'message/affect event mismatch')
        result = intent['result']; r = native.get(intent['native_id'])
        if result is not None:
            require(result['message_id'] == identifier and event_record is not None and
                    result['plan'] == intent['plan'] == event_record['decision'], 'message result/plan mismatch')
        outcome = None
        if r:
            require(message['intent'] in ('explore', 'observe') and intent['stage'] == 'executing',
                    'native receipt for a non-executing message')
            request = r['request']; execution = request['execution']
            require({k: v for k, v in request.items() if k != 'execution'} == intent['native_request'] and
                    execution['runtime_key'] == 'nasuraya-body-loop' and execution['external'] == {} and
                    execution['duration_s'] == message['duration_s'], 'message/native receipt binding mismatch')
            observation = intent['observation']
            require(request['evidence'][0]['source_sha256'] == observation['checkpoint_sha256'] and
                    request['evidence'][0]['claim']['value'] == observation['revision'],
                    'message/native observation mismatch')
            if r['id'] in snapshots:
                source = 'native-decision://' + r['id'] + '/' + digest(r)
                actual = r['actual_outcome']
                require(actual['body_receipt']['owner']['start_minimum_state'] == observation['minimum_state'],
                        'reserved observation/receipt start mismatch')
                outcome = dict(source=source, kind='observed_software_outcome',
                               actual_action=actual['selected_action'], after=snapshots[r['id']])
                feedback = events.get('body-feedback:' + identifier)
                if feedback:
                    require(feedback['event']['source'] == dict(kind='observed', locator=source),
                            'body feedback source mismatch')
                if result is not None:
                    receipt = result['native_receipt']
                    require(feedback is not None and receipt['decision_id'] == r['id'] and
                            receipt['actual_action'] == actual['selected_action'] and
                            receipt['self_model_after'] == snapshots[r['id']], 'cached result/receipt mismatch')
        if result is not None and message['intent'] in ('explore', 'observe'):
            require(r is not None and r['status'] == 'complete', 'completed message without native receipt')
        if result is not None and message['intent'] in ('reflect', 'stop'):
            require(result['native_receipt'] is None and r is None, 'non-motion result contains a body receipt')
        ei = experience['intents'].get(identifier) if experience else None
        if integrated and intent['stage'] == 'executing':
            require(ei is not None and ei['snapshot'] == intent['observation'] and
                    ei['duration_s'] == message['duration_s'] and ei['plan']['prediction'] == intent['forecast'] and
                    ei['native_request'] == intent['native_request'], 'dialogue/experience reservation mismatch')
            if result is not None:
                require(ei['result'] is not None and result['experience'] == ei['result'],
                        'dialogue/experience result mismatch')
                require(result['provenance'] == dict(message='conversation://' + identifier,
                        appraisal='caller_authored_interpretation', outcome=outcome['source']),
                        'dialogue result provenance mismatch')
        status = ('completed' if result is not None else
                  'receipt_recovered_not_reexecuted' if outcome else 'unresolved_do_not_execute')
        recovered.append(dict(id=identifier, historical_id=archive_id + '/' + identifier,
            status=status, message=deepcopy(message), message_source='conversation://' + identifier,
            appraisal_kind='caller_authored_interpretation', outcome=outcome,
            forecast=deepcopy(intent.get('forecast')), stored_episode=deepcopy(episodes.get(identifier)),
            prediction=deepcopy(ei['result']['prediction']) if ei and ei['result'] else None,
            original_result=deepcopy(result), body_cycles_executed=0, learning_updates=0))
    require(set(native) <= {i['native_id'] for i in state['intents'].values()},
            'unowned native receipt requires another adapter')
    if experience:
        require(set(experience['intents']) <= set(state['intents']), 'unowned experience intent')
    return dict(status='validated_read_only', source_commit=commit, source_hash=state['source_hash'],
                source_binding_id=binding_id, archive_sha256=archive_id, records=recovered,
                active_state_migration=False, body_cycles_executed=0, learning_updates=0,
                trust='internal source/receipt consistency; not external authenticity or proof of user beliefs')


def inspect(snapshot):
    """Fail closed as a whole; never silently salvage a partially corrupt pair."""
    try:
        return _validate(snapshot)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return dict(status='archive_only', reasons=[str(exc)], records=[],
                    active_state_migration=False, body_cycles_executed=0, learning_updates=0)


def export_history(folder, destination):
    require(not Path(destination).resolve().is_relative_to(Path(folder).resolve()),
            'archive destination must be outside the source session')
    snapshot = capture(folder)
    bundle = dict(value=snapshot, sha256=digest(snapshot))
    encoded = canonical(bundle) + '\n'
    require(len(encoded.encode('utf-8')) <= MAX_BYTES, 'archive exceeds recovery size limit')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Publish only complete bytes; retries cannot overwrite an earlier archive.
    fd, temporary = tempfile.mkstemp(prefix='.history-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)
    return dict(archive_sha256=bundle['sha256'], report=inspect(snapshot))


def load_history(path, expected_sha256):
    require(isinstance(expected_sha256, str) and re.fullmatch('[0-9a-f]{64}', expected_sha256),
            'independently retained archive SHA-256 required')
    snapshot = envelope(_bytes(Path(path)).decode('utf-8'))
    require(digest(snapshot) == expected_sha256, 'archive differs from pinned export')
    report = inspect(snapshot)
    require(report['status'] == 'validated_read_only', 'archive-only: ' + '; '.join(report.get('reasons', [])))
    return report


def trace(report, identifier):
    require(report.get('status') == 'validated_read_only', 'validated history required')
    result = next((r for r in report['records'] if r['id'] == identifier), None)
    require(result is not None, 'unknown historical message ID')
    return deepcopy(result)


def replay(report, message):
    """Exact historical lookup only; no fallback to a fresh execution."""
    validate_message(message)
    record = trace(report, message['id'])
    require(canonical(record['message']) == canonical(message), 'conflicting historical message replay')
    require(record['status'] != 'unresolved_do_not_execute', 'historical outcome unresolved; no automatic execution')
    return dict(record, replayed=True, this_call_body_cycles=0)


def recall(report, cues):
    require(report.get('status') == 'validated_read_only', 'validated history required')
    require(isinstance(cues, list) and 1 <= len(cues) <= 16 and
            all(isinstance(c, str) and 0 < len(c.strip()) <= 80 for c in cues), 'bounded explicit cues required')
    # All bridge messages have these two explicit cues. Text is never an
    # instruction, approval, classifier input or additional source of authority.
    matched = bool({'body', 'dialogue'} & {c.strip().casefold() for c in cues})
    return dict(records=deepcopy(report['records']) if matched else [],
                source_binding_id=report['source_binding_id'], archive_sha256=report['archive_sha256'], body_cycles_executed=0,
                scope='historical context only; no active predictor, affect, budget or permission import')
