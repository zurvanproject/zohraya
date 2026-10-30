"""Resume the software-only experiment from its verified validation boundary.

The whole old held-out partition is discarded. Model sources, input protocol,
training receipts and the validation-selected configuration remain unchanged.
Mutable evaluation files stay in local temporary storage until completion.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .__main__ import ROOT, SOURCE, verified_sources


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def resume(source, output):
    from reflection_cycle import canonical, digest
    from synthetic_fixture import prepare_defaults
    from . import continuous_self_knowledge as continuous
    from .continuous_self_eval import (protocol, make_body, start_session, forecasts,
                                      finalize, CANDIDATES, _bucket)
    from .experience import context, metrics
    from .host import executed_body
    from .self_knowledge import BUCKETS
    from .self_knowledge_eval import _append, _write

    started=time.monotonic(); started_utc=datetime.now(timezone.utc).isoformat()
    declared=json.loads((source/'protocol.json').read_text())
    expected=dict(declared); stamp=expected.pop('protocol_sha256')
    if digest(expected)!=stamp or protocol(declared['profile'])!=expected:
        raise ValueError('frozen protocol or model source mismatch')
    settings=declared['settings']; prefix_count=0; expected_ids=[]
    for split in ('train','validation'):
      for seed in settings['seeds']:
        for case in declared['inputs'][str(seed)][split]:
          for preferred in declared['preferences']:
            for duration in declared['durations_s']:
              for step in range(settings['rounds']):
                expected_ids.append(f'f{seed}-{case["id"]}-{preferred}-{int(duration*10)}-{step}')
    prefix_count=len(expected_ids)
    def prefix(path):
        with path.open() as stream:
            return [json.loads(line) for line in itertools.islice(stream,prefix_count)]
    predictions=prefix(source/'predictions.jsonl'); rows=prefix(source/'trials.jsonl')
    if len(predictions)!=prefix_count or [r['id'] for r in rows]!=expected_ids:
        raise ValueError('incomplete or reordered train/validation boundary')
    for p,r in zip(predictions,rows,strict=True):
        if not all(r[k]==v for k,v in p.items()):
            raise ValueError('boundary prediction mismatch: '+r['id'])
    def observation(row):
        return dict(id=row['id'],source=row['source'],kind='observed_software_outcome',
            before=row['before'],feedback=row['feedback']['state'],context=context(row['before']),
            preferred=row['preferred'],duration_s=row['duration_s'],actual_action=row['actual_action'])
    fitted={str(seed):[observation(r) for r in rows if r['fold']==str(seed)] for seed in settings['seeds']}
    training={fold:[observation(r) for r in rows if r['fold']==fold and r['split']=='train'] for fold in fitted}
    for fold in fitted:
        if json.loads((source/f'fold-{fold}-train.json').read_text())!=training[fold]:
            raise ValueError('training boundary differs from native observations')
        old_fit=source/f'fold-{fold}-fit.json'
        if old_fit.exists() and json.loads(old_fit.read_text())!=fitted[fold]:
            raise ValueError('fitted boundary differs from native observations')
    selection=json.loads((source/'selection.json').read_text())
    validation=[r for r in rows if r['split']=='validation']
    losses=[sum(sum((r['forecasts']['candidates'][i]['distribution'][a]-
        (a==_bucket(r['actual_action'])))**2 for a in BUCKETS) for r in validation)/len(validation)
        for i in range(len(CANDIDATES))]
    winner=min(range(len(CANDIDATES)),key=lambda i:(losses[i],i))
    if (selection['config']!=CANDIDATES[winner] or selection['validation_brier']!=losses
            or selection['test_outcomes_seen']!=0):
        raise ValueError('boundary selection is not validation-only')
    selected=selection['config']; origin=json.loads((source/'origin.json').read_text())
    output.mkdir(parents=True,exist_ok=False)
    for name in ('protocol.json','origin.json','selection.json','selected-config.json'):
        shutil.copyfile(source/name,output/name)
    for fold in fitted:
        _write(output/f'fold-{fold}-train.json',training[fold])
        _write(output/f'fold-{fold}-fit.json',fitted[fold])
    prepare_defaults(); count=prefix_count
    with open(output/'native-records.jsonl.gz','wb') as raw:
      with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,compresslevel=6) as archive:
        with gzip.open(source/'native-records.jsonl.gz','rt') as native:
          for p,r,line in zip(predictions,rows,itertools.islice(native,prefix_count),strict=True):
            record=json.loads(line)
            if (digest(record)!=r['native_record_sha256'] or record['id']!=r['id']
                    or not executed_body(record)
                    or record['actual_outcome']['selected_action']!=r['actual_action']):
                raise ValueError('native boundary receipt mismatch: '+r['id'])
            archive.write((canonical(record)+'\n').encode())
            _append(output/'predictions.jsonl',p); _append(output/'trials.jsonl',r)
        print(canonical(dict(verified_boundary_cycles=prefix_count,
            whole_old_test_partition_discarded=True,selected_config=selected)),flush=True)
        for split in ('test','novelty'):
          for seed in settings['seeds']:
            fold=str(seed); frozen=fitted[fold]; frozen_sha=digest(frozen)
            for case in declared['inputs'][fold][split]:
              body=make_body(origin,case['changes'])
              for preferred in declared['preferences']:
                durations=[declared['novelty_duration_s']] if split=='novelty' else declared['durations_s']
                for duration in durations:
                  rounds=1 if split=='novelty' else settings['rounds']
                  session_id=f'f{fold}-{case["id"]}-{preferred}-{int(duration*10)}'
                  with tempfile.TemporaryDirectory(prefix='self-resume-session-') as tmp:
                    with start_session(Path(tmp)/'body.sqlite',session_id,body,rounds) as loop:
                      for step in range(rounds):
                        ident=session_id+f'-{step}'
                        snapshot=loop.observe(); before=metrics(snapshot)
                        feedback=continuous.native_feedback(loop,snapshot,duration)
                        pre=dict(id=ident,fold=fold,split=split,case=case['id'],step=step,
                            before=before,feedback=feedback,preferred=preferred,duration_s=duration,
                            before_checkpoint_sha256=snapshot['checkpoint_sha256'],
                            training_sha256=frozen_sha,training_count=len(frozen),
                            forecasts=forecasts(frozen,before,feedback['state'],preferred,duration,split,selected))
                        _append(output/'predictions.jsonl',pre)
                        receipt=loop.step(decision_id=ident,duration_s=duration,preferred_action=preferred)
                        record=loop.engine.get(ident)
                        if not executed_body(record):raise ValueError('incomplete resumed native outcome')
                        source_ref='native-decision://'+ident+'/'+digest(record)
                        archive.write((canonical(record)+'\n').encode())
                        row=dict(pre,actual_action=receipt['actual_action'],source=source_ref,
                            receipt=receipt,native_record_sha256=digest(record))
                        _append(output/'trials.jsonl',row); count+=1
                        if digest(frozen)!=frozen_sha:raise ValueError('frozen fit changed')
                      if loop.status()['actions_remaining']!=0:raise ValueError('unexpected resumed budget')
                  if count%32==0:
                    print(canonical(dict(completed=count,new_native_cycles=count-prefix_count,
                        split=split,fold=fold,elapsed_seconds=round(time.monotonic()-started,1))),flush=True)
        archive.flush()
      raw.flush();os.fsync(raw.fileno())
    summary=finalize(output)
    summary.update(started_utc=started_utc,completed_utc=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=time.monotonic()-started,timing_scope='resumption and audit; verified prefix executed earlier',
        resumed_from_validation=True,reused_prefix_cycles=prefix_count,new_native_cycles=count-prefix_count,
        model_api_calls=0,physical_actuator_calls=0,initialization_warmup_cycles=1)
    _write(output/'summary.json',summary)
    _write(output/'resumption.json',dict(schema='nasuraya-validation-boundary-resumption/1',
        source_protocol_sha256=stamp,kept_prefix_cycles=prefix_count,
        discarded_partitions=['test','novelty'],new_native_cycles=count-prefix_count,
        model_and_config_changed=False,mutable_storage='local temporary directory',
        entrypoint_sha256=_sha(__file__),full_post_run_audit_passed=True))
    print(canonical(dict(native_cycles=count,validation_passed=True,
        all_acceptance_criteria_passed=summary['all_acceptance_criteria_passed'])),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv);source=args.source.resolve();output=args.output.resolve()
    if not source.is_dir() or output.exists():parser.error('existing source and never-used output required')
    if args.worker:
        resume(source,output);return 0
    manifest=verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-self-resume-') as tmp:
        runtime=Path(tmp)/'runtime';runtime.mkdir();result=Path(tmp)/'result'
        for name in manifest:
            dest=runtime/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(SOURCE/name,dest)
        env=dict(os.environ);env.pop('OPENAI_API_KEY',None)
        env['PYTHONPATH']=str(runtime)+os.pathsep+str(ROOT)
        status=subprocess.run([sys.executable,'-m',__spec__.name,str(source),str(result),'--worker'],
                              cwd=runtime,env=env).returncode
        if status:return status
        shutil.copytree(result,output)
        if any(_sha(p)!=_sha(output/p.relative_to(result)) for p in result.rglob('*') if p.is_file()):
            raise ValueError('completed export hash mismatch')
    print(json.dumps(dict(exported=str(output),immutable_export_hashes_match=True)),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
