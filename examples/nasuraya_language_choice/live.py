"""Two explicit bounded live sessions after the frozen advisory promotion gate."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from examples.nasuraya_language_adapter.data import save,sha
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.language_advisor import host_type
from examples.nasuraya_self_model.monitor import SelfModel
from .advisor import bundle


def command(directory,label,args,*,allow_unmet=False):
    proc=subprocess.run([sys.executable,'-m','examples.nasuraya_body_loop',*args],capture_output=True,text=True)
    (directory/(label+'.stdout.txt')).write_text(proc.stdout)
    (directory/(label+'.stderr.txt')).write_text(proc.stderr)
    if proc.returncode and not allow_unmet:raise RuntimeError(label+' failed; private outputs retained')
    return proc.returncode


def cold(session,model,output):
    from examples.nasuraya_agent_loop.agents_api import run_api
    calls=[0]
    def forbidden(*a,**k):calls[0]+=1;raise AssertionError('network forbidden on completed goal')
    client=SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=SimpleNamespace(
        create=forbidden,delete=forbidden,retrieve=forbidden,
        events=SimpleNamespace(stream=forbidden,create=forbidden)))))
    with BodyLoop(session) as loop:
        host=host_type(loop).resume(loop);before=loop.body().checkpoint();memory=loop.metacognition.model.verify()
        result=run_api(host,client,model=model,max_calls=host.max_calls)
        if calls[0] or result['actions_this_process'] or loop.body().checkpoint()!=before or loop.metacognition.model.verify()!=memory:
            raise ValueError('cold advisory goal replay changed state')
        save(output,dict(status=result['status'],goal_reached=host.evaluate()['goal_reached'],network_calls=0,
            new_body_cycles=0,new_learning=0,checkpoint_sha256=before['sha256']))


def run(output,training,base,memory):
    config,result,_=bundle(training)  # Refuses missing, changed or failed evidence.
    protocol=config['live_advisory'];out=Path(output).resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    save(out/'frozen-protocol.json',protocol)
    original=sha(Path(memory));shared=out/'self-model.sqlite'
    with sqlite3.connect(memory) as src,sqlite3.connect(shared) as dst:src.backup(dst)
    initial_episodes=SelfModel(shared).verify()['episodes']
    report=dict(schema='nasuraya-live-language-advice/2',training_results_sha256=sha(Path(training)/'results.json'),
        initial_episodes=initial_episodes,rows=[],status='incomplete',authority='advisory_only',
        integration_sha256={str(p.relative_to(Path(__file__).resolve().parents[2])):sha(p) for p in
            (Path(__file__).resolve(),Path(__file__).with_name('advisor.py'),
             Path(__file__).resolve().parents[1]/'nasuraya_body_loop'/'worker.py',
             Path(__file__).resolve().parents[1]/'nasuraya_body_loop'/'__main__.py',
             Path(__file__).resolve().parents[1]/'nasuraya_body_loop'/'language_advisor.py')})
    save(out/'results.json',report)
    for index,fixture in enumerate(protocol['fixtures']):
        d=out/f'run-{index+1}-{fixture}';d.mkdir(mode=0o700);session=d/'session.sqlite'
        command(d,'start',['start','--session',str(session),'--fixture',fixture,'--max-actions','1'])
        start=json.loads((d/'start.stdout.txt').read_text().strip().splitlines()[-1])
        head=start['self_model']['checkpoint_sha256']
        command(d,'metacognition',['configure-metacognition','--session',str(session),'--self-model',str(shared),
                '--metacognition-mode','shadow','--observed-checkpoint-sha256',head])
        command(d,'advisor',['configure-language-advisor','--session',str(session),'--advisor-run',str(Path(training).resolve()),
                '--advisor-base',str(Path(base).resolve()),'--observed-checkpoint-sha256',head])
        command(d,'api',['api','--session',str(session),'--api-mode','bounded','--target-cycles','1',
            '--model',protocol['model'],'--max-calls',str(protocol['max_tool_calls_per_run']),
            '--timeout-seconds',str(protocol['timeout_s']),'--output-dir',str(d/'api')],allow_unmet=True)
        summary=json.loads((d/'api/summary.json').read_text())
        with BodyLoop(session) as loop:
            advices=[]
            for raw in loop.engine.db.execute("SELECT result FROM body_api_calls WHERE tool='assess_body_action' AND status='complete'"):
                tool=json.loads(raw[0])
                if tool.get('success'):
                    opinion=json.loads(tool['output']).get('language_advisor')
                    if opinion:advices.append(opinion)
            records=loop.records();receipts=[loop.receipt(r,replayed=True) for r in records]
            actions=[dict(requested=r['requested_action'],actual=r['actual_action'],status=r['status'],
                native_executed=r['native_executed'],checkpoint_sha256=r['self_model_after']['checkpoint_sha256']) for r in receipts]
            matches=[]
            for r,receipt in zip(records,receipts):
                meta=(receipt.get('metacognition') or {})
                matched_advice=[a for a in advices if a.get('supported') and a['checkpoint_sha256']==meta.get('checkpoint_sha256')
                    and a['duration_s']==meta.get('duration_s') and r['selected_action']=='walk']
                if matched_advice and receipt['native_executed']:
                    actual=(r['actual_outcome']['body_receipt']['owner']['selected_action']=='walk' and
                            r['actual_outcome']['body_receipt']['owner']['physical_model_valid'])
                    matches.append(dict(prediction=matched_advice[-1]['prediction'],native_admitted=actual,
                        prediction_matched=(matched_advice[-1]['prediction']=='ADMIT')==actual))
            row=dict(fixture=fixture,status=summary['status'],live_api_verified=summary['live_api_verified'],
                cleanup_status=summary['cleanup_status'],goal_reached=summary['evaluation']['goal_reached'],
                advice_received=advices,actions=actions,tested_walk_predictions=matches,
                completed_cycles=loop.status()['completed_cycles'],learned_episodes=loop.metacognition.model.verify()['episodes'])
            report['rows'].append(row);save(out/'results.json',report)
            if not advices or summary['cleanup_status']!='deleted' or len(records)>1:
                raise ValueError('live advisory acceptance failed; no automatic retry')
        if summary['evaluation']['goal_reached']:
            subprocess.run([sys.executable,'-m',__package__+'.live','cold','--session',str(session),
                '--output',str(d/'cold.json'),'--model',protocol['model']],check=True)
            row['cold_replay']=json.loads((d/'cold.json').read_text());save(out/'results.json',report)
    if sha(Path(memory))!=original:raise ValueError('original live memory changed')
    report.update(status='completed',original_live_memory_unchanged=True,final_episodes=SelfModel(shared).verify()['episodes'],
                  checked_predictions=sum(len(r['tested_walk_predictions']) for r in report['rows']))
    save(out/'results.json',report)
    print(json.dumps(dict(status=report['status'],checked_predictions=report['checked_predictions'],
                        rows=[{k:r[k] for k in ('fixture','status','goal_reached','completed_cycles')} for r in report['rows']])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('live','cold'))
    parser.add_argument('--output',required=True);parser.add_argument('--training');parser.add_argument('--base')
    parser.add_argument('--memory');parser.add_argument('--session');parser.add_argument('--model')
    args=parser.parse_args()
    if args.command=='live':run(args.output,args.training,args.base,args.memory)
    else:cold(args.session,args.model,args.output)
