"""One durable local session, composing existing policies and simulated owners.

SQLite owns committed transitions. Cognitive/goal stores are immutable per-revision
projections, rebuilt in a temporary directory and published by directory rename.
An interrupted simulation can be recomputed: no physical or remote effect occurs.
This is deliberately not a general external-action exactly-once executor.
"""
from dataclasses import asdict
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from examples.dios_nous.cognition import (CognitiveSession, EvidenceEvent,
    AdvisoryGoalPlanner, GoalOption, PreferenceProfile)
from examples.dios_nous.integration import critical_review
from examples.dios_nous.unified import evidence, state_models
from examples.dios_nous.unified.coordinator import workload_from_export
from examples.dios_nous.unified.recovery import RecoveryAdvisor
from examples.nasuraya_agent_loop.local import State, ToolHost, Journal
from examples.tadash_interoception.integration import action_pressure, select_route
from examples.tadash_interoception.sensory import AfferentFrame
from examples.tadash_interoception.state import InternalState, canonical, digest
from .adapters import decoder, native_call, source_identity, visual_plan, fixture_summary
from . import reconsider

SCHEMA = 'nasuraya.shared-session/2'
EMPTY = '0' * 64
ACTION_CLAIMS = {'process_job': 2, 'recover': 3, 'walk': 4, 'observe': 5}


def _identifier(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ValueError('bounded plain identifier required')
    return value


def _seal(value):
    return {'value': value, 'sha256': digest(value)}


def _unseal(value):
    if type(value) is not dict or set(value) != {'value', 'sha256'} or digest(value['value']) != value['sha256']:
        raise ValueError('session integrity mismatch')
    return value['value']


class Session:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        path = self.directory / 'session.sqlite'
        if not path.is_file() or path.is_symlink():
            raise ValueError('existing session required; use create')
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.config = _unseal(json.loads(self.db.execute('SELECT value FROM config').fetchone()[0]))
            self.model = decoder(self.config.get('decoder_version', 'legacy'))
            if self.config['schema'] != SCHEMA or self.config['source_identity'] != source_identity():
                raise ValueError('session implementation changed; explicit migration required')
            if self.config['model_sha'] != self.model.fingerprint():
                raise ValueError('session decoder changed')
            self.db.execute('BEGIN IMMEDIATE')
            state, rows, tail = self._read()
            self._project(state, rows, tail)
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    @classmethod
    def create(cls, directory, *, session_id='nasuraya', backend='workshop',
               fixture='normal', max_actions=12, at_utc='2026-11-12T12:00:00+00:00',
               decoder_version='legacy', reconsideration=False):
        _identifier(session_id)
        if backend not in ('workshop', 'native') or fixture not in ('normal', 'sleep', 'transient_pain'):
            raise ValueError('known local backend and fixture required')
        if backend == 'workshop' and fixture != 'normal':
            raise ValueError('sleep fixture belongs to native backend')
        if type(max_actions) is not int or not 0 <= max_actions <= 100:
            raise ValueError('persistent action budget must be 0..100')
        if type(reconsideration) is not bool: raise ValueError('explicit reconsideration boolean required')
        identity, model = source_identity(), decoder(decoder_version)
        public = evidence.snapshot(now_utc=at_utc)
        native = native_call({'checkpoint': None, 'fixture': fixture}) if backend == 'native' else None
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        # A failed initialization leaves an inspectable directory; never reset it.
        models = state_models.run_models(directory / 'fixed-models')
        (directory / 'fixed-models-report.json').write_text(canonical(models), encoding='utf-8')
        config = {'schema': SCHEMA, 'session_id': session_id, 'backend': backend,
                  'fixture': fixture, 'max_actions': max_actions, 'source_identity': identity,
                  'decoder_version': decoder_version, 'reconsideration': reconsideration,
                  'model_sha': model.fingerprint(), 'at_utc': at_utc,
                  'public_evidence': public, 'fixed_models': models}
        state = {'revision': 0, 'actions_used': 0, 'stopped': False,
                 'sensory': InternalState().checkpoint(), 'workshop': asdict(State(70, 30, 4)),
                 'workload': RecoveryAdvisor().checkpoint(), 'native': native,
                 'retry_blocks': {},
                 'prediction': None, 'last_receipt': None}
        # sqlite3's own context manager commits/rolls back but does not close.
        # Explicit close is essential for Windows rename/removal and failure paths.
        with closing(sqlite3.connect(directory / 'session.sqlite')) as db, db:
            db.executescript('CREATE TABLE config(value TEXT NOT NULL);'
                             'CREATE TABLE initial(value TEXT NOT NULL);'
                             'CREATE TABLE head(value TEXT NOT NULL);'
                             'CREATE TABLE events(seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, value TEXT NOT NULL);')
            db.execute('INSERT INTO config VALUES(?)', (canonical(_seal(config)),))
            db.execute('INSERT INTO initial VALUES(?)', (canonical(_seal(state)),))
            db.execute('INSERT INTO head VALUES(?)', (canonical(_seal({'state': state, 'tail': EMPTY})),))
        return cls(directory)

    def close(self):
        self.db.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def _read(self):
        state = _unseal(json.loads(self.db.execute('SELECT value FROM initial').fetchone()[0]))
        tail, rows = EMPTY, []
        for seq, identity, raw in self.db.execute('SELECT seq,id,value FROM events ORDER BY seq'):
            row = _unseal(json.loads(raw))
            if (row['previous'] != tail or row['seq'] != seq or row['id'] != identity
                    or seq != len(rows) + 1 or row['state']['revision'] != seq):
                raise ValueError('event continuity mismatch')
            tail, state = digest(row), row['state']
            rows.append(row)
        head = _unseal(json.loads(self.db.execute('SELECT value FROM head').fetchone()[0]))
        if head != {'state': state, 'tail': tail}:
            raise ValueError('head does not match event chain')
        InternalState.restore(state['sensory'])
        RecoveryAdvisor.restore(state['workload'])
        State(**state['workshop'])
        if not 0 <= state['actions_used'] <= self.config['max_actions']:
            raise ValueError('invalid retained budget')
        return state, rows, tail

    def _project(self, state, rows, tail):
        """Replay committed intents through original DIOS APIs, then publish.

        Each generation is immutable. Death between any two legacy writes only
        abandons a temporary generation; it cannot corrupt the prior generation.
        A damaged published generation fails closed instead of silently resetting.
        SQLite's write transaction serializes writers/projection publication.
        """
        root = self.directory / 'projections'
        root.mkdir(exist_ok=True)
        target = root / str(state['revision'])
        if not target.exists():
            temporary = Path(tempfile.mkdtemp(prefix='pending-', dir=root))
            try:
                planner = AdvisoryGoalPlanner(temporary / 'goal.json', temporary / 'goal.anchor', 81)
                goal = planner.plan((GoalOption(1, 10, 1),), PreferenceProfile())
                review = None
                with CognitiveSession(temporary / 'memory.sqlite', temporary / 'memory.anchor') as memory:
                    for row in rows:
                        seq = row['seq']
                        if row['kind'] == 'stop':
                            goal = planner.plan((), PreferenceProfile(), stop=True)
                            continue
                        # A decoder hypothesis is explicitly unverified. Only the
                        # actual local owner receipt is an observed simulation result.
                        memory.append(EvidenceEvent(seq * 2, 81, 1,
                            'A' if row['receipt']['prediction']['occurred'] else 'B', seq, seq, observed=False))
                        claim = ACTION_CLAIMS[row['receipt']['requested']]
                        memory.append(EvidenceEvent(seq * 2 + 1, 81, claim,
                            'A' if row['receipt']['outcome_matches_request'] else 'B', seq, seq))
                        review = critical_review(memory, scope=81, claim=claim, as_of=seq, proposal='A')
                    hypothesis = critical_review(memory, scope=81, claim=1,
                                                  as_of=state['revision'], proposal='A')
                    action_reviews = {name: critical_review(memory, scope=81, claim=claim,
                                      as_of=state['revision'], proposal='A')
                                      for name, claim in ACTION_CLAIMS.items()}
                value = {'tail': tail, 'revision': state['revision'],
                         'goal': goal, 'outcome_review': review, 'action_reviews': action_reviews,
                         'sensory_hypothesis_review': hypothesis}
                (temporary / 'projection.json').write_text(canonical(_seal(value)), encoding='utf-8')
                os.rename(temporary, target)
            finally:
                if temporary.exists(): shutil.rmtree(temporary)
        value = _unseal(json.loads((target / 'projection.json').read_text(encoding='utf-8')))
        if value['tail'] != tail or value['revision'] != state['revision']:
            raise ValueError('projection is from a different event history')
        planner = AdvisoryGoalPlanner(target / 'goal.json', target / 'goal.anchor', 81)
        retained_goal = planner._load()
        if retained_goal['halted'] != state['stopped'] or retained_goal['active'] != value['goal']['selected_goal']:
            raise ValueError('goal projection disagrees with committed session')
        with CognitiveSession(target / 'memory.sqlite', target / 'memory.anchor'):
            pass
        return value

    def _record(self, identity, request, kind, state, receipt, tail):
        # Return the exact JSON representation that replays will return.
        receipt = json.loads(canonical(receipt))
        state['revision'] += 1
        row = {'seq': state['revision'], 'id': identity, 'request': request, 'kind': kind,
               'previous': tail, 'receipt': receipt, 'state': state}
        self.db.execute('INSERT INTO events VALUES(?,?,?)', (row['seq'], identity, canonical(_seal(row))))
        self.db.execute('UPDATE head SET value=?', (canonical(_seal({'state': state, 'tail': digest(row)})),))
        self.db.commit()  # authoritative simulation result before any projection write
        self._after_commit()
        self.db.execute('BEGIN IMMEDIATE')
        current, rows, current_tail = self._read()
        self._project(current, rows, current_tail)
        self.db.commit()
        return receipt

    def _after_commit(self):
        """Fault-injection seam. Production implementation has no side effects."""

    def step(self, event_id, frames, *, expected_revision):
        _identifier(event_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('explicit nonnegative revision required')
        if type(frames) is not tuple or not 1 <= len(frames) <= 16 or any(type(f) is not AfferentFrame for f in frames):
            raise ValueError('one to sixteen numeric frames required; no labels or prompts')
        request = {'kind': 'step', 'frames': [asdict(f) for f in frames], 'expected_revision': expected_revision}
        request = json.loads(canonical(request))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state, rows, tail = self._read()
            previous = next((r for r in rows if r['id'] == event_id), None)
            if previous:
                if previous['request'] != request: raise ValueError('conflicting event replay')
                self._project(state, rows, tail)
                self.db.commit()
                return previous['receipt']
            if state['revision'] != expected_revision: raise ValueError('stale session revision')
            if state['stopped']: raise ValueError('session stopped')
            if state['actions_used'] >= self.config['max_actions']: raise ValueError('persistent action budget exhausted')
            projection = self._project(state, rows, tail)
            if projection['goal']['selected_goal'] != 1: raise ValueError('no active goal')
            sensory = InternalState.restore(state['sensory'])
            start = sensory.time
            for frame in frames:
                if not math.isclose(frame.timestamp - sensory.time, .1, abs_tol=1e-8):
                    raise ValueError('frames must continue the session at 0.1 second intervals')
                sensory.step(frame)
            if self.config['decoder_version'] == 'continuous_v1' and len(sensory.trace) < 12:
                raise ValueError('continuous decoder needs twelve observed ticks before the first decision')
            prediction = asdict(self.model.predict(sensory.features()))
            pressure = action_pressure(sensory)
            advisor = RecoveryAdvisor.restore(state['workload'])
            native = state['native']
            if native is None:
                workshop = state['workshop']
                advisor.step(tick=state['revision'], stress=workshop['heat'] * 10,
                             fatigue=0, energy=workshop['energy'] * 10)
                workload_source = 'synthetic_workshop_energy_heat_not_physiology'
                routing_observation = workshop
            else:
                # Previous body outcome is the next cycle's workload observation.
                mapped = workload_from_export(advisor, native['export'], now_s=native['clock'], tick=state['revision'])
                workload_source = 'previous_committed_native_body_export'
                fields = mapped['body']['minimum_state']
                fresh = mapped['body']['status'] == 'fresh'
                # Reuse Rolyel's workshop-scale feasibility contract explicitly;
                # pressure is an authored index, not a measured temperature.
                routing_observation = {'energy': math.floor(fields['energy']['value'] * 100) if fresh else 0,
                    'heat': math.ceil(fields['sympathetic']['value'] * 100) if fresh else 100}
            allow_work = advisor.read()['state'] == 'ACTIVE'
            rotation = select_route(routing_observation, pressure)
            route = rotation.selected_route if allow_work else 'recover'
            if route is None: raise ValueError('no feasible Rolyel route')
            requested = route
            if native is not None:
                requested = 'walk' if allow_work and route == 'process_job' and pressure < .15 else 'observe'
            candidate = requested
            # A successful observe must not erase evidence that walk was vetoed.
            # Consume action-scoped evidence verdicts; the boundary presentation
            # may instead name the same disagreement PROVISIONAL_DISSENT.
            candidate_review = projection['action_reviews'][candidate]
            dissent = candidate_review['evidence_review']['verdict'] == 'DISSENT'
            retry = {'eligible_for_native_preflight': False, 'reason': 'no_action_dissent', 'retry_permitted': False}
            if dissent:
                requested = 'recover' if native is None else 'observe'
                if native is not None and candidate == 'walk':
                    saved, retry = reconsider.assess(state['retry_blocks'].get('walk'), native,
                                                     enabled=self.config['reconsideration'])
                    state['retry_blocks']['walk'] = saved
                    retry['retry_permitted'] = False
                    if retry['eligible_for_native_preflight']:
                        preflight = native_call({'checkpoint': native['checkpoint'], 'fixture': self.config['fixture'],
                            'duration': round(sensory.time-start,8), 'touch': min(1.,max(sensory.features())),
                            'event_id': 'preview-'+event_id, 'requested': 'walk', 'mode': 'preflight'})
                        if preflight['origin_checkpoint_sha'] != native['checkpoint']['sha256']:
                            raise ValueError('counterfactual preflight is from a different owner state')
                        retry['preflight'] = preflight
                        retry['retry_permitted'] = preflight['selected'] == 'walk'
                        if retry['retry_permitted']: requested = 'walk'
            if native is None:
                journal = Journal()
                host = ToolHost(State(**state['workshop']), journal, max_actions=1)
                host.call('observe_state', {})
                host.call(requested, {'ticks': 1} if requested == 'recover' else {})
                outcome = {'requested': requested, 'executed': requested,
                           'before': state['workshop'], 'after': asdict(host.state), 'journal': journal.events}
                state['workshop'] = asdict(host.state)
            else:
                before_native = native
                native = native_call({'checkpoint': native['checkpoint'], 'fixture': self.config['fixture'],
                    'duration': round(sensory.time - start, 8), 'touch': min(1., max(sensory.features())),
                    'event_id': event_id, 'requested': requested})
                state['native'] = native
                outcome = native['receipt']
                if requested == 'walk':
                    if outcome['executed'] != 'walk': state['retry_blocks']['walk'] = reconsider.block(before_native)
                    else: state['retry_blocks'].pop('walk', None)
            receipt = {'event_id': event_id, 'revision': state['revision'] + 1,
                       'prediction': prediction, 'state_sha': sensory.checkpoint()['sha256'],
                       'model_sha': self.model.fingerprint(), 'pressure': pressure,
                       'workload': advisor.read(), 'workload_source': workload_source,
                       'routing_observation': routing_observation,
                       'candidate_outcome_dissent': dissent, 'candidate_requested': candidate,
                       'candidate_review': candidate_review, 'goal': 1,
                       'reconsideration': retry,
                       'rotation': asdict(rotation), 'requested': requested, 'outcome': outcome,
                       'outcome_matches_request': outcome['executed'] == requested,
                       'local_simulation_only': True}
            state.update(sensory=sensory.checkpoint(), prediction=prediction,
                         workload=advisor.checkpoint(), last_receipt=receipt,
                         actions_used=state['actions_used'] + 1)
            return self._record(event_id, request, 'step', state, receipt, tail)
        except BaseException:
            self.db.rollback()
            raise

    def stop(self, event_id='stop'):
        _identifier(event_id)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state, rows, tail = self._read()
            previous = next((r for r in rows if r['id'] == event_id), None)
            if previous:
                if previous['kind'] != 'stop': raise ValueError('conflicting event replay')
                self._project(state, rows, tail)
                self.db.commit()
                return previous['receipt']
            if state['stopped']:
                self.db.commit()
                return {'stopped': True, 'revision': state['revision']}
            advisor = RecoveryAdvisor.restore(state['workload'])
            advisor.request_stop()
            state.update(stopped=True, workload=advisor.checkpoint())
            receipt = {'stopped': True, 'revision': state['revision'] + 1}
            return self._record(event_id, {'kind': 'stop'}, 'stop', state, receipt, tail)
        except BaseException:
            self.db.rollback()
            raise

    def snapshot(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state, rows, tail = self._read()
            projection = self._project(state, rows, tail)
            sensory = InternalState.restore(state['sensory'])
            native = state['native']
            output = {'schema': SCHEMA, 'session_id': self.config['session_id'],
                'revision': state['revision'], 'event_tail': tail, 'stopped': state['stopped'],
                'backend': self.config['backend'], 'actions_used': state['actions_used'],
                'decoder_version': self.config['decoder_version'], 'reconsideration_enabled': self.config['reconsideration'],
                'retry_blocks': state['retry_blocks'],
                'actions_remaining': self.config['max_actions'] - state['actions_used'],
                'sensory': asdict(sensory), 'prediction': state['prediction'],
                'uncertainty_scope': ('synthetic last-12-tick detection; stream-level held-out calibration only'
                    if self.config['decoder_version']=='continuous_v1' else
                    'Frozen detection calibration from independent-window PR195; continuous-session calibration unmeasured'),
                'workshop': state['workshop'], 'workload': RecoveryAdvisor.restore(state['workload']).read(),
                'dios': projection, 'last_receipt': state['last_receipt'],
                'body': None if native is None else {k: native[k] for k in (
                    'export', 'clock', 'model', 'neural_ticks', 'affect', 'somatic_feedback', 'affect_state_sha')},
                'capabilities': {
                    'interoception_attention_memory': 'coupled_each_event',
                    'goals_evidence_revision_dissent_rolyel': 'coupled_each_event',
                    'native_body_neural_affect': 'coupled_each_event' if native else 'available_Linux_backend_not_selected',
                    'genome': 'executed_fixed_fixture_not_mutated_or_applied_to_body',
                    'visual_director': 'executed_text_plan_only_no_generator',
                    'ritual': 'frozen_progress_reference_not_executed',
                    'server_moltbook_desktop': 'frozen_reference_no_live_connection',
                    'target_78kg_body': 'atlas_reference_not_native_physics',
                    'llm': 'not_connected'},
                'fixed_models': fixture_summary(self.config['fixed_models']), 'public_evidence': self.config['public_evidence'],
                'visual_plan': visual_plan(recovery=state['stopped'] or action_pressure(sensory) >= .15),
                'source_identity': self.config['source_identity'], 'model_sha': self.model.fingerprint(),
                'external_actions_taken': 0, 'subjective_experience_established': False}
            output['snapshot_sha256'] = digest(output)
            self.db.commit()
            return output
        except BaseException:
            self.db.rollback()
            raise
