"""Compare design proposals, retain evidence, demonstrate a cold memory decision."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .chromosomes import digest
from .design_decision import candidates, committed_source, context, contract, fresh_source
from .design_memory import DesignMemory
from .foot_contact import compile_foot
from .foot_trial import run_copy
from .traits import ROOT, baseline, checkpoint
from examples.nasuraya_body_loop.__main__ import verified_sources


def persist(memory, path):
    """Durable portable checkpoint; pending intent is saved before any callback."""
    path = Path(path)
    saved = memory.export()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.design-memory-', delete=False) as handle:
            temporary = handle.name
            json.dump(saved, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return saved


def observe(memory, name, trial_id, *, reuse_variant=None, runner=run_copy, checkpoint_path=None):
    before = memory.begin(name, trial_id)
    if checkpoint_path is not None:
        persist(memory, checkpoint_path)
    if before['status'] == 'completed':
        return dict(evidence=before['evidence'], native_calls=0, cached=True)
    if before['status'] == 'unresolved':
        raise ValueError('unresolved prior call: reconcile its result before any retry')
    c = contract()
    if reuse_variant is not None:
        source, receipt, _ = committed_source(reuse_variant)
        calls = 0
    else:
        receipt = runner(compile_foot(candidates()[name]), verified_sources())
        source = fresh_source(c, trial_id)
        calls = 1
    obs = memory.finish(trial_id, receipt, source)
    if checkpoint_path is not None:
        persist(memory, checkpoint_path)
    return dict(evidence=obs, native_calls=calls, cached=False)


def evaluate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    c = contract()
    (output / 'frozen-contract.json').write_text(json.dumps(c, ensure_ascii=False, indent=2) + '\n')
    original = baseline()
    baseline_sha = digest(original)
    native_before = verified_sources()
    # The design SQLite is separate from native state. Export pending intent
    # before any external computation, so failure cannot erase the commitment.
    checkpoint_path = output / 'experience-checkpoint.json'
    with tempfile.TemporaryDirectory(prefix='nasuraya-design-memory-') as directory:
        db_path = output / 'experience.sqlite'
        memory = DesignMemory.create(db_path)
        initial = memory.record_choice('before-experience')
        persist(memory, checkpoint_path)
        measurements = {}
        measurements['baseline'] = observe(memory, 'baseline', 'baseline-prior', reuse_variant='baseline', checkpoint_path=checkpoint_path)
        measurements['foot_plus_1_percent'] = observe(memory, 'foot_plus_1_percent', 'foot-plus-1-fresh', checkpoint_path=checkpoint_path)
        measurements['foot_plus_2_percent'] = observe(memory, 'foot_plus_2_percent', 'foot-plus-2-prior', reuse_variant='affine', checkpoint_path=checkpoint_path)
        # Same physical fixture as baseline: transfer explicitly, not a new trial.
        measurements['cosmetic_only'] = observe(memory, 'cosmetic_only', 'cosmetic-transfer', reuse_variant='baseline', checkpoint_path=checkpoint_path)
        after = memory.record_choice('after-experience')
        without = memory.record_choice('memory-disabled-control', use_memory=False)
        unseen_context = dict(context(), mission='different goal; no transfer is authorized')
        unseen = memory.record_choice('unseen-context-control', requested_context=unseen_context)
        saved = persist(memory, checkpoint_path)
        code = ('import json,sys; from examples.nasuraya_genome.design_memory import DesignMemory; '
                'm=DesignMemory.restore(sys.argv[2],json.load(open(sys.argv[1]))); '
                'print(json.dumps(m.recommend(),sort_keys=True))')
        process = subprocess.run([sys.executable, '-c', code, str(checkpoint_path.resolve()),
                                  str(Path(directory) / 'cold.sqlite')], cwd=ROOT,
                                 check=True, capture_output=True, text=True, timeout=40)
        cold = json.loads(process.stdout)
        # Replaying a completed trial must not call the native runner again.
        def forbidden(*args, **kwargs):
            raise AssertionError('cached trial must not be executed')
        replayed = observe(memory, 'foot_plus_1_percent', 'foot-plus-1-fresh', runner=forbidden)
        state = memory.verify()
    selected = candidates()[after['chosen']]
    (output / 'recommended-genotype.json').write_text(json.dumps(checkpoint(selected), indent=2) + '\n')
    checks = dict(actual_choice_changed=initial['chosen'] != after['chosen'],
                  memory_disabled_retains_baseline=without['chosen'] == 'baseline',
                  cold_recommendation_equal=cold == after,
                  cosmetic_mutation_rejected=after['candidates']['cosmetic_only']['status'] == 'rejected',
                  unseen_context_retains_baseline=unseen['chosen'] == 'baseline' and not unseen['memory_used'],
                  completed_replay_did_not_run=replayed['native_calls'] == 0 and replayed['cached'],
                  native_sources_unchanged=verified_sources() == native_before,
                  original_genotype_unchanged=digest(original) == baseline_sha,
                  no_pending=not state['pending'])
    if not all(checks.values()):
        raise AssertionError(checks)
    result = dict(schema='nasuraya.design-cycle-result/0.1', initial=initial, after=after,
                  memory_disabled=without, unseen_context=unseen, cold=cold, checks=checks,
                  events=state['events'], experience_head_sha256=state['head_sha256'],
                  fresh_physical_experiments=sum(m['native_calls'] for m in measurements.values()),
                  reused_candidate_observations=[name for name, m in measurements.items() if m['native_calls'] == 0],
                  distinct_physical_observations=len({m['evidence']['source']['physical_trial_id'] for m in measurements.values()}),
                  candidate_observations=len(measurements), memory_scope='external exact-context design ledger',
                  selected_is_proposal_only=True, native_apply_allowed=False, live_body_advanced=False, API_calls=0,
                  limitations=['authored utility weights', 'one fresh software comparison',
                               'prior baseline and +2% evidence was already observed',
                               'no statistical/general performance claim', 'no live API agent integration'])
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    r = evaluate(args.output)
    print(json.dumps(dict(before=r['initial']['chosen'], after=r['after']['chosen'],
                          checks=r['checks'], fresh_physical_experiments=r['fresh_physical_experiments'])))
