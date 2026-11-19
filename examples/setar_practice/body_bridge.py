"""Explicit, bounded orchestration of synthetic audio practice by a BodyLoop.

The native action remains 'observe'. This is NOT a hand actuator, continuous
scheduler, physical cost model, or synchronization of audio and body clocks.
The caller must hold BodyLoop's session lock for this object's lifetime.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

from .skill import SetarSkill, atomic_json, checkpoint, read_controller, sha

BIND = 'nasuraya.setar/binding/1'
RUN = 'nasuraya.setar/run/1/'
# Conservative engineering policy on the existing normalized fixture proxies.
# These are not measured human physiology or musical proficiency thresholds.
LIMITS = {'energy': (.20, 1.), 'hydration': (.30, 1.),
          'fatigue': (0., .75), 'pain': (0., .70), 'sleep_pressure': (0., .80)}


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def readiness(snapshot):
    state = snapshot.get('minimum_state', {})
    reasons = []
    for key, (low, high) in LIMITS.items():
        value = state.get(key)
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not low <= value <= high):
            reasons.append(key)
    return {'allowed': not reasons, 'reasons': reasons,
            'policy': 'declared engineering proxy gate, not clinical thresholds'}


class SetarBodyBridge:
    def __init__(self, loop):
        self.loop = loop
        self.db = loop.engine.db
        if self.db.in_transaction:
            raise ValueError('bridge requires the body host autocommit boundary')

    def _read(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _write(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, encode(value)))

    def _runs(self):
        return [json.loads(row[0]) for row in self.db.execute(
            'SELECT value FROM meta WHERE key LIKE ? ORDER BY key', (RUN + '%',))]

    def _binding(self):
        value = self._read(BIND)
        if value is None:
            raise ValueError('explicit setar binding required')
        return value

    def bind(self, checkpoint_path=None, *, max_steps=3):
        if self._read(BIND) is not None:
            raise ValueError('already bound; budgets and learned memory cannot be reset')
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValueError('max_steps must be an integer in 1..100')
        if self.loop.status()['mode'] != 'bounded':
            raise ValueError('binding requires a bounded body session')
        skill = SetarSkill(checkpoint_path)
        data = checkpoint(skill.controller, skill.parent_sha256)
        self._write(BIND, {'schema': BIND, 'max_steps': max_steps,
            'initial_updates': data['total_updates'], 'checkpoint': data})
        return self.status()

    def status(self):
        binding = self._read(BIND)
        runs = self._runs()
        return {'bound': binding is not None, 'scope': 'body-gated synthetic audio',
            'total_updates': binding['checkpoint']['total_updates'] if binding else None,
            'attempts_reserved': len(runs),
            'attempts_remaining': max(0, binding['max_steps'] - len(runs)) if binding else 0,
            'unresolved_runs': [r['run_id'] for r in runs if r['state'] == 'running'],
            'physical_hand_control': False, 'automatically_scheduled': False,
            'audio_and_body_clocks_synchronized': False}

    def evaluate(self):
        binding = self._binding()
        before = encode(binding)
        with tempfile.TemporaryDirectory(prefix='setar-read-only-') as folder:
            path = Path(folder) / 'checkpoint.json'
            atomic_json(path, binding['checkpoint'])
            result = SetarSkill(path).evaluate()
        if before != encode(self._binding()):
            raise RuntimeError('evaluation changed the bound skill')
        return {'binding_unchanged': True, 'native_cycles_caused': 0,
                'evaluation': result}

    def step(self, run_id, output, *, realtime, seed=4110000):
        if not isinstance(run_id, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id) is None:
            raise ValueError('run_id must be 1..64 ASCII letters, digits, dots, dashes or underscores')
        if type(realtime) is not bool or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('explicit timing mode and bounded integer seed required')
        out = Path(output).absolute()
        request = {'run_id': run_id, 'output': str(out), 'realtime': realtime, 'seed': seed}
        request_hash = hashlib.sha256(encode(request).encode()).hexdigest()
        binding = self._binding()
        previous = self._read(RUN + run_id)
        if previous is not None:
            if previous['request_sha256'] != request_hash:
                raise ValueError('conflicting setar replay')
            if previous['state'] == 'running':
                raise RuntimeError('unresolved setar execution; do not replay automatically')
            return {**previous, 'replayed': True}
        current = self.status()
        if current['unresolved_runs']:
            raise RuntimeError('reconcile unresolved setar execution before new work')
        body_status = self.loop.status()
        if body_status['mode'] != 'bounded' or body_status['unresolved_running']:
            raise ValueError('body is read-only or has an unresolved execution')
        if current['attempts_remaining'] <= 0 or body_status['actions_remaining'] <= 0:
            raise ValueError('persistent skill or native action budget exhausted')
        if out.exists() or out.is_symlink():
            raise ValueError('fresh output directory required')
        record = {'run_id': run_id, 'request_sha256': request_hash, 'request': request,
            'state': 'running', 'replayed': False, 'native_cycles_caused': 0,
            'physical_hand_control': False, 'checkpoint_committed': False}
        self._write(RUN + run_id, record)  # Durable reservation before any effect.
        try:
            out.mkdir(mode=0o700, parents=True, exist_ok=False)
            snapshot = self.loop.observe()
            record['readiness_before'] = readiness(snapshot)
            record['body_observation_sha256'] = snapshot['checkpoint_sha256']
            if not record['readiness_before']['allowed']:
                record.update(state='deferred', reason='body_proxy_gate')
            else:
                receipt = self.loop.step(decision_id='setar-gate:' + run_id,
                                         preferred_action='observe', duration_s=.1)
                record['native_receipt'] = receipt
                record['native_cycles_caused'] = int(receipt['status'] == 'complete')
                allowed = (receipt['status'] == 'complete'
                    and receipt['requested_action'] == receipt['actual_action'] == 'observe')
                record['readiness_after'] = readiness(receipt['self_model_after'])
                if not allowed or not record['readiness_after']['allowed']:
                    record.update(state='deferred', reason='native_gate_or_postcycle_state')
                else:
                    parent = out / 'parent_checkpoint.json'
                    atomic_json(parent, binding['checkpoint'])
                    summary = SetarSkill(parent).practice(out / 'practice', episodes=1,
                                                         realtime=realtime, seed=seed)
                    saved = out / 'practice' / 'checkpoint.json'
                    controller = read_controller(saved)
                    updated = deepcopy(binding)
                    updated['checkpoint'] = checkpoint(controller, sha(parent))
                    if (sha(saved) != summary['checkpoint_sha256']
                            or updated['checkpoint']['total_updates'] != summary['total_updates']
                            or summary['inherited_updates'] != binding['checkpoint']['total_updates']):
                        raise RuntimeError('practice receipt and checkpoint disagree')
                    record.update(state='completed', summary=summary, checkpoint_committed=True,
                        native_gate_seconds=.1, scheduled_audio_seconds=10.,
                        audio_and_body_clocks_synchronized=False)
                    # Skill progress and completion receipt become visible together.
                    self.db.execute('BEGIN IMMEDIATE')
                    try:
                        self._write(BIND, updated)
                        self._write(RUN + run_id, record)
                        self.db.execute('COMMIT')
                    except BaseException:
                        self.db.execute('ROLLBACK')
                        raise
            if record['state'] == 'deferred':
                self._write(RUN + run_id, record)
        except BaseException as exc:
            # No automatic replay. The last committed binding remains authoritative.
            record.update(state='failed_or_interrupted', exception_type=type(exc).__name__,
                          checkpoint_committed=False, replay_automatically=False)
            self._write(RUN + run_id, record)
            raise
        # The ledger, not this convenience copy, is the authoritative receipt.
        try:
            atomic_json(out / 'bridge_receipt.json', record)
        except OSError:
            record = {**record, 'receipt_copy_written': False}
        return record
