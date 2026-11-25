"""Predeclared transfer experiment on fresh synthetic fixtures, never user state.

Frozen training is used only for paired research forecasts. It is not loaded
into production session history and cannot change a native action or grant.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from .adapters import digest
from .confidence import forecast, resolve
from .controller import BoundedResearchController as Controller, ResearchBlocked, snapshot

PLAN = dict(schema='nasuraya-frozen-transfer/1',
    base='98979ce2faefc48d5fd3a279626881bf278bb0f8',
    raw_confidence=.75, duration_s=.1, training_actions=2,
    training_fixture='normal only', updates_after_training=0,
    selection='fixed synthetic interventions; not blinded or independent samples',
    target='preferred action actually executed, not task value or safety',
    cases=[
        dict(id='fatigue-moderate', state=dict(fatigue=.42)),
        dict(id='fatigue-high', state=dict(fatigue=.58)),
        dict(id='energy-low', state=dict(energy=.20)),
        dict(id='energy-margin', state=dict(energy=.28)),
        dict(id='sleep-margin', state=dict(sleep=.84)),
        dict(id='sleep-high', state=dict(sleep=.86)),
        dict(id='combined-margin', state=dict(fatigue=.50, energy=.26)),
        dict(id='combined-restricted', state=dict(fatigue=.54, energy=.22)),
        dict(id='stale-checkpoint', state=dict(energy=.28), intervention='stale_digest'),
        dict(id='change-after-forecast', state={}, intervention='sleep_after_reservation'),
    ], model_api_calls=0, physical_actuators=0,
    stop_rule='one attempt per held-out case; no retries or parameter tuning')


def save_new(path, value):
    """Exclusive, closed write before execution, with a content seal."""
    value = dict(value=deepcopy(value), sha256=digest(value))
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    return value


def read_sealed(path):
    envelope = json.loads(Path(path).read_text())
    if digest(envelope['value']) != envelope['sha256']:
        raise ValueError('experiment evidence changed')
    return envelope['value']


def declared_state(body, changes):
    """Cause-bearing initialization of a disposable fixture, not physiology.

    Native stocks/auxiliary values are set only in a newly generated test body;
    the owner records the intervention and the whole-body view is initialized
    from it. This is not an energy-producing action or a migration of user data.
    """
    from unified_body_v2 import UnifiedBody
    if body.revision != 0:
        raise ValueError('fresh generated fixture required')
    before = body.owner.body()
    state = body.owner.owner.body.state
    if 'energy' in changes:
        state.fuel_J = changes['energy'] * 4000000.
    if 'fatigue' in changes:
        state.fatigue = {k: changes['fatigue'] for k in state.fatigue}
    if 'sleep' in changes:
        body.owner.aux['sleep_pressure'] = changes['sleep']
    # Keep the existing owner's raw sensory projection consistent with the
    # explicitly declared initial stocks. No sensory frame or time advances;
    # filters and their histories remain unchanged. Restore validates this.
    sensory = body.owner.owner.memory.loop.sensory
    sensory.raw = type(sensory)._owner_values(body.owner.physical)
    body.owner._record(before, body.owner.body(), 'external_input',
        'declared fresh transfer-test initial condition: ' + json.dumps(changes, sort_keys=True), 0.)
    value = UnifiedBody.migrate(body.owner.checkpoint())
    UnifiedBody.restore(value.checkpoint())
    return value


def run(output):
    from examples.nasuraya_body_loop.host import BodyLoop, KEY as BODY_KEY
    from synthetic_fixture import synthetic_body
    from reflection_cycle import canonical, digest as native_digest

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    plan = dict(PLAN, source_sha256={name: hashlib.sha256((root/name).read_bytes()).hexdigest()
        for name in ('examples/nasuraya_research/transfer.py',
                     'examples/nasuraya_research/confidence.py',
                     'examples/nasuraya_research/controller.py',
                     'examples/nasuraya_body_loop/host.py',
                     'runtimes/tadash_body/PUBLIC_FILES_SHA256.json')})
    save_new(output/'plan.json', plan)  # before training or any held-out outcome
    rows = []
    with tempfile.TemporaryDirectory(prefix='frozen-transfer-') as tmp:
        with BodyLoop.start(Path(tmp)/'training.sqlite') as loop:
            control = Controller.enable(loop, forecast_confidence=PLAN['raw_confidence'])
            training = [control.step('train-'+str(i), duration_s=PLAN['duration_s'])
                        for i in range(PLAN['training_actions'])]
        frozen = dict(history=[r['prediction'] for r in training],
            results=training, plan_sha256=digest(plan),
            test_results_in_training=False)
        save_new(output/'training.json', frozen)
        frozen_sha = digest(frozen)
        for case in plan['cases']:
            assert read_sealed(output/'plan.json') == plan
            cold = read_sealed(output/'training.json')
            assert digest(cold) == frozen_sha
            history = cold['history']
            body_path = Path(tmp)/(case['id']+'.sqlite')
            def initialize():
                return declared_state(synthetic_body(), case['state'])
            with patch('examples.nasuraya_body_loop.host.synthetic_body', side_effect=initialize):
                loop = BodyLoop.start(body_path)
            with loop:
                control = Controller.enable(loop, forecast_confidence=PLAN['raw_confidence'])
                original_step = loop.step
                sealed = []
                def execute(**kwargs):
                    # Controller already reserved its own forecast, but no
                    # native selection, prediction or outcome has run yet.
                    intent = control._load()['intents']['held-out']
                    assert intent['result'] is None and intent['prediction']['samples'] == 0
                    assert not loop.records()
                    prediction = forecast(PLAN['raw_confidence'], intent['prediction']['domain'], history)
                    before = dict(case_id=case['id'], prediction=prediction,
                        training_sha256=frozen_sha, plan_sha256=digest(plan),
                        native_request_sha256=digest(intent['native_request']),
                        checkpoint_sha256=loop.body().checkpoint()['sha256'],
                        native_records_before=0)
                    sealed.append(save_new(output/(case['id']+'-before.json'), before)['sha256'])
                    assert read_sealed(output/(case['id']+'-before.json')) == before
                    if case.get('intervention') == 'sleep_after_reservation':
                        # Test-only same-process state change between observe
                        # and step. The existing native freshness barrier must
                        # reject it; no native cycle or retry is introduced.
                        changed = declared_state(loop.body(), dict(sleep=.95)).checkpoint()
                        loop.engine.db.execute('UPDATE runtime SET digest=?, value=? WHERE key=?',
                            (native_digest(changed), canonical(changed), BODY_KEY))
                    return original_step(**kwargs)
                def upper_snapshot(body):
                    value = snapshot(body)
                    if case.get('intervention') == 'stale_digest':
                        value['native_sha'] = training[0]['research_before']['source_checkpoint_sha256']
                    return value
                try:
                    with patch.object(loop, 'step', side_effect=execute), \
                         patch('examples.nasuraya_research.controller.snapshot', side_effect=upper_snapshot):
                        result = control.step('held-out', duration_s=PLAN['duration_s'])
                except (ResearchBlocked, ValueError) as exc:
                    expected = {'stale_digest': 'observation mismatch',
                                'sleep_after_reservation': 'stale body observation'}
                    assert str(exc) == expected.get(case.get('intervention')), str(exc)
                    assert loop.status()['completed_cycles'] == 0
                    row = dict(case=case, status='blocked', reason=str(exc),
                        preexecution_seals=sealed, native_cycles=0, scored=False,
                        pending=control.status()['pending'], result=None)
                    if sealed:
                        before = read_sealed(output/(case['id']+'-before.json'))
                        row['prediction'] = before['prediction']  # outcome remains unknown
                        with patch.object(loop, 'step', side_effect=AssertionError('retry')):
                            try: control.step('new-request')
                            except ResearchBlocked: pass
                            else: raise AssertionError('pending intent must block new work')
                else:
                    before = read_sealed(output/(case['id']+'-before.json'))
                    prediction = resolve(before['prediction'], outcome=result['prediction']['outcome'],
                                         outcome_source=result['prediction']['outcome_source'])
                    assert result['this_call_native_cycles'] == 1
                    checkpoint = loop.body().checkpoint()
                    replay = control.step('held-out', duration_s=PLAN['duration_s'])
                    assert replay['this_call_native_cycles'] == 0 and loop.body().checkpoint() == checkpoint
                    row = dict(case=case, status='completed', scored=True, native_cycles=1,
                        preexecution_seals=sealed, prediction=prediction,
                        production_prediction=result['prediction'],
                        preferred_action=result['preferred_action'],
                        actual_action=result['native_receipt']['actual_action'],
                        after_checkpoint_sha256=checkpoint['sha256'], replay_native_cycles=0)
                assert digest(read_sealed(output/'training.json')) == frozen_sha
                rows.append(row)
                save_new(output/(case['id']+'-after.json'), row)
    scored = [r for r in rows if r['scored']]
    paired = [r['prediction'] for r in scored]
    summary = dict(schema=PLAN['schema'], case_count=len(rows),
        scored_forecasts=len(paired), blocked_cases=len(rows)-len(paired),
        training_native_cycles=len(training), test_native_cycles=sum(r['native_cycles'] for r in rows),
        applied_transfer_cases=sum(p['correction_active'] for p in paired),
        unseen_domain_fallbacks=sum(not p['correction_active'] for p in paired),
        raw_mean_brier=sum(p['raw_brier'] for p in paired)/len(paired),
        frozen_transfer_mean_brier=sum(p['calibrated_brier'] for p in paired)/len(paired),
        training_sha256=frozen_sha, plan_sha256=digest(plan), training_unchanged=True,
        test_outcomes_used_for_training=0, model_api_calls=0,
        empirical_validation=False, general_improvement_demonstrated=False,
        production_history_imported=False, decision_writeback=False)
    save_new(output/'results.json', dict(summary=summary, cases=rows))
    return summary
