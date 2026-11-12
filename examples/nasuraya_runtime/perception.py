"""Bounded signed sensory memory and a numeric-only occurrence readout.

No event labels, seeds, stimulus metadata or simulator calls enter this module.
The existing decoder still estimates class/intensity; this readout addresses
occurrence under noise and exposes the limits of that separation.
"""
from dataclasses import dataclass, field
import math

from examples.tadash_interoception.sensory import AfferentFrame, finite
from examples.tadash_interoception.state import digest
from examples.tadash_interoception.model import Prediction

DIMENSIONS = 25


@dataclass
class SignedTrace:
    time: float = 0.
    values: list = field(default_factory=list)

    def step(self, frame):
        if type(frame) is not AfferentFrame or not math.isclose(frame.timestamp-self.time,.1,abs_tol=1e-8):
            raise ValueError('consecutive numeric afferents required')
        self.values=(self.values+[list(frame.values)])[-64:]
        self.time=frame.timestamp

    def features(self):
        if len(self.values)<12:raise ValueError('twelve signed observations required')
        # Negative samples estimate a symmetric noise floor without truth labels.
        sigma=max(.02,min(.5,math.sqrt(2*sum(min(0.,v)**2 for r in self.values for v in r)/(6*len(self.values)))))
        recent=self.values[-12:]; features=[]
        for width in (1,3,6,12):
            scores=[max(sum(r[c] for r in recent[i:i+width]) for i in range(13-width))/(sigma*math.sqrt(width))
                    for c in range(6)]
            # The occurrence detector is region permutation invariant; class
            # information remains in the existing region-indexed internal state.
            features.extend(sorted((max(-10.,min(50.,x)) for x in scores),reverse=True))
        return tuple(features+[sigma])

    def checkpoint(self):
        value={'time':self.time,'values':self.values}
        return {'schema':'nasuraya.signed-trace/1','state':value,'sha256':digest(value)}

    @classmethod
    def restore(cls, envelope):
        if type(envelope) is not dict or set(envelope)!={'schema','state','sha256'}:
            raise ValueError('closed signed-trace envelope required')
        value=envelope['state']
        if envelope['schema']!='nasuraya.signed-trace/1' or digest(value)!=envelope['sha256']:
            raise ValueError('signed trace integrity mismatch')
        if set(value)!={'time','values'} or type(value['values']) is not list or len(value['values'])>64:
            raise ValueError('bounded signed trace required')
        finite(value['time'],0,1e6)
        for row in value['values']:
            if type(row) is not list or len(row)!=6:raise ValueError('six signed values required')
            for v in row:finite(v,-2,2)
        return cls(value['time'],[r.copy() for r in value['values']])


def sigmoid(value):
    return 1/(1+math.exp(-max(-35.,min(35.,value))))


class NoiseDecoder:
    requires_signed_trace=True

    def __init__(self, parameters, class_model):
        keys={'means','scales','weights','bias','temperature','threshold','regularization'}
        if type(parameters) is not dict or set(parameters)!=keys:raise ValueError('closed detector parameters required')
        for key in ('means','scales','weights'):
            if len(parameters[key])!=DIMENSIONS:raise ValueError('detector dimension mismatch')
            for x in parameters[key]:finite(x,-1e4,1e4)
        if any(x<=0 for x in parameters['scales']):raise ValueError('positive scales required')
        for key,low,high in [('bias',-100,100),('temperature',.1,10),('threshold',.01,.99),('regularization',0,1)]:
            finite(parameters[key],low,high)
        self.parameters=parameters;self.class_model=class_model

    def fingerprint(self):
        return digest({'parameters':self.parameters,'class_model':self.class_model.fingerprint()})

    def probability(self, features):
        if type(features) is not tuple or len(features)!=DIMENSIONS:raise ValueError('numeric signed features only')
        for x in features:finite(x,-10,50)
        p=self.parameters
        standardized=[max(-8.,min(8.,(v-m)/s)) for v,m,s in zip(features,p['means'],p['scales'])]
        return sigmoid((p['bias']+sum(w*x for w,x in zip(p['weights'],standardized)))/p['temperature'])

    def predict(self, internal_features, signed_features):
        p=self.probability(signed_features); detected=p>=self.parameters['threshold']
        classified=self.class_model.predict(internal_features)
        return Prediction(detected,p,
            classified.location if detected and classified.occurred else 'unknown' if detected else 'none',
            classified.stimulus_type if detected and classified.occurred else 'unknown' if detected else 'none',
            classified.intensity if detected else 0.,
            classified.confidence if detected and classified.occurred else p if detected else 1-p,
            detected and (classified.novelty_uncertain or not classified.occurred))


def fit_numeric(features, targets, regularization):
    """Fixed-budget full-batch logistic fit; caller owns split/novelty validation."""
    n=len(features)
    if n!=len(targets) or n<20:raise ValueError('matched training data required')
    means=[sum(r[j] for r in features)/n for j in range(DIMENSIONS)]
    scales=[max(1e-4,math.sqrt(sum((r[j]-means[j])**2 for r in features)/n)) for j in range(DIMENSIONS)]
    data=[[max(-8.,min(8.,(x-m)/s)) for x,m,s in zip(r,means,scales)] for r in features]
    weights=[0.]*DIMENSIONS;bias=0.
    for _ in range(400):
        gradients=[0.]*DIMENSIONS; gb=0.
        for row,y in zip(data,targets):
            error=sigmoid(bias+sum(w*x for w,x in zip(weights,row)))-int(y)
            gb+=error
            for j,x in enumerate(row):gradients[j]+=error*x
        bias-=.08*gb/n
        weights=[w-.08*(g/n+regularization*w) for w,g in zip(weights,gradients)]
    return dict(means=means,scales=scales,weights=weights,bias=bias,
                temperature=1.,threshold=.5,regularization=regularization)
