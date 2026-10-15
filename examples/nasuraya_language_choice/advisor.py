"""Source-bound, read-only language advice; never an action authorization."""
import json
from pathlib import Path
import torch
from peft import PeftModel

from examples.nasuraya_language_adapter import train as old
from examples.nasuraya_language_adapter.data import sha, prompt, read_episodes, row_from_episode
from examples.nasuraya_self_model.monitor import snapshot
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from reflection_cycle import canonical
from .experiment import PROTOCOL, source_hashes, predict, metrics

KEY='nasuraya-language-advisor/2'


def advisor_source():
    return {str(p.relative_to(PROTOCOL.parents[2])):sha(p) for p in
        (Path(__file__), PROTOCOL.parent.parent/'nasuraya_body_loop/language_advisor.py')}


def bundle(run):
    run=Path(run).resolve();result=json.loads((run/'results.json').read_text())
    config=json.loads((run/'frozen-protocol.json').read_text())
    if config!=json.loads(PROTOCOL.read_text()) or result['sources']!=source_hashes():
        raise ValueError('language advisor source/protocol mismatch')
    for name,field in [('before-fresh-labels.json','before_labels_sha256'),
                       ('fresh-labels.sqlite','fresh_label_database_sha256'),('fresh-labels.json','fresh_labels_sha256')]:
        if sha(run/name)!=result[field]:raise ValueError('language evidence checksum mismatch')
    before=json.loads((run/'before-fresh-labels.json').read_text())
    plans=json.loads((run/'fresh-plans.json').read_text())
    if sha(run/'fresh-plans.json')!=before['fresh_plans_sha256']:raise ValueError('fresh plan mismatch')
    episodes=read_episodes(run/'fresh-labels.sqlite')
    labels=[row_from_episode(p['id'],'held_out',*episodes[p['id']],'fresh native receipt after prediction commit') for p in plans]
    if labels!=json.loads((run/'fresh-labels.json').read_text()):raise ValueError('fresh label differs from receipt')
    primary=config['primary_arm'];measured=metrics(before['predictions'][primary],labels)
    parent=metrics(before['predictions']['parent'],labels);gate=config['promotion']
    passed=(measured['balanced_accuracy']>=gate['balanced_accuracy_min'] and measured['admit_recall']>=gate['admit_recall_min']
        and measured['defer_recall']>=gate['defer_recall_min'] and
        measured['balanced_accuracy']-parent['balanced_accuracy']>=gate['gain_over_raw_parent_min'])
    if not passed or not result['promote_advisory'] or measured!=result['metrics'][primary]:
        raise ValueError('language advisor has not passed the frozen promotion criteria')
    directory=run/primary/'adapter'
    if sha(directory/'adapter_model.safetensors')!=result['weights'][primary]['adapter_sha256']:
        raise ValueError('language adapter weights mismatch')
    return config,result,directory


class LanguageAdvisor:
    def __init__(self,run,base):
        self.run=Path(run).resolve();self.base=Path(base).resolve()
        self.config,self.result,directory=bundle(self.run)
        self.weights_sha=sha(directory/'adapter_model.safetensors')
        torch.set_num_threads(self.config['cpu_threads'])
        self.model,self.tokenizer=old.load_base(self.base,json.loads((self.run/'parent-protocol.json').read_text()))
        self.model=PeftModel.from_pretrained(self.model,directory,local_files_only=True,is_trainable=False)
        self.model.eval()
        if old.effective_hashes(self.model)!=self.result['weights'][self.config['primary_arm']]['effective_hashes']:
            raise ValueError('language effective weights mismatch')
        self.cache={}

    def assess(self,body,action,duration):
        before=body.checkpoint()
        common=dict(schema=KEY,action=action,duration_s=duration,checkpoint_sha256=before['sha256'],
                    authority='advisory_only',native_authorization=False,weights_sha256=self.weights_sha)
        if action!='walk':return dict(common,supported=False,reason='trained only for bounded walk admission')
        key=(before['sha256'],action,duration)
        if key not in self.cache:
            q=dict(duration_s=duration,external={})
            text=prompt(snapshot(body),q)
            result=predict(self.model,self.tokenizer,[dict(id='advice',prompt=text)],self.config['max_length'])[0]
            self.cache[key]=dict(common,supported=True,prediction=result['prediction'],
                admit_two_choice_probability=result['admit_probability'],
                scope='two English label completions on generated software fixtures; not calibrated physical probability')
        if body.checkpoint()!=before:raise ValueError('language advice advanced body')
        return dict(self.cache[key])


def configure(loop,*,run,base,expected_checkpoint):
    if not loop.metacognition or loop.body().checkpoint()['sha256']!=expected_checkpoint:
        raise ValueError('enabled metacognition and exact current checkpoint required')
    if loop.status()['unresolved_running'] or loop.metacognition.model.verify()['pending']:
        raise ValueError('resolve existing native/self-model outcomes first')
    tables={r[0] for r in loop.engine.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'body_api_transport' in tables and loop.engine.db.execute("SELECT 1 FROM body_api_transport WHERE state!='deleted'").fetchone():
        raise ValueError('finish and delete the existing API session before configuring language advice')
    advisor=LanguageAdvisor(run,base)
    contract=dict(schema=KEY,run=str(advisor.run),base=str(advisor.base),weights_sha256=advisor.weights_sha,
        results_sha256=sha(advisor.run/'results.json'),sources=advisor_source(),authority='advisory_only')
    previous=loop.engine.db.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
    if previous and json.loads(previous[0])!=contract:raise ValueError('advisor binding cannot be silently replaced')
    with loop.engine.transaction():loop.engine.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(KEY,canonical(contract)))
    return dict(schema=KEY,configured=True,weights_sha256=advisor.weights_sha,authority='advisory_only')


class AdvisedBodyAPIHost(BodyAPIHost):
    def __init__(self,loop,**kwargs):
        super().__init__(loop,**kwargs)
        record=loop.engine.db.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
        if not record:raise ValueError('explicit language advisor configuration required')
        contract=json.loads(record[0])
        if contract['schema']!=KEY or contract['sources']!=advisor_source() or contract['authority']!='advisory_only':
            raise ValueError('language advisor binding/source mismatch')
        if sha(Path(contract['run'])/'results.json')!=contract['results_sha256']:
            raise ValueError('language advisor evidence changed')
        self.language_advisor=LanguageAdvisor(contract['run'],contract['base'])
        if self.language_advisor.weights_sha!=contract['weights_sha256']:raise ValueError('language advisor weights changed')
        self.instructions+='''\nA trained local language advisor is enabled in assess_body_action. Its output
is read-only and never grants execution permission. For this bounded advisory
check, first observe and assess a 0.1-second walk, even if you later choose a
recovery action. You may choose walk, observe, rest or sleep under the existing
budgets and guards. Compare advice with a receipt only if the core actually
requests that walk; a different action does not test the walk prediction.
Do not evade a native or metacognitive guard because of ADMIT advice.\n'''
        if loop.config['fixture']=='normal':
            self.instructions+='For this normal-fixture calibration, the authorized probe is a 0.1-second walk after observing and assessing it; native and metacognitive guards still decide.\n'

    def admission_assessment(self,action,duration_s,observed_checkpoint_sha256):
        result=super().admission_assessment(action,duration_s,observed_checkpoint_sha256)
        result['language_advisor']=self.language_advisor.assess(self.loop.body(),action,self.canonical_duration(duration_s))
        return result
