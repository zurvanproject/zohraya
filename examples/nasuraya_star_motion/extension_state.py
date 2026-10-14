"""Explicit persistence for the additive star-motion controller.

A native checkpoint alone does not encode this controller's semantics.
Always use this envelope when continuing coordinated star motion.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from coordinated_support import CoordinatedSupport
from unified_body_v2 import UnifiedBody
from persistent_embodiment_v1 import digest

SCHEMA='nasuraya-coordinated-star/1'
FIELDS=('star_enabled','star_started','star_targets','support_searches','support_adjustments','last_support_adjustment','cursor_semantics')


class StarMotion(CoordinatedSupport):
    def _start_swing(self,side,kind,target,duration):
        if kind=='walk' and self.star_enabled:
            i=self.star_started[side]
            if i<len(self.star_targets[side]):
                proposed=self.star_targets[side][i]
                if math.dist(proposed,self.state.feet_m[side])>self.design['max_step_length_m']:
                    raise ValueError('star target exceeds native reach contract')
                target=proposed;self.star_started[side]+=1
        return super()._start_swing(side,kind,target,duration)


def sources():
    root=Path(__file__).parent
    return {n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('coordinated_support.py','extension_state.py')}


def attach(body,controller):
    p=body.owner.physical;p.__class__=StarMotion
    for k in FIELDS:
        if k in controller:setattr(p,k,deepcopy(controller[k]))
    if type(p.star_enabled) is not bool or set(p.star_started)!={'L','R'} or set(p.star_targets)!={'L','R'}:
        raise ValueError('controller contract')
    for side in ('L','R'):
        targets=p.star_targets[side];count=p.star_started[side]
        if type(count) is not int or not 0<=count<=len(targets)<=100:raise ValueError('controller cursor')
        for v in targets:
            if not isinstance(v,list) or len(v)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in v) or v[2]!=0.:
                raise ValueError('controller target')
    if getattr(p,'cursor_semantics',None)!='confirmed':
        q=p.state.swing
        if q is not None and q['kind']=='walk':
            side=q['side'];i=p.star_started[side]
            if i and p.star_targets[side][i-1]==q['target']:p.star_started[side]-=1
        p.cursor_semantics='confirmed'
    p._validate_state();return body


def checkpoint(body):
    p=body.owner.physical
    controller={k:deepcopy(getattr(p,k)) for k in FIELDS if hasattr(p,k)}
    payload=dict(schema=SCHEMA,sources=sources(),native=body.checkpoint(),controller=controller,
        scope='native body plus explicit motion-controller overlay; no learned model weights')
    return dict(payload=payload,sha256=digest(payload))


def restore(envelope):
    if set(envelope)!={'payload','sha256'} or digest(envelope['payload'])!=envelope['sha256']:
        raise ValueError('extension checksum')
    p=envelope['payload']
    if p['schema']!=SCHEMA or p['sources']!=sources():raise ValueError('extension source/version mismatch')
    return attach(UnifiedBody.restore(p['native']),p['controller'])
