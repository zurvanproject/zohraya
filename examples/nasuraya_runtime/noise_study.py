"""Stage-3 prospective continuous study; development and holdout are separate."""
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

from examples.tadash_interoception.sensory import AfferentFrame, Stimulus, transduce, LOCATIONS, TYPES
from examples.tadash_interoception.state import InternalState, digest, canonical
from examples.tadash_interoception.model import Prediction, CLASSES
from examples.tadash_interoception.integration import DiosObserver, correction_gate
from . import stream_study
from .perception import SignedTrace, NoiseDecoder, fit_numeric, sigmoid
from .adapters import decoder, ROOT

SPLITS={'train':tuple(range(2000000,2000024)),'diagnosis':tuple(range(2010000,2010008)),
        'validation':tuple(range(2020000,2020008)),'test':tuple(range(2030000,2030024)),
        'novel':tuple(range(2040000,2040008)),'shift':tuple(range(2050000,2050008))}
REGULARIZATION=(.001,.01,.1)
TEMPERATURES=(.5,1.,2.,4.)


def generate(seed, *, novel=False, shift=False, ticks=640):
    rng=random.Random(seed);condition=('clean','noisy','misleading')[seed%3]
    noise=rng.uniform(.10,.25) if condition=='noisy' else .025
    samples=[]
    while len(samples)<ticks:
        for _ in range(rng.randint(0,60)):
            samples.append((tuple(max(-2.,min(2.,rng.gauss(0,noise))) for _ in range(6)),None))
        location=rng.choice(LOCATIONS);kind='compound' if novel and rng.random()<.4 else rng.choice(TYPES)
        duration=rng.choice((.1,.3,.6,1.));intensity=rng.uniform(.18,1.)
        stimulus=Stimulus(location,intensity,duration,rng.uniform(1,39),kind,noise,0.)
        raw=transduce(stimulus,seed=rng.randrange(2**31))[:round(duration*10)]
        samples.extend((f.values,(location,kind,intensity)) for f in raw)
    samples=samples[:ticks]
    if shift:
        # Dedicated held-out stress: correlated additive disturbance and offsets.
        disturbance=[0.]*6;changed=[]
        for values,truth in samples:
            disturbance=[.8*x+rng.gauss(0,.08) for x in disturbance]
            if rng.random()<.02:disturbance[rng.randrange(6)]+=rng.uniform(.3,.8)
            changed.append((tuple(max(-2.,min(2.,x+d)) for x,d in zip(values,disturbance)),truth))
        samples=changed
    return samples,condition


def rows(seeds, *, novel=False, shift=False, ticks=640):
    result=[]
    for seed in seeds:
        samples,condition=generate(seed,novel=novel,shift=shift,ticks=ticks)
        state=InternalState();signed=SignedTrace();cold=None;cold_signed=None
        for i,(values,_) in enumerate(samples):
            frame=AfferentFrame((i+1)/10,values);state.step(frame);signed.step(frame)
            if cold is not None:cold.step(frame);cold_signed.step(frame)
            if i==ticks//2-1:
                cold=InternalState.restore(json.loads(canonical(state.checkpoint())))
                cold_signed=SignedTrace.restore(json.loads(canonical(signed.checkpoint())))
            if i<15 or (i+1)%4:continue
            active=[x for _,x in samples[i-11:i+1] if x is not None]
            families={(r,k) for r,k,_ in active};one=len(families)==1
            location,kind=next(iter(families)) if one else ('mixed','mixed') if families else ('none','none')
            truth={'occurred':bool(active),'location':location,'type':kind,
                'intensity':statistics.mean(x[2] for x in active) if active else 0.,
                'classifiable':one and kind in TYPES,'novel_present':any(k=='compound' for _,k in families)}
            visible=location+':'+kind if active else 'none'
            if condition=='misleading':visible=random.Random(seed*1000+i).choice([x for x in CLASSES if x!=visible])
            result.append({'seed':seed,'tick':i+1,'condition':condition,'truth':truth,'label':visible,
                'features':state.features(),'signed_features':signed.features(),
                'state_sha':digest({'legacy':state.checkpoint(),'signed':signed.checkpoint()}),
                'memory_consistent':cold is None or (cold.checkpoint()==state.checkpoint() and cold_signed.checkpoint()==signed.checkpoint())})
    return result


def scores(data,predictions):
    result=stream_study.scores(data,predictions)
    result['balanced_accuracy']=1-(result['fpr']+result['fnr'])/2 if result['positive'] and result['negative'] else None
    return result


def grouped(data,predictions):
    out={'all':scores(data,predictions),'conditions':{}}
    for condition in ('clean','noisy','misleading'):
        pairs=[(r,p) for r,p in zip(data,predictions) if r['condition']==condition]
        if pairs:out['conditions'][condition]=scores([r for r,_ in pairs],[p for _,p in pairs])
    return out


def predict(model,data,*,observer=None,prefix=''):
    result=[]; model_sha=model.fingerprint()
    for row in data:
        p=model.predict(row['features'],row['signed_features']) if isinstance(model,NoiseDecoder) else model.predict(row['features'])
        if observer:
            identity=f'{prefix}:{row["seed"]}:{row["tick"]}'
            observer.commit_prediction(identity,p,model_sha=model_sha,state_sha=row['state_sha'])
            observer.reveal(identity,row['truth'])
        result.append(p)
    return result


def calibration(data,parameters,class_model):
    raw=NoiseDecoder(parameters,class_model)
    probabilities=[raw.probability(r['signed_features']) for r in data]
    y=[r['truth']['occurred'] for r in data];noisy=[r['condition']=='noisy' for r in data]
    trials=[]
    for temperature in TEMPERATURES:
        ps=[sigmoid(math.log(p/(1-p))/temperature) for p in probabilities]
        brier=sum((p-t)**2 for p,t in zip(ps,y))/len(y)
        for cut in range(10,91):
            threshold=cut/100;detected=[p>=threshold for p in ps]
            fpr=sum(d and not t for d,t,n in zip(detected,y,noisy) if n)/sum(n and not t for n,t in zip(noisy,y))
            fnr=sum(not d and t for d,t in zip(detected,y))/sum(y)
            overall_fp=sum(d and not t for d,t in zip(detected,y))/(len(y)-sum(y))
            balanced=1-(fnr+overall_fp)/2
            trials.append({'temperature':temperature,'threshold':threshold,'brier':brier,
                           'noisy_fpr':fpr,'fnr':fnr,'balanced_accuracy':balanced})
    feasible=[r for r in trials if r['noisy_fpr']<=.10]
    chosen=min(feasible,key=lambda r:(-r['balanced_accuracy'],r['brier'],r['threshold'])) if feasible else min(trials,key=lambda r:(r['noisy_fpr'],-r['balanced_accuracy'],r['brier']))
    return dict(parameters,temperature=chosen['temperature'],threshold=chosen['threshold']),chosen,trials


def implementation():
    files=set(stream_study.implementation())
    files.update('examples/nasuraya_runtime/'+x+'.py' for x in ('profile','perception','noise_study','__main__'))
    files.add('examples/dios_nous/unified/body.py')
    return {f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sorted(files)}


def develop(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    observer=DiosObserver(directory/'observer.jsonl');start=time.perf_counter()
    train,diagnostic,validation=[rows(SPLITS[k]) for k in ('train','diagnosis','validation')]
    if any(r['seed'] not in SPLITS['train'] or r['truth']['novel_present'] for r in train):raise ValueError('training firewall')
    base=decoder('continuous_v1')
    observer.emit('execute',run=1,model_sha=base.fingerprint())
    baseline=predict(base,diagnostic,observer=observer,prefix='diagnosis/baseline')
    candidates=[]
    for regularization in REGULARIZATION:
        parameters=fit_numeric([r['signed_features'] for r in train],[r['truth']['occurred'] for r in train],regularization)
        calibrated,selected,trials=calibration(diagnostic,parameters,base)
        candidates.append({'parameters':calibrated,'selected_calibration':selected,'trials':trials})
    feasible=[c for c in candidates if c['selected_calibration']['noisy_fpr']<=.10]
    chosen=min(feasible,key=lambda c:(-c['selected_calibration']['balanced_accuracy'],c['selected_calibration']['brier'])) if feasible else min(candidates,key=lambda c:c['selected_calibration']['noisy_fpr'])
    candidate=NoiseDecoder(chosen['parameters'],base)
    bp=predict(base,validation,observer=observer,prefix='validation/baseline')
    cp=predict(candidate,validation,observer=observer,prefix='validation/candidate')
    b,c=grouped(validation,bp),grouped(validation,cp)
    strict=(c['conditions']['noisy']['fpr']<=.10 and c['all']['fnr']<=.25 and
            c['all']['balanced_accuracy']>=.80 and c['all']['brier']<b['all']['brier'])
    gate=correction_gate(directory/'dios',b['all'],c['all'])
    accepted=strict and gate['accepted']
    # Record strict acceptance through the original cognitive API as well.
    from examples.dios_nous.cognition import CognitiveSession,EvidenceEvent
    from examples.dios_nous.integration import critical_review
    with CognitiveSession(directory/'strict.sqlite',directory/'strict.anchor') as session:
        session.append(EvidenceEvent(1,23,1,'A' if accepted else 'B',1,1))
        review=critical_review(session,scope=23,claim=1,as_of=1,proposal='A')
    observer.emit('self_correct',run=2,accepted=accepted,candidate_sha=candidate.fingerprint(),strict_review=review)
    observer.close()
    frozen={'schema':'nasuraya.noise-model/1','splits':SPLITS,'implementation':implementation(),
            'class_model_sha':base.fingerprint(),'parameters':chosen['parameters'],
            'model_sha':candidate.fingerprint(),'validation_accepted':accepted}
    frozen['sha256']=digest(frozen)
    report={'baseline_diagnosis':grouped(diagnostic,baseline),'candidates':candidates,
        'validation_baseline':b,'validation_candidate':c,'strict_accepted':accepted,'dios':gate,
        'strict_dios':review,'elapsed_seconds':time.perf_counter()-start,'training_windows':len(train)}
    stream_study.write(directory/'frozen-model.json',frozen)
    stream_study.write(directory/'development.json',report)
    return report


def load_model(path):
    frozen=json.loads(Path(path).read_text(encoding='utf-8'));expected=frozen.pop('sha256')
    if digest(frozen)!=expected or frozen['schema']!='nasuraya.noise-model/1':raise ValueError('noise model integrity')
    base=decoder('continuous_v1');model=NoiseDecoder(frozen['parameters'],base)
    if base.fingerprint()!=frozen['class_model_sha'] or model.fingerprint()!=frozen['model_sha']:raise ValueError('noise model lineage')
    return frozen,model,expected


def test(directory,frozen_path):
    frozen,model,sha=load_model(frozen_path)
    if frozen['implementation']!=implementation() or frozen['splits']!=json.loads(canonical(SPLITS)):
        raise ValueError('frozen evaluator or split changed')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    observer=DiosObserver(directory/'observer.jsonl');output={'frozen_sha256':sha,'groups':{},'adaptation_on_test':False}
    predictions={}
    for group in ('test','novel','shift'):
        start=time.perf_counter();data=rows(SPLITS[group],novel=group=='novel',shift=group=='shift')
        base=decoder('continuous_v1')
        models={'legacy':decoder(),'stage2':base,'candidate':model,'selected':model if frozen['validation_accepted'] else base}
        pred={name:predict(m,data,observer=observer if name=='candidate' else None,prefix=group) for name,m in models.items()}
        for name in ('random','always_none','always_present','visible_label'):
            values=[]
            for row in data:
                rng=random.Random(row['seed']*1000+row['tick'])
                label=('none' if rng.random()<.5 else rng.choice(CLASSES[1:])) if name=='random' else row['label'] if name=='visible_label' else 'left_palm:mechanical' if name=='always_present' else 'none'
                location,kind=label.split(':') if label!='none' else ('none','none')
                p=.5 if name=='random' else .99 if label!='none' else .01
                values.append(Prediction(label!='none',p,location,kind,.59 if label!='none' else 0.,.5,False))
            pred[name]=values
        output['groups'][group]={'metrics':{name:grouped(data,p) for name,p in pred.items()},
            'paired_stream_bootstrap':stream_study.cluster_interval(data,pred['stage2'],pred['candidate']),
            'elapsed_seconds':time.perf_counter()-start}
        predictions[group]=[{'seed':r['seed'],'tick':r['tick'],'condition':r['condition'],'truth':r['truth'],
            'state_sha':r['state_sha'],'predictions':{name:asdict(p[i]) for name,p in pred.items()}} for i,r in enumerate(data)]
    observer.close();stream_study.write(directory/'report.json',output)
    stream_study.write(directory/'predictions.json.gz',predictions,compressed=True)
    return output


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=('develop','test'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--frozen',type=Path)
    args=parser.parse_args()
    if args.phase=='develop':r=develop(args.output);print(json.dumps({'accepted':r['strict_accepted'],'validation':r['validation_candidate']}))
    elif args.frozen is None:parser.error('test requires frozen parameters')
    else:test(args.output,args.frozen);print(json.dumps({'output':str(args.output)}))
