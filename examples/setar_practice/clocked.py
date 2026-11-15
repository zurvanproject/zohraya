"""Opt-in, one-second body/audio windows with delayed synthetic feedback.

This is blockwise orchestration of observe cycles, not finger dynamics or
sample-rate coupled physiology. Caller holds the existing BodyLoop lock.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import heapq
import os
from pathlib import Path
import re
import time

from . import engine as e
from .body_bridge import BIND, RUN, SetarBodyBridge, encode, readiness
from .skill import atomic_json, checkpoint, read_controller, sha

CURSOR = 'clocked_curriculum_index'
TOTAL_SAMPLES = round(11.2 * e.SR)  # Ten-second score plus its entire decay tail.
WINDOW_ENDS = tuple([i * e.SR for i in range(1, 12)] + [TOTAL_SAMPLES])


class ClockedAudio:
    """Render scheduled notes; release feedback only after a full stem exists.

Audio is generated from isolated synthetic notes. Its feedback is NOT extracted
from the mixed polyphonic output. Controller changes remain provisional until
an entire lesson and its body windows complete.
    """
    def __init__(self, controller, index, seed):
        self.stage, events = e.exercise(index)
        self.controller = e.Controller(pitch_cents=dict(controller.pitch_cents),
            timing_s=dict(controller.timing_s), attack_gain=dict(controller.attack_gain),
            inherited_updates=controller.inherited_updates + controller.updates)
        self.queue = [(round(x['onset_s'] * e.SR), 1, x['index'], x) for x in events]
        heapq.heapify(self.queue)
        self.seed, self.index = seed, index
        self.audio = e.np.zeros(TOTAL_SAMPLES, dtype=e.np.float32)
        self.rows, self.notes, self.feedback = [], 0, 0
        self.samples = 0

    def advance(self, end_sample, *, pace):
        if type(end_sample) is not int or not self.samples < end_sample <= TOTAL_SAMPLES:
            raise ValueError('strictly increasing bounded sample clock required')
        while self.queue and self.queue[0][0] < end_sample:
            tick, kind, index, payload = heapq.heappop(self.queue)
            pace(tick / e.SR)
            if kind == 0:
                event, measurement, rendered_at = payload
                self.controller.observe(event, measurement)
                self.feedback += 1
                self.rows.append(dict(kind='feedback', sample=tick,
                    rendered_at_sample=rendered_at, event_index=index, measurement=measurement))
            else:
                note_seed = self.seed + self.index * 100 + index
                stem, measured, command = e.render_observe(payload, self.controller,
                    e.np.random.default_rng(note_seed))
                available = tick + len(stem)
                if available >= TOTAL_SAMPLES:
                    raise ValueError('note feedback exceeds lesson duration')
                e.mix_stem(self.audio, stem, tick / e.SR)
                heapq.heappush(self.queue, (available, 0, index, (payload, measured, tick)))
                self.notes += 1
                self.rows.append(dict(kind='note', sample=tick, event=payload, seed=note_seed,
                    command=command, feedback_available_sample=available))
        self.samples = end_sample
        pace(end_sample / e.SR)


class ClockedSetarBridge(SetarBodyBridge):
    def status(self):
        result = super().status()
        binding = self._read(BIND)
        index = binding.get(CURSOR, 0) if binding else None
        return {**result, 'clocked_curriculum_index': index,
            'clocked_course_complete': index == 60,
            'clocked_required_native_actions': len(WINDOW_ENDS),
            'clocked_window_seconds': 1.0}

    def lesson(self, run_id, output, *, realtime, seed=4110000):
        if not isinstance(run_id, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id) is None:
            raise ValueError('invalid run_id')
        if type(realtime) is not bool or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('explicit timing mode and bounded integer seed required')
        out = Path(output).absolute()
        request = dict(kind='clocked-setar-v0.5', run_id=run_id, output=str(out), realtime=realtime, seed=seed)
        digest = hashlib.sha256(encode(request).encode()).hexdigest()
        binding = self._binding()
        previous = self._read(RUN + run_id)
        if previous is not None:
            if previous.get('request_sha256') != digest:
                raise ValueError('conflicting setar replay')
            if previous['state'] == 'running':
                raise RuntimeError('unresolved clocked execution; no automatic replay')
            return {**previous, 'replayed': True}
        status, native = self.status(), self.loop.status()
        if status['unresolved_runs'] or native['unresolved_running']:
            raise RuntimeError('unresolved work must be reconciled first')
        if native['mode'] != 'bounded':
            raise ValueError('bounded native body required')
        if status['attempts_remaining'] <= 0 or native['actions_remaining'] < len(WINDOW_ENDS):
            raise ValueError('lesson requires one skill attempt and 12 remaining native actions; budgets are not increased')
        index = binding.get(CURSOR, 0)
        if type(index) is not int or not 0 <= index < 60:
            raise ValueError('clocked curriculum complete or invalid; never wrap automatically')
        if out.exists() or out.is_symlink():
            raise ValueError('fresh output directory required')
        record = dict(run_id=run_id, request_sha256=digest, request=request, state='running',
            replayed=False, curriculum_index=index, native_cycles_caused=0, windows=[],
            approved_audio_seconds=0., body_elapsed_seconds=0., checkpoint_committed=False,
            physical_hand_control=False, sample_rate_body_coupling=False)
        self._write(RUN + run_id, record)
        start, cpu_start = time.monotonic(), time.process_time()
        def pace(target):
            if realtime:
                delay = start + target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        try:
            out.mkdir(parents=True, mode=0o700, exist_ok=False)
            parent = out / 'parent_checkpoint.json'
            atomic_json(parent, binding['checkpoint'])
            audio = ClockedAudio(read_controller(parent), index, seed)
            origin = None
            prior = 0
            for window, end_sample in enumerate(WINDOW_ENDS):
                snapshot = self.loop.observe()
                before = readiness(snapshot)
                if not before['allowed']:
                    record.update(state='deferred', reason='body_proxy_gate', readiness=before)
                    break
                before_time = datetime.fromisoformat(snapshot['simulated_wall_utc'])
                if origin is None:
                    origin = before_time
                if abs((before_time - origin).total_seconds() - prior / e.SR) > 1e-6:
                    raise RuntimeError('native clock changed outside this lesson')
                duration = round((end_sample - prior) / e.SR, 1)
                receipt = self.loop.step(decision_id=f'setar-clock:{run_id}:{window}',
                    preferred_action='observe', duration_s=duration)
                complete = receipt['status'] == 'complete'
                record['native_cycles_caused'] += int(complete and not receipt['replayed'])
                after = receipt['self_model_after']
                elapsed = (datetime.fromisoformat(after['simulated_wall_utc']) - origin).total_seconds()
                record['body_elapsed_seconds'] = elapsed
                record['windows'].append(dict(window=window, duration_s=duration, native_receipt=receipt))
                self._write(RUN + run_id, record)
                if not complete or receipt['actual_action'] != 'observe' or not readiness(after)['allowed']:
                    record.update(state='deferred', reason='native_gate_or_postcycle_state')
                    break
                if receipt['replayed'] or abs(elapsed - end_sample / e.SR) > 1e-6:
                    raise RuntimeError('native clock does not match the audio window')
                # Native state first approves this block; queued note/feedback
                # events then advance monotonically within the same interval.
                audio.advance(end_sample, pace=pace)
                prior = end_sample
                record['approved_audio_seconds'] = end_sample / e.SR
                self._write(RUN + run_id, record)
            with (out / 'events.jsonl').open('x', encoding='utf-8') as handle:
                for row in audio.rows:
                    handle.write(encode(row) + '\n')
                handle.flush()
                os.fsync(handle.fileno())
            record.update(note_events=audio.notes, released_feedback=audio.feedback,
                provisional_updates=audio.controller.updates,
                wall_clock_seconds=time.monotonic() - start, cpu_seconds=time.process_time() - cpu_start,
                accelerated=not realtime, ten_minutes_wall_clock_verified=False)
            if audio.samples:
                record['audio'] = e.write_audio(out / 'practice.wav', audio.audio[:audio.samples])
            if record['state'] == 'running':
                if audio.queue or audio.samples != TOTAL_SAMPLES or audio.notes != audio.feedback:
                    raise RuntimeError('lesson ended with unobserved notes or an incomplete clock')
                saved = checkpoint(audio.controller, sha(parent))
                atomic_json(out / 'checkpoint.json', saved)
                updated = deepcopy(binding)
                updated['checkpoint'], updated[CURSOR] = saved, index + 1
                record.update(state='completed', checkpoint_committed=True,
                    total_updates=saved['total_updates'], next_curriculum_index=index + 1,
                    checkpoint_sha256=sha(out / 'checkpoint.json'), stage=audio.stage,
                    clock_residual_seconds=record['body_elapsed_seconds'] - audio.samples / e.SR,
                    blockwise_clock_aligned=True)
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    self._write(BIND, updated)
                    self._write(RUN + run_id, record)
                    self.db.execute('COMMIT')
                except BaseException:
                    self.db.execute('ROLLBACK')
                    raise
            else:
                record.update(blockwise_clock_aligned=False, replay_automatically=False)
                self._write(RUN + run_id, record)
        except BaseException as exc:
            record.update(state='failed_or_interrupted', exception_type=type(exc).__name__,
                checkpoint_committed=False, replay_automatically=False, blockwise_clock_aligned=False)
            self._write(RUN + run_id, record)
            raise
        # Only the SQLite receipt is authoritative; an export failure cannot
        # turn a committed success into an apparent failed/redoable lesson.
        try:
            atomic_json(out / 'bridge_receipt.json', record)
        except OSError:
            return {**record, 'receipt_copy_written': False}
        return record
