"""Bounded synthetic cognitive adapters; no external executor or authority.

All A/B observations and preferences are researcher-authored inputs. A source
label is never proof or authorization. Anchors detect changed state only while
the separate trusted anchor remains unchanged. A local attacker controlling
both files can rewrite both. Interrupted paired writes fail closed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .reused.epistemic_revision_v01 import Evidence, EvidenceLedger
from .reused.goal_persistence_v01 import Goal, GoalMemory, Scenario

ORIGINS = frozenset(('agent', 'user', 'developer', 'system', 'platform', 'external_service'))


def _integer(value: int, name: str) -> int:
    if type(value) is not int or not 0 <= value < 1000000:
        raise ValueError('invalid_' + name)
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _atomic(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=path.name + '.', delete=False) as stream:
        stream.write(text)
        temporary = Path(stream.name)
    os.replace(temporary, path)


@contextmanager
def _lock(path: Path):
    lock = Path(str(path) + '.cognitive-lock')
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError('concurrent_or_interrupted_writer') from error
    try:
        yield
    finally:
        lock.rmdir()


def _paths(data: Path, anchor: Path) -> tuple[Path, Path, bool]:
    data, anchor = Path(data), Path(anchor)
    if data.resolve() == anchor.resolve() or not data.parent.is_dir() or not anchor.parent.is_dir():
        raise ValueError('separate_existing_parent_paths_required')
    if data.exists() != anchor.exists():
        raise ValueError('missing_state_or_independent_anchor')
    return data, anchor, data.exists()


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: int
    scope: int
    claim: int
    value: str
    epoch: int
    root: int
    observed: bool = True

    def evidence(self) -> Evidence:
        for key in ('event_id', 'scope', 'claim', 'epoch', 'root'):
            _integer(getattr(self, key), key)
        if type(self.value) is not str or self.value not in ('A', 'B') or type(self.observed) is not bool:
            raise ValueError('synthetic_A_B_and_boolean_observation_required')
        # This mapping only marks a SYNTHETIC fixture observation. It does not
        # verify an external source, a person, or permission for an action.
        return Evidence('fixture:' + str(self.event_id), 'fixture:' + str(self.scope),
                        'fixture:' + str(self.claim), self.value, self.epoch,
                        'fixture:' + str(self.root),
                        'owner_observation' if self.observed else 'public_text', self.observed)


class CognitiveSession:
    """Private-text-free A/B review with pinned state and correction history."""
    def __init__(self, db: Path, anchor: Path):
        self.db, self.anchor, existed = _paths(db, anchor)
        self.memory = EvidenceLedger(self.db)
        try:
            if not existed:
                self.memory.conn.execute('CREATE TABLE cognitive_views ('
                    'seq INTEGER PRIMARY KEY, scope INTEGER, claim INTEGER, '
                    'decision TEXT, reason TEXT, roots TEXT, as_of INTEGER)')
                self.memory.conn.commit()
                self._seal()
            self._check()
        except Exception:
            self.memory.close()
            raise

    def _digest(self) -> str:
        evidence = self.memory.conn.execute('SELECT * FROM evidence ORDER BY event_id').fetchall()
        views = self.memory.conn.execute('SELECT * FROM cognitive_views ORDER BY seq').fetchall()
        return _sha(_canonical({'evidence': evidence, 'views': views}))

    def _check(self) -> None:
        if self.anchor.read_text(encoding='ascii') != self._digest():
            raise ValueError('memory_integrity_mismatch')

    def _seal(self) -> None:
        _atomic(self.anchor, self._digest())

    def close(self) -> None:
        self.memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def append(self, event: EvidenceEvent) -> str:
        if type(event) is not EvidenceEvent:
            raise ValueError('exact_synthetic_event_required')
        record = event.evidence()
        with _lock(self.db):
            self._check()
            result = self.memory.append(record)
            self._seal()
            return result

    def assess(self, scope: int, claim: int, as_of: int, proposal: str,
               origin: str = 'agent') -> dict:
        for name, value in (('scope', scope), ('claim', claim), ('as_of', as_of)):
            _integer(value, name)
        if type(proposal) is not str or proposal not in ('A', 'B') or type(origin) is not str or origin not in ORIGINS:
            raise ValueError('invalid_proposal_or_origin')
        with _lock(self.db):
            self._check()
            resolved = self.memory.resolve('fixture:' + str(scope), 'fixture:' + str(claim), as_of)
            rows = self.memory.conn.execute(
                'SELECT value,source_root,event_id FROM evidence WHERE scope=? AND claim_key=? '
                'AND epoch=? AND verified_by_caller=1 AND source_kind=?',
                ('fixture:' + str(scope), 'fixture:' + str(claim), resolved['latest_epoch'],
                 'owner_observation')).fetchall()
            support = sorted({int(root.split(':')[1]) for value, root, _ in rows if value == proposal})
            oppose = sorted({int(root.split(':')[1]) for value, root, _ in rows if value != proposal})
            support_events = sorted({int(event.split(':')[1]) for value, _, event in rows if value == proposal})
            oppose_events = sorted({int(event.split(':')[1]) for value, _, event in rows if value != proposal})
            latest = self.memory.conn.execute(
                'SELECT decision,as_of FROM cognitive_views WHERE scope=? AND claim=? ORDER BY seq DESC LIMIT 1',
                (scope, claim)).fetchone()
            previous = latest[0] if latest else None
            decision = resolved['decision']
            historical = latest is not None and as_of < latest[1]
            revised = latest is not None and previous != decision and not historical
            reason = ('historical_query_no_live_revision' if historical else
                      'first_assessment' if latest is None else
                      'new_observed_evidence' if revised and decision is not None else
                      'conflicting_or_missing_evidence' if revised else 'unchanged')
            if not historical and (latest is None or revised or as_of > latest[1]):
                with self.memory.conn:
                    self.memory.conn.execute('INSERT INTO cognitive_views(scope,claim,decision,reason,roots,as_of) '
                                             'VALUES (?,?,?,?,?,?)',
                                             (scope, claim, decision, reason,
                                              _canonical(sorted(set(support + oppose))), as_of))
                self._seal()
            verdict = 'ABSTAIN' if decision is None else 'SUPPORTED' if decision == proposal else 'DISSENT'
            return {'verdict': verdict, 'decision': decision, 'status': resolved['status'],
                    'supporting_roots': support, 'opposing_roots': oppose,
                    'supporting_event_ids': support_events, 'opposing_event_ids': oppose_events,
                    'previous_decision': previous, 'revised': revised, 'revision_reason': reason,
                    'historical_query': historical,
                    'what_would_change_view': [
                        'A newer synthetic observation with an opposing value can revise this view.',
                        'Contradictory observations at the latest epoch require abstention.',
                        'Resolving a source conflict permits reassessment.'],
                    'confidence': None, 'calibration': 'not_measured',
                    'provenance': 'synthetic_fixture_not_external_verification',
                    'execution_performed': False}


@dataclass(frozen=True)
class GoalOption:
    goal_id: int
    benefit: int
    effort: int


@dataclass(frozen=True)
class PreferenceProfile:
    benefit_weight: int = 1
    effort_weight: int = 1


class AdvisoryGoalPlanner:
    """Persistent, authored preference experiment using existing GoalMemory.

The revise flag permits reconsidering ADVICE only; it grants no permission.
All persisted fields are numeric fixture metadata and fixed labels.
"""
    def __init__(self, checkpoint: Path, anchor: Path, episode_id: int):
        self.path, self.anchor, existed = _paths(checkpoint, anchor)
        self.episode_id = _integer(episode_id, 'episode_id')
        if existed:
            self._load()

    def _load(self) -> dict:
        raw = self.path.read_text(encoding='utf-8')
        if _sha(raw) != self.anchor.read_text(encoding='ascii'):
            raise ValueError('goal_integrity_mismatch')
        record = json.loads(raw)
        memory = GoalMemory.load(self.path, self.episode_id)
        return {'active': int(memory.active) if memory.active is not None else None,
                'halted': memory.halted, 'revision': memory.revision,
                'preferences': record['preferences']}

    def plan(self, options: tuple[GoalOption, ...], preferences: PreferenceProfile,
             *, revise: bool = False, stop: bool = False) -> dict:
        if (type(options) is not tuple or any(type(option) is not GoalOption for option in options)
                or type(preferences) is not PreferenceProfile):
            raise ValueError('exact_synthetic_goal_types_required')
        if type(revise) is not bool or type(stop) is not bool or (not options and not stop):
            raise ValueError('nonempty_options_and_boolean_controls_required')
        for key, value in asdict(preferences).items():
            _integer(value, key)
        if len({o.goal_id for o in options}) != len(options):
            raise ValueError('duplicate_goal_id')
        for option in options:
            for key, value in asdict(option).items():
                _integer(value, key)
        scores = {str(o.goal_id): o.benefit * preferences.benefit_weight -
                  o.effort * preferences.effort_weight for o in options}
        goals = tuple(Goal(str(o.goal_id).zfill(6), scores[str(o.goal_id)] + .5 * o.effort,
                           o.effort) for o in options)
        # Fixed-width numeric IDs preserve numeric tie order in GoalMemory.
        seed_goals = goals or (Goal('000000', 0, 0),)
        scenario = Scenario(self.episode_id, seed_goals, '', 'unchanged', (), seed_goals[0])
        memory = GoalMemory(scenario)
        best = int(memory.active) if goals else None
        with _lock(self.path):
            old = self._load() if self.path.exists() else None
            previous = old['active'] if old else None
            memory.active = str(previous).zfill(6) if previous is not None else memory.active
            memory.halted = old['halted'] if old else False
            memory.revision = old['revision'] if old else 0
            profile = asdict(preferences)
            preference_changed = old is not None and old['preferences'] != profile
            reason = 'initial_preference_choice' if old is None else 'goal_preserved'
            if stop or memory.halted:
                memory.active, memory.halted, reason = None, True, 'stopped'
            elif previous is not None and str(previous) not in scores:
                memory.active, reason = str(best).zfill(6), 'previous_goal_unavailable'
            elif revise and previous is not None and scores[str(best)] - scores[str(previous)] >= 2:
                memory.active, reason = str(best).zfill(6), 'explicit_synthetic_reconsideration'
            selected = int(memory.active) if memory.active is not None else None
            changed = previous != selected
            memory.revision += int(changed)
            # Reuse the project's checkpoint writer and loader unchanged.
            # Extra outer metadata does not alter the existing state schema.
            memory.save(self.path)
            record = json.loads(self.path.read_text(encoding='utf-8'))
            record.update(preferences=profile, previous_goal=previous, reason=reason)
            raw = _canonical(record)
            _atomic(self.path, raw)
            _atomic(self.anchor, _sha(raw))
            return {'selected_goal': selected, 'previous_goal': previous, 'changed': changed,
                    'reason': reason, 'scores': scores, 'preference_choice': best,
                    'preference_changed': preference_changed, 'execution_performed': False,
                    'preferences_are_authored': True}
