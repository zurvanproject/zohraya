"""Cold-process dialogue -> memory -> forecast -> native outcome demonstration."""
import json
from pathlib import Path
from examples.nasuraya_affect.engine import CHECKS
from .demo import call


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    session = output/'session'
    call('dialogue', 'init', '--session-dir', session, '--max-actions', '2')
    checks = dict.fromkeys(CHECKS, 0.)
    checks.update(relevance=1., certainty=1., goal_congruence=.8, novelty=.8, controllability=.7)
    results, paths = [], []
    for identifier in ('first', 'second'):
        path = output/(identifier+'.json')
        path.write_text(json.dumps(dict(id=identifier, text='Synthetic continuity fixture '+identifier,
                                       intent='explore', appraisal=checks, duration_s=.1))+'\n')
        paths.append(path)
        results.append(call('dialogue', 'message', '--session-dir', session, '--message', path))
    trace = call('dialogue', 'trace', '--session-dir', session, '--message-id', 'second')
    recall = call('dialogue', 'recall', '--session-dir', session, '--cue', 'body')
    consolidation = call('dialogue', 'consolidate', '--session-dir', session)
    before = call('dialogue', 'status', '--session-dir', session)
    replay = call('dialogue', 'message', '--session-dir', session, '--message', paths[1])
    after = call('dialogue', 'status', '--session-dir', session)
    forecasts = [r['experience']['prediction'] for r in results]
    if (before != after or replay['this_call_body_cycles'] != 0 or
            replay['experience']['this_call_native_cycles'] != 0 or
            forecasts[1]['history_ids'] != ['first'] or forecasts[1]['method'] != 'nearest_episode' or
            after['body']['completed_cycles'] != 2 or any(p['numeric_gate']['eligible'] for p in forecasts)):
        raise RuntimeError('shared continuity contract failed')
    report = dict(schema='nasuraya.dialogue-memory-continuity/1',
        source='two sequential synthetic software-body transitions; not independent forecast validation',
        native_cycles=after['body']['completed_cycles'], remaining_budget=after['body']['actions_remaining'],
        cold_replay_cycles=replay['this_call_body_cycles'], cold_replay_state_equal=before == after,
        episode_count=len(after['experience']['episodes']),
        actions=[r['native_receipt']['actual_action'] for r in results],
        action_correct=sum(int(p['action_correct']) for p in forecasts),
        metric_mae=sum(p['mean_absolute_error'] for p in forecasts)/len(forecasts),
        forecast_methods=[p['method'] for p in forecasts],
        numeric_gate_eligible=False, external_api_calls=0, incremental_api_cost_usd=0,
        recalled_sources=[r['source'] for r in recall['records']],
        trace=trace, consolidation=consolidation)
    (output/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report
