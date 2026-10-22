"""Native body bridge fixtures; run only in the verified worker."""
import json
from pathlib import Path
import tempfile

from examples.nasuraya_body_loop.host import BodyLoop
from .engine import AffectiveAgent, CHECKS
from .body_dialogue import DialogueBodyBridge


def evaluate(output):
    output.mkdir(parents=True, exist_ok=False)
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        for fixture in ('normal', 'sleep'):
            folder = Path(temporary)/fixture
            folder.mkdir()
            with BodyLoop.start(folder/'body.sqlite', fixture=fixture, max_actions=1) as body:
                with AffectiveAgent(folder/'affect.sqlite') as affect:
                    bridge = DialogueBodyBridge.enable(body, affect)
                    checks = dict.fromkeys(CHECKS, 0.)
                    checks.update(relevance=1., certainty=1., goal_congruence=.8, novelty=.8, controllability=.7)
                    message = dict(id='fixture-'+fixture, text='Authored native-body bridge scenario',
                                   intent='explore', appraisal=checks, duration_s=.1)
                    before = body.status()
                    result = bridge.receive(message)
                    repeated = bridge.receive(message)
                    expected = 'walk' if fixture == 'normal' else 'observe'
                    assert result['native_receipt']['actual_action'] == expected
                    assert repeated['this_call_body_cycles'] == 0
                    results.append(dict(fixture=fixture, before=before, result=result,
                                        after=bridge.status(), replay_body_cycles=0))
    report = dict(scope='Two constructed native UnifiedBody scenarios; no MuJoCo or external model API',
                  results=results)
    (output/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return dict(scenarios=len(results), actions=[r['result']['native_receipt']['actual_action'] for r in results])
