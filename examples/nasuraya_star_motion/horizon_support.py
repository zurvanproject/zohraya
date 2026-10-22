"""Opt-in receding-horizon stand proposal, using the existing native solver.

Each candidate applies one bounded acceleration command, then follows the
existing coordinator for five future ticks. Forecast impulses are not replayed.
Only the first action is executed on the owner. Not enabled by default.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import math
from pathlib import Path

from coordinated_support import CoordinatedSupport
from posture_step import PostureLoop, checksum

POLICY=dict(horizon_ticks=6,scales=[.5,0.],minimum_gain_J=.01,
            position_regret_m=.001,speed_regret_m_s=.003,
            quiet_speed_m_s=.001)


def future_environment(e):
    # Hold environmental conditions/command constant; one-shot perturbations
    # belong only to the observed first tick, not to the predicted future.
    return replace(e,external_impulse_N_s=[0.,0.],prescribed_slip_m={},
                   body=replace(e.body,injury_events_kg={},stimuli={}))


def rollout(owner,e,scale):
    trial=deepcopy(owner)
    first=(CoordinatedSupport.step(trial,e) if scale is None
           else trial._integrate_once(e,scale))
    frames=[first]
    future=future_environment(e)
    for _ in range(POLICY['horizon_ticks']-1):
        if not frames[-1]['balance']['model_valid']:
            break
        frames.append(CoordinatedSupport.step(trial,future))
    return trial,frames


class HorizonSupport(CoordinatedSupport):
    def step(self,e):
        # Quiet, stationary support has no proposed economy change. Still run
        # native validation/arbitration; invalid data never bypasses it.
        active=(math.hypot(*self.state.velocity_m_s)>POLICY['quiet_speed_m_s']
                or math.hypot(*e.external_impulse_N_s)>0)
        eligible=(e.command=='stand' and self.state.phase=='double_support'
                  and self.state.swing is None and not self.state.reflex_recovery and active)
        if not eligible:
            return CoordinatedSupport.step(self,e)
        before=self.checkpoint()
        baseline,base_frames=rollout(self,e,None)
        best_cost=sum(f['ledger']['fuel_used_J'] for f in base_frames)
        selected=None;probes=1
        if all(f['balance']['model_valid'] for f in base_frames):
            for scale in POLICY['scales']:
                trial,frames=rollout(self,e,scale);probes+=1
                valid=(len(frames)==len(base_frames) and all(
                    f['balance']['model_valid'] and f['contact']['joint_support_fraction']>=.999
                    and f['balance']['capture_margin_m']>=0 for f in frames))
                if not valid:continue
                # Constrain the first tick and the horizon endpoint; compare
                # each state's own native target. No checkpoint manipulation.
                for j in (0,-1):
                    f,b=frames[j],base_frames[j]
                    valid=valid and (
                        f['posture']['phase']==b['posture']['phase']
                        and f['posture']['swing']==b['posture']['swing']
                        and f['posture']['walk_steps']==b['posture']['walk_steps']
                        and f['posture']['protective_steps']==b['posture']['protective_steps']
                        and math.dist(f['posture']['com_m'],f['posture']['target_com_m'])
                            <= math.dist(b['posture']['com_m'],b['posture']['target_com_m'])+POLICY['position_regret_m']
                        and math.hypot(*f['posture']['velocity_m_s'])
                            <= math.hypot(*b['posture']['velocity_m_s'])+POLICY['speed_regret_m_s'])
                cost=sum(f['ledger']['fuel_used_J'] for f in frames)
                if valid and cost<best_cost-POLICY['minimum_gain_J']:
                    selected,best_cost=scale,cost
        if self.checkpoint()!=before:
            raise AssertionError('forecast mutated owner')
        actual=(CoordinatedSupport.step(self,e) if selected is None
                else self._integrate_once(e,selected))
        actual['posture']['horizon_governor']=dict(
            adjusted=selected is not None,acceleration_scale=selected,
            horizon_ticks=POLICY['horizon_ticks'],candidate_probes=probes,
            predicted_horizon_fuel_J=best_cost,
            assumption='future conditions held constant; observed impulses/slips/injury events not repeated',
            scope='same-model forecast; one actual owner tick')
        return actual


def sources():
    root=Path(__file__).parent
    return {n:hashlib.sha256((root/n).read_bytes()).hexdigest()
            for n in ('horizon_support.py','coordinated_support.py')}


def checkpoint(body):
    payload=dict(schema='nasuraya-horizon-support/1',sources=sources(),policy=deepcopy(POLICY),
        native=body.checkpoint(),controller={k:deepcopy(getattr(body,k)) for k in
         ('support_searches','support_adjustments','last_support_adjustment') if hasattr(body,k)})
    return dict(payload=payload,sha256=checksum(payload))


def restore(envelope):
    if not isinstance(envelope,dict) or set(envelope)!={'payload','sha256'}:
        raise ValueError('horizon envelope')
    p=envelope['payload']
    if (not isinstance(p,dict) or set(p)!={'schema','sources','policy','native','controller'}
        or envelope['sha256']!=checksum(p) or p['schema']!='nasuraya-horizon-support/1'
        or p['sources']!=sources() or p['policy']!=POLICY):
        raise ValueError('horizon source/policy/checksum mismatch')
    allowed={'support_searches','support_adjustments','last_support_adjustment'}
    if not isinstance(p['controller'],dict) or set(p['controller'])-allowed:
        raise ValueError('horizon controller fields')
    for k in ('support_searches','support_adjustments'):
        if k in p['controller'] and (type(p['controller'][k]) is not int or p['controller'][k]<0):
            raise ValueError('horizon controller counter')
    body=PostureLoop.restore(p['native']);body.__class__=HorizonSupport
    for k,v in p['controller'].items():setattr(body,k,deepcopy(v))
    return body
