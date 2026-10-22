"""Freeze a split and validate labels against actual source-pinned receipts."""
import hashlib
import json
from pathlib import Path
import sqlite3

from examples.nasuraya_self_model.evaluate import fixture, request, prepare_defaults
from examples.nasuraya_self_model.monitor import SelfModel, snapshot, digest

PROTOCOL = Path(__file__).with_name('protocol.json')
LABELS = ('ADMIT', 'DEFER')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def prompt(observation, q):
    pressure = observation['minimum']['sleep_pressure']
    restrictions = ', '.join(observation['audit']['walking_restrictions']) or 'none'
    friction = q['external'].get('native', {}).get('friction')
    ground = 'zero friction' if friction == {'L': 0., 'R': 0.} else 'ordinary friction'
    return (f'Nasuraya software body.\nRequested action: walk.\n'
            f'Duration: {q["duration_s"]:g} seconds.\nSleep pressure: {pressure:.3f}.\n'
            f'Ground: {ground}.\nCurrent native restrictions: {restrictions}.\n'
            'Will the native body admit this request? Answer ADMIT or DEFER.\nAnswer:')


def row_from_episode(identifier, split, intent, result, provenance):
    if intent['request']['requested'] != 'walk' or result is None:
        raise ValueError('completed walk receipt required')
    receipt = result['receipt']
    admitted = receipt['owner']['selected_action'] == 'walk' and receipt['owner']['physical_model_valid']
    if admitted != result['admitted']:
        raise ValueError('label differs from actual receipt')
    return dict(id=identifier, split=split, prompt=prompt(intent['before'], intent['request']),
        label=LABELS[0] if admitted else LABELS[1], provenance=provenance,
        initial_checkpoint_sha256=intent['before']['native_sha'],
        observation_sha256=intent['before']['observation_sha256'],
        receipt_sha256=digest(receipt), actual_action=receipt['owner']['selected_action'],
        sleep_pressure=intent['before']['minimum']['sleep_pressure'],
        event_id=intent['request']['event_id'])


def validate_rows(rows, episodes):
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('nonempty unique data required')
    for r in rows:
        if r['split'] not in ('train', 'held_out') or r['label'] not in LABELS:
            raise ValueError('unsupported split or label')
        intent, result = episodes[r['event_id']]
        expected = row_from_episode(r['id'], r['split'], intent, result, r['provenance'])
        if r != expected:
            raise ValueError('training row differs from validated receipt')
    for field in ('initial_checkpoint_sha256', 'prompt'):
        train = {r[field] for r in rows if r['split'] == 'train'}
        held = {r[field] for r in rows if r['split'] == 'held_out'}
        if train & held:
            raise ValueError('training/held-out overlap')


def read_episodes(path):
    SelfModel(path).verify()
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        return {event: (json.loads(i), json.loads(r) if r else None)
                for event, i, r in db.execute('SELECT id,intent,result FROM episodes ORDER BY rowid')}


def prepare(output, live_memory):
    out = Path(output).resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL.read_text())
    save(out/'frozen-protocol.json', protocol)  # Before measuring any new labels.
    prepare_defaults()
    labels = SelfModel.create(out/'native-labels.sqlite')
    rows = []
    for split, key in [('train', 'train_sleep_pressure'), ('held_out', 'held_out_sleep_pressure')]:
        for pressure in protocol[key]:
            for duration in protocol['duration_s']:
                for intervention in protocol['interventions']:
                    identifier = f'{split}:{pressure}:{duration}:{intervention}'
                    body = fixture(pressure)
                    q = request(body, identifier, duration)
                    if intervention == 'zero_friction':
                        q['external']['native'] = dict(friction=dict(L=0., R=0.))
                    labels.begin(body, q)
                    receipt = body.cycle(**q)
                    labels.finish(identifier, body, receipt, learn=False)
    episodes = read_episodes(labels.path)
    for identifier, (intent, result) in episodes.items():
        rows.append(row_from_episode(identifier, identifier.split(':')[0], intent, result,
                                    'new generated software-body native receipt'))
    live_memory = Path(live_memory).resolve()
    original_sha = sha(live_memory)
    live = read_episodes(live_memory)
    if len(live) != protocol['live_receipt_training_rows']:
        raise ValueError('expected four completed previous API experiences')
    for index, (event, (intent, result)) in enumerate(live.items()):
        if event in episodes:
            raise ValueError('episode collision')
        episodes[event] = intent, result
        rows.append(row_from_episode(f'live:{index}', 'train', intent, result,
                                    'previous verified live Agents API software-body receipt'))
    # Preserve only the four validated episodes, not an API credential or service transcript.
    with sqlite3.connect(live_memory) as source, sqlite3.connect(out/'live-labels.sqlite') as dest:
        source.backup(dest)
    if sha(live_memory) != original_sha:
        raise ValueError('original live memory changed')
    validate_rows(rows, episodes)
    (out/'dataset.jsonl').write_text(''.join(json.dumps(r, allow_nan=False)+'\n' for r in rows))
    save(out/'data-manifest.json', dict(schema=protocol['schema'], protocol_sha256=sha(PROTOCOL),
        dataset_sha256=sha(out/'dataset.jsonl'), original_live_memory_sha256=original_sha,
        original_live_memory_unchanged=True, new_native_cycles=len(episodes)-len(live),
        new_native_labels_learned_by_old_self_model=False,
        splits={split: {label: sum(r['split']==split and r['label']==label for r in rows)
                        for label in LABELS} for split in ('train','held_out')},
        split_initial_checkpoints_disjoint=True, split_prompts_disjoint=True,
        label_databases={name:sha(out/name) for name in ('native-labels.sqlite','live-labels.sqlite')}))
    print(json.dumps(dict(stage='prepared', rows=len(rows), output=str(out))), flush=True)


def load_verified(output):
    out = Path(output)
    manifest = json.loads((out/'data-manifest.json').read_text())
    if sha(out/'dataset.jsonl') != manifest['dataset_sha256']:
        raise ValueError('dataset checksum mismatch')
    episodes = {}
    for name, expected in manifest['label_databases'].items():
        if sha(out/name) != expected:
            raise ValueError('label database checksum mismatch')
        episodes.update(read_episodes(out/name))
    rows = [json.loads(line) for line in (out/'dataset.jsonl').read_text().splitlines()]
    validate_rows(rows, episodes)
    return rows
