"""Actual DIOS memory/revision, goal continuity, Rolyel and local agent calls."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from examples.dios_nous.cognition import (CognitiveSession, EvidenceEvent,
    AdvisoryGoalPlanner, GoalOption, PreferenceProfile)
from examples.dios_nous.integration import critical_review
from examples.dios_nous.dissent import review_decision
from examples.nasuraya_agent_loop.local import Action as ToolAction, FixturePolicy
from runtimes.tadash_body.decision_core import Action, Consequence
from .state import InternalState, digest

_source = (Path(__file__).parent / 'reused/rolyel_v01.py').read_bytes()
if hashlib.sha1(b'blob ' + str(len(_source)).encode() + b'\0' + _source).hexdigest() != '021c752d3cb403211888acb395cd913558249d36':
    raise ValueError('PR185 Rolyel source mismatch')
from .reused.rolyel_v01 import Check, Route, rotate


class DiosObserver:
    """Continuous observer for all runs. Predictions must precede scored truth.

    Its hash chain detects accidental edits given a trusted tail; not authentication.
    Data truth is retained only here, never in the decoder or internal state.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.stream = self.path.open('x', encoding='utf-8')
        self.sequence, self.tail, self.pending = 0, '0' * 64, {}
        self.seen = set()
        self.errors = 0

    def emit(self, kind, **data):
        row = {'sequence': self.sequence, 'previous': self.tail, 'kind': kind, **data}
        self.tail = digest(row)
        self.stream.write(json.dumps(dict(row, sha256=self.tail), sort_keys=True, allow_nan=False) + '\n')
        self.stream.flush()
        self.sequence += 1

    def commit_prediction(self, identity, prediction, *, model_sha, state_sha):
        if identity in self.seen: raise ValueError('prediction already committed')
        self.seen.add(identity)
        self.pending[identity] = prediction
        self.emit('prediction', identity=identity, prediction=asdict(prediction),
                  model_sha=model_sha, state_sha=state_sha)

    def reveal(self, identity, truth):
        if identity not in self.pending: raise ValueError('prediction required before truth')
        prediction = self.pending.pop(identity)
        wrong = prediction.occurred != truth['occurred'] or (truth['occurred'] and
                (prediction.location != truth['location'] or prediction.stimulus_type != truth['type']))
        self.errors += int(wrong)
        review = review_decision({'decision': {'origin': 'agent', 'summary': 'Synthetic interoception prediction'},
                  'observations': ([{'concern': 'contradictory_decision', 'provenance': 'synthetic_test',
                                     'basis': 'Committed prediction disagrees with subsequently revealed fixture'}]
                                   if wrong else [])})
        self.emit('revealed_outcome', identity=identity, truth=truth, wrong=wrong,
                  dios_stance=review['stance'], reasons=review['reason_codes'])

    def close(self):
        if self.pending: raise ValueError('unscored predictions remain')
        self.stream.close()


def correction_gate(directory, baseline, candidate, *, phase=1):
    """Persist actual comparison evidence, then ask existing DIOS to review it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    acceptable = (candidate['brier'] < baseline['brier'] and
                  candidate['accuracy'] >= baseline['accuracy'] - .02)
    with CognitiveSession(directory / 'memory.sqlite', directory / 'memory.anchor') as session:
        session.append(EvidenceEvent(phase, 17, 1, 'A' if acceptable else 'B', phase, phase))
        reviewed = critical_review(session, scope=17, claim=1, as_of=phase, proposal='A')
    return {'accepted': acceptable and reviewed['evidence_review']['decision'] == 'A',
            'baseline': baseline, 'candidate': candidate, 'dios': reviewed,
            'reason': 'validation_gate_passed' if acceptable else 'validation_gate_rejected_rollback',
            'source': 'measured_synthetic_validation_not_external_truth'}


def select_route(observation, pressure):
    """Pure shared policy calculation used by the real bounded host and evaluator."""
    default = FixturePolicy().choose(observation)
    routes = []
    for name in ('recover', 'process_job'):
        feasible = name == 'recover' or default.name == 'process_job'
        benefit = min(1., .1 + 1.5 * pressure) if name == 'recover' else .8
        harm = .01 if name == 'recover' else min(.9, 1.4 * pressure)
        action = Action(name, (Consequence(1., harm, benefit=benefit, confidence=1.),),
                        respect=.8, honesty=.8, balance=.8, dignity=.8, compassion=.8, disharmony=0.)
        routes.append(Route(action, .9, 'Preserve the same synthetic workshop goal',
                            (Check('feasible', feasible, 'local-state://' + digest(observation)),)))
    return rotate('complete workshop safely', 'process_job', routes, ('feasible',))


def action_pressure(state):
    # Memory, attention-filtered sensory state and prediction residual all enter
    # this authored proxy. It is not a pain scale or estimated probability.
    return min(1., state.load + .2 * max(state.features()) + .1 * state.prediction_error)


class SensoryPolicy:
    """Consumes only internal state. Body load can defer work without a prompt.

    The existing ToolHost retains its observation, safety and action budgets.
    Rolyel uses the existing DecisionCore; scores are explicit authored policy.
    """
    def __init__(self, state, directory):
        if type(state) is not InternalState: raise ValueError('internal state required')
        self.state = state
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.planner = AdvisoryGoalPlanner(self.directory / 'goal.json', self.directory / 'goal.anchor', 71)
        self.plan = self.planner.plan((GoalOption(1, 10, 1),), PreferenceProfile())
        self.last_rotation = None

    def choose(self, observation):
        if self.plan['selected_goal'] is None:
            raise ValueError('goal stopped')
        rotation = select_route(observation, action_pressure(self.state))
        self.last_rotation = asdict(rotation)
        if rotation.selected_route is None: raise ValueError('no feasible action')
        return ToolAction(rotation.selected_route,
                          {'ticks': 1} if rotation.selected_route == 'recover' else {},
                          'numeric internal load through Rolyel and DecisionCore')

    def stop(self):
        self.plan = self.planner.plan((), PreferenceProfile(), stop=True)

    def introspect(self, decoder):
        """Agent-facing numeric report; no stimulus metadata or narrative template."""
        from .model import Decoder
        if type(decoder) is not Decoder:
            raise ValueError('numeric Decoder required')
        prediction = decoder.predict(self.state.features())
        return {'internal_load': self.state.load, 'attention': self.state.attention.copy(),
                'prediction_error': self.state.prediction_error,
                'memory_frames': len(self.state.trace), 'inference': asdict(prediction),
                'detection_uncertainty': 1 - max(prediction.probability, 1-prediction.probability),
                'type_confidence_scope': 'conditional_neighbour_vote_not_calibrated',
                'subjective_experience_established': False}

    def native_preference(self):
        """Native API has walk/observe preferences, not a hand withdrawal actuator."""
        return 'observe' if action_pressure(self.state) >= .15 else 'walk'
