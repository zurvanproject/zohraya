"""Run only in caller-created disposable, verified native staging (Linux)."""
import json
import os
from pathlib import Path
import sys

from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE


def run(directory):
    # Refuse direct execution against repository runtime defaults.
    import unified_body_v2
    native_root = Path(unified_body_v2.__file__).resolve().parent
    if native_root == SOURCE.resolve() or Path.cwd().resolve() != native_root:
        raise ValueError('disposable native staging required')
    from examples.nasuraya_body_loop.host import BodyLoop
    from .sensory import Stimulus, transduce
    from .state import observe
    from .integration import SensoryPolicy
    results = {}
    for name, intensity, fixture in (('none', 0., 'normal'), ('mechanical', .95, 'normal'),
                                     ('sleep_protection', 0., 'sleep')):
        kind = 'mechanical' if intensity else 'none'
        state = observe(transduce(Stimulus('left_palm', intensity, .8, 12., kind, .025, .2), seed=183))
        policy = SensoryPolicy(state, directory / (name + '-goals'))
        with BodyLoop.start(directory / (name + '.sqlite'), fixture=fixture, max_actions=1) as loop:
            before = loop.observe()
            # This bounded research bridge uses the existing ReflectiveBody API
            # to route actual touch samples, not just a preferred-action string.
            if loop.config['mode'] != 'bounded' or loop.status()['actions_remaining'] != 1:
                raise ValueError('one fresh bounded action required')
            body = loop.body()
            sample_time = body.owner.owner.body.state.time_s
            external = {'sensors': {'touch': {'value': min(1., max(state.features())),
                'source_id': 'synthetic-palm-afferents-v1', 'sampled_at_s': sample_time,
                'kind': 'declared_simulated_input'}}}
            request = loop.make_request('palm-1', before, .1, policy.native_preference())
            loop.engine.db.execute('DELETE FROM meta WHERE key=?', ('body-loop-observation',))
            record = loop.adapter.cycle(request, at_utc=request['at_utc'], duration_s=.1, external=external)
            receipt = loop.receipt(record, replayed=False)
            after = loop.body()
            exhausted = False
            loop.observe()
            try:
                loop.step(decision_id='second')
            except ValueError as exc:
                exhausted = 'budget exhausted' in str(exc)
            results[name] = {'before_sha': before['checkpoint_sha256'], 'receipt': receipt,
                             'input_touch': external['sensors']['touch'],
                             'retained_touch': after.modules['senses']['samples']['touch'],
                             'budget_enforced': exhausted, 'body_model': 'native_195kg_reduced_simulation'}
        with BodyLoop(directory / (name + '.sqlite')) as reopened:
            results[name]['cold_checkpoint_matches'] = reopened.body().checkpoint() == after.checkpoint()
    return results


if __name__ == '__main__':
    print(json.dumps(run(Path(sys.argv[1])), sort_keys=True, allow_nan=False))
