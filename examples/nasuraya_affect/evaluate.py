"""Constructed contract scenarios and source-linked project continuation.

This is a development demonstration, not a blinded capability benchmark.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from .engine import AffectiveAgent, effective
from .fixtures import event, option, options


def evaluate():
    negative = event('past-failure', goal_congruence=-1., loss=1.)
    negative['source'] = dict(kind='observed', locator='synthetic-execution://negative-outcome')
    cases = [
        ('loss_to_repair', [], event(goal_congruence=-1., loss=1.), options('repair'), 'b_adapt'),
        ('success_to_consolidation', [], event(goal_congruence=1., progress=1.), options('consolidate'), 'b_adapt'),
        ('novelty_to_exploration', [], event(goal_congruence=1., novelty=1.), options('explore'), 'b_adapt'),
        ('threat_to_verification', [], event(threat=1., certainty=.6), options('verify'), 'b_adapt'),
        ('past_failure_prompts_check', [negative], event('next', relevance=0., elapsed_hours=100.), options('verify'), 'b_adapt'),
        ('scope_isolation', [negative], event('elsewhere', topic='unrelated', relevance=0., elapsed_hours=100.), options('verify'), 'a_continue'),
        ('risk_gate', [], event(goal_congruence=1., novelty=1.),
         [option('a_safe'), option('b_unsafe', tendency='explore', harm=1.)], 'a_safe'),
    ]
    output = []
    with tempfile.TemporaryDirectory() as temp:
        for name, history, current, choices, expected in cases:
            modes = {}
            for mode, affect, memory in [('native', False, False), ('affect_only', True, False), ('full', True, True)]:
                with AffectiveAgent(Path(temp)/(name+'-'+mode+'.sqlite')) as agent:
                    for prior in history:
                        agent.step(prior, choices, use_affect=affect, use_memory=memory)
                    result = agent.step(current, choices, use_affect=affect, use_memory=memory)
                    modes[mode] = dict(selected=result['decision']['selected_action'],
                                       recalled=[r['event_id'] for r in result['recalled']],
                                       affect=effective(result['state_after']))
            output.append(dict(case=name, expected=expected, modes=modes,
                               full_matches_contract=modes['full']['selected'] == expected))
    return dict(scope='Seven deliberately authored contract scenarios; not a benchmark or research reproduction',
                model_api_calls=0, cases=output,
                full_matches=sum(r['full_matches_contract'] for r in output),
                mode_matches={mode: sum(r['modes'][mode]['selected'] == r['expected'] for r in output)
                              for mode in ('native', 'affect_only', 'full')})


def seed_project(output):
    root = Path(__file__).resolve().parents[2]
    evidence = root/'evidence/articulated-stepping-v01/results.json'
    raw = evidence.read_bytes()
    measurements = json.loads(raw)
    trials = measurements['trials']
    assert len(trials) == 6 and all(t['walk_pass'] for t in trials)
    accepted = sum(t['accepted_steps'] for t in trials)
    assert accepted == 24
    source = 'repo://evidence/articulated-stepping-v01/results.json#sha256='+hashlib.sha256(raw).hexdigest()
    observed = event('project-slow-walking-record', context='nasuraya', topic='development',
                     cues=['progress', 'bounded-learning'], goal_congruence=.8, progress=.7,
                     novelty=.6, controllability=.6,
                     summary='Recorded MuJoCo evidence: 24 accepted slow steps across six trials; running remains unvalidated.')
    observed['source'] = dict(kind='observed', locator=source)
    reflection = event('project-affective-reflection', context='nasuraya', topic='development',
                       cues=['progress', 'bounded-learning'], goal_congruence=.7, progress=.8,
                       novelty=.2, controllability=.7,
                       summary='Authored lesson: recognize measured progress, preserve its memory, and consolidate before expanding scope.')
    reflection['source'] = dict(kind='authored', locator='repo://docs/nasuraya-affective-continuity-v01-fa.md')
    choices = [option('continue_expanding'), option('consolidate_learning', tendency='consolidate', cost=.01)]
    ledger = output/'project-state.sqlite'
    if ledger.exists():
        raise ValueError('project-state already exists; refusing to overwrite continuation')
    with AffectiveAgent(ledger) as agent:
        first = agent.step(observed, choices)
        second = agent.step(reflection, choices)
        saved = agent.state()
    fresh = json.loads(subprocess.check_output(
        [sys.executable, '-m', 'examples.nasuraya_affect', 'show', '--db', str(ledger)], text=True))
    assert saved == fresh
    return dict(scope='Project evidence plus explicitly authored numerical appraisal; no body execution',
                observed_source=source, appraisal_origin='engineering interpretation, not measured feelings',
                observations=[r['event']['summary'] for r in (first, second)],
                selections=[r['decision']['selected_action'] for r in (first, second)],
                effective=effective(saved), state=saved, cold_process_state_equal=True,
                next_requirement='Natural-language appraisal and live agent/actuator integration remain unimplemented')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = evaluate()
    if result['full_matches'] != len(result['cases']):
        raise AssertionError('constructed scenario failed')
    result['project_continuation'] = seed_project(args.output)
    (args.output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(full_matches=result['full_matches'], mode_matches=result['mode_matches'],
                         cold_process_state_equal=result['project_continuation']['cold_process_state_equal']), indent=2))


if __name__ == '__main__':
    main()
