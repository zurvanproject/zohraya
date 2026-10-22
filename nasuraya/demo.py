"""One fresh session across real modules, with process-boundary replay checks."""
import json
from pathlib import Path
from .__main__ import invoke
from examples.nasuraya_affect.engine import CHECKS
from examples.nasuraya_genome.history import create, verify
from examples.nasuraya_genome.traits import express


def call(name, *args):
    result = invoke(name, list(map(str, args)), capture=True)
    if result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    return json.loads(result.stdout)


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    genome = create()
    genotype = verify(genome)
    (output/'genome.json').write_text(json.dumps(genome, indent=2)+'\n')
    session = output/'session'
    call('dialogue', 'init', '--session-dir', session, '--max-actions', '1')
    appraisal = dict.fromkeys(CHECKS, 0.)
    appraisal.update(relevance=1., certainty=1., goal_congruence=.8, novelty=.8, controllability=.7)
    message = dict(id='unified-fixture', text='Synthetic integration scenario', intent='explore',
                   appraisal=appraisal, duration_s=.1)
    path = output/'message.json'
    path.write_text(json.dumps(message)+'\n')
    first = call('dialogue', 'message', '--session-dir', session, '--message', path)
    before = call('dialogue', 'status', '--session-dir', session)
    replay = call('dialogue', 'message', '--session-dir', session, '--message', path)
    after = call('dialogue', 'status', '--session-dir', session)
    if first['this_call_body_cycles'] != 1 or replay['this_call_body_cycles'] != 0 or before != after:
        raise RuntimeError('unified continuation contract failed')
    if verify(json.loads((output/'genome.json').read_text())) != genotype:
        raise RuntimeError('genome proposal changed during body execution')
    observation = call('self-observe', '--session', session/'body.sqlite')
    if (observation['checkpoint_sha256'] != after['body']['self_model']['checkpoint_sha256']
            or not observation['native_checkpoint_unchanged']):
        raise RuntimeError('self-model observed a different body checkpoint')
    (output/'self-observation.json').write_text(json.dumps(observation, indent=2)+'\n')
    report = dict(schema='nasuraya.unified-demo/1', body_kind='native aggregate Tadash',
                  actual_action=first['native_receipt']['actual_action'],
                  executed_cycles=first['this_call_body_cycles'], replay_cycles=replay['this_call_body_cycles'],
                  state_equal_across_cold_replay=before==after,
                  identity_policy_sha256=express(genotype)['policy_sha256'],
                  genome_revision=genotype['revision'], genome_applied_to_body=False,
                  self_observation_checkpoint_sha256=observation['checkpoint_sha256'],
                  self_model_status=observation['telemetry']['operational_status'],
                  self_model_integrity=observation['telemetry']['integrity'],
                  self_observation_cycles=observation['simulated_cycles_executed'],
                  source='synthetic fixture only', external_api_calls=0)
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
