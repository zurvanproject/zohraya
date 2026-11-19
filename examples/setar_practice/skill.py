"""Explicit, offline skill adapter with durable, validated calibration memory.

No imports into the body runtime, remote execution, cron, API or model training.
Every run writes a new directory. Evaluation never trains. A restart may start
a NEW run from a completed checkpoint; unfinished runs are not replayed.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
from . import engine

DATA = Path(__file__).with_name('data')
SCHEMA = 'zohraya.setar.checkpoint.v1'
SKILL_ID = 'synthetic_setar_controller'
SEED_SHA256 = '01ab60d21ba34c628542ad1ae5a75d14573431dd257d4b70d8f64608f339fe31'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _finite(value: object, lower: float, upper: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def validate_controller(data: dict) -> None:
    expected = set(engine.Controller.__dataclass_fields__)
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError('Unexpected controller schema')
    for name in ('updates', 'inherited_updates', 'rejected_observations'):
        if not _integer(data[name]):
            raise ValueError('Invalid update counter: ' + name)
    if data['interpolate'] is not True:
        raise ValueError('This skill requires the v0.3 interpolating controller')
    for name, limits in [('timing_s', (-.085, .035)), ('attack_gain', (.4, 1.8))]:
        table = data[name]
        if not isinstance(table, dict) or set(table) != set(engine.DIRECTIONS):
            raise ValueError('Invalid stroke table')
        if not all(_finite(v, *limits) for v in table.values()):
            raise ValueError('Nonfinite or out-of-range ' + name)
    pitch = data['pitch_cents']
    if not isinstance(pitch, dict) or not pitch:
        raise ValueError('Missing calibration nodes')
    for key, value in pitch.items():
        try:
            string, fret = key.split(':')
            target = float(fret)
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Invalid node key') from None
        if string not in ('1', '2') or target not in engine.TRAIN_FRETS:
            raise ValueError('Unsupported training node')
        if key != engine.key(int(string), target) or not _finite(value, -100., 100.):
            raise ValueError('Invalid calibration value')
    nodes = data['node_updates']
    if not isinstance(nodes, dict) or not set(nodes).issubset(pitch):
        raise ValueError('Invalid node counters')
    if not all(_integer(v) for v in nodes.values()) or sum(nodes.values()) != data['updates']:
        raise ValueError('Node counts do not match new updates')


def read_controller(path: Path) -> engine.Controller:
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError('Checkpoint must be an object')
    if 'schema' in raw:
        if raw.get('schema') != SCHEMA or raw.get('skill_id') != SKILL_ID:
            raise ValueError('Foreign checkpoint')
        data = raw.get('controller')
        validate_controller(data)
        if type(raw.get('total_updates')) is not int or raw['total_updates'] != data['inherited_updates'] + data['updates']:
            raise ValueError('Cumulative count mismatch')
    elif 'inherited_updates' in raw:
        data = raw
        validate_controller(data)
    else:
        required = {'pitch_cents', 'timing_s', 'attack_gain', 'updates', 'rejected_observations'}
        if not required.issubset(raw) or set(raw) - required - {'provenance'}:
            raise ValueError('Unrecognized cumulative parent format')
        if not _integer(raw['updates']) or not _integer(raw['rejected_observations']):
            raise ValueError('Invalid imported counters')
        data = asdict(engine.Controller(
            pitch_cents=raw['pitch_cents'], timing_s=raw['timing_s'], attack_gain=raw['attack_gain'],
            inherited_updates=raw['updates'], rejected_observations=raw['rejected_observations']))
        validate_controller(data)
    return engine.Controller(**data)


def checkpoint(controller: engine.Controller, parent_digest: str) -> dict:
    data = asdict(controller)
    validate_controller(data)
    return {'schema': SCHEMA, 'skill_id': SKILL_ID, 'engine_version': '0.3.1',
            'controller': data, 'total_updates': controller.inherited_updates + controller.updates,
            'parent_checkpoint_sha256': parent_digest, 'physical_body_integration': False}


class SetarSkill:
    def __init__(self, parent: Path | str | None = None):
        self.parent = Path(parent) if parent is not None else DATA / 'seed_v03.json'
        if parent is None and sha(self.parent) != SEED_SHA256:
            raise ValueError('Bundled seed checksum mismatch')
        self.parent_sha256 = sha(self.parent)
        self.controller = read_controller(self.parent)

    def status(self) -> dict:
        ctl = self.controller
        return {'skill_id': SKILL_ID, 'version': '0.3.1', 'mode': 'offline_synthetic_audio',
                'inherited_updates': ctl.inherited_updates, 'new_updates': ctl.updates,
                'total_updates': ctl.inherited_updates + ctl.updates,
                'calibration_nodes': len(ctl.pitch_cents), 'parent_sha256': self.parent_sha256,
                'body_runtime_connected': False, 'remote_server_execution': False,
                'automatically_scheduled': False}

    def evaluate(self) -> dict:
        before = asdict(self.controller)
        result, rows = engine.evaluate(self.controller, engine.HOLDOUT_FRETS)
        if before != asdict(self.controller) or sha(self.parent) != self.parent_sha256:
            raise RuntimeError('Evaluation changed memory')
        return {'kind': 'read_only_evaluation', 'status': self.status(), 'summary': result,
                'rows': rows, 'checkpoint_unchanged': True}

    def practice(self, output: Path | str, *, episodes: int = 60, realtime: bool = False, seed: int = 4110000) -> dict:
        if type(episodes) is not int or not 1 <= episodes <= 60:
            raise ValueError('episodes must be an integer in 1..60')
        if type(realtime) is not bool or type(seed) is not int or seed < 0:
            raise ValueError('Invalid scheduling or seed')
        if sha(self.parent) != self.parent_sha256:
            raise ValueError('Parent changed after loading')
        out = Path(output)
        out.mkdir(mode=0o700, parents=True, exist_ok=False)
        # A fresh session inherits every previous update exactly once.
        old = self.controller
        ctl = engine.Controller(pitch_cents=dict(old.pitch_cents), timing_s=dict(old.timing_s),
                attack_gain=dict(old.attack_gain), inherited_updates=old.inherited_updates + old.updates)
        started = datetime.now(timezone.utc).isoformat()
        start, cpu_start = time.monotonic(), time.process_time()
        audio = engine.np.zeros(round((episodes * 10. + 1.2) * engine.SR), dtype=engine.np.float32)
        count = 0
        def pace(target: float) -> None:
            if realtime:
                delay = start + target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        atomic_json(out / 'checkpoint.json', checkpoint(ctl, self.parent_sha256))
        atomic_json(out / 'status.json', {'state': 'running', 'realtime': realtime, 'started_utc': started})
        try:
            with (out / 'events.jsonl').open('x', encoding='utf-8') as log:
                for episode in range(episodes):
                    stage, events = engine.exercise(episode)
                    for event in events:
                        scheduled = episode * 10. + event['onset_s']
                        pace(scheduled)
                        actual = time.monotonic() - start
                        note_seed = seed + episode * 100 + event['index']
                        stem, measured, command = engine.render_observe(event, ctl, engine.np.random.default_rng(note_seed))
                        ctl.observe(event, measured)
                        engine.mix_stem(audio, stem, scheduled)
                        log.write(json.dumps({'episode': episode + 1, 'stage': stage, 'seed': note_seed,
                            'scheduled_s': scheduled, 'actual_wall_s': actual, 'event': event,
                            'measurement': measured, 'command': command}, allow_nan=False) + '\n')
                        count += 1
                    pace((episode + 1) * 10.)
                    log.flush()
                    os.fsync(log.fileno())
                    atomic_json(out / 'checkpoint.json', checkpoint(ctl, self.parent_sha256))
            elapsed, cpu = time.monotonic() - start, time.process_time() - cpu_start
            if sha(self.parent) != self.parent_sha256:
                raise RuntimeError('Parent modified during practice')
            audio_meta = engine.write_audio(out / 'practice.wav', audio)
            summary = {'kind': 'setar_skill_session', 'started_utc': started, 'episodes': episodes,
                'note_events': count, 'inherited_updates': ctl.inherited_updates, 'new_updates': ctl.updates,
                'total_updates': ctl.inherited_updates + ctl.updates,
                'rejected_observations': ctl.rejected_observations, 'accelerated': not realtime,
                'scheduled_music_seconds': episodes * 10., 'wall_clock_seconds': elapsed, 'cpu_seconds': cpu,
                'ten_minutes_wall_clock_verified': realtime and episodes == 60 and elapsed >= 600.,
                'parent_checkpoint_sha256': self.parent_sha256, 'checkpoint_sha256': sha(out / 'checkpoint.json'),
                'events_sha256': sha(out / 'events.jsonl'), 'audio': audio_meta,
                'body_runtime_connected': False, 'remote_server_execution': False}
            atomic_json(out / 'summary.json', summary)
            atomic_json(out / 'status.json', {'state': 'completed', 'checkpoint_sha256': summary['checkpoint_sha256']})
            return summary
        except BaseException:
            atomic_json(out / 'status.json', {'state': 'failed_or_interrupted', 'replay_automatically': False,
                'checkpoint_policy': 'last_completed_episode', 'events_may_include_uncommitted_episode': True})
            raise
