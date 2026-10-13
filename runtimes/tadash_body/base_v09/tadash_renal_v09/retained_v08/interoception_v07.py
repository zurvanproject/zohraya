"""Read-only functional sensory routes over the realized V06 body.

Named routes are engineering analogies, not nerve recordings or neuronal
simulation. Gas stores are liters in the existing proxy model, heat is joules,
and no synthetic sensory value is converted into a medical measurement.
Fast physical safety uses unfiltered owner data and never waits for this layer.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
from cognitive_workspace_v07 import numeric,canonical,digest

SCHEMA='tadash-functional-sensory-routes/0.7'


def clamp(x):return min(1.,max(0.,x))


class SensoryRoutes:
    def __init__(self,physical):
        self.time_s=physical.state.time_s
        self.frames=0
        self.lowpass=dict(gas_stress=0.,resource_stress=0.,pain_L=0.,pain_R=0.,tail_hazard=0.)
        self.delayed_integrative_proxy=0.
        self.raw=self._owner_values(physical)
        self.last=None

    @staticmethod
    def _owner_values(p):
        s=p.body.state;g=p.coupling.gas
        return dict(fuel_J=s.fuel_J,reserve_J=s.reserve_J,water_L=s.free_water_L,
            heat_fraction=s.heat_J/195000.,usable_o2_L=g.usable_o2_L,co2_store_L=g.co2_store_L,
            max_leg_fatigue=max(v for k,v in s.fatigue.items() if k.startswith(('hip_','knee_','ankle_'))),
            left_leg_fatigue=max(s.fatigue[j+'_L'] for j in ('hip','knee','ankle')),
            right_leg_fatigue=max(s.fatigue[j+'_R'] for j in ('hip','knee','ankle')),
            feet_m=deepcopy(p.state.feet_m),tail_angle_rad=deepcopy(p.state.tail_angle_rad))

    def observe(self,frame,physical):
        t=frame['t_s'];dt=frame['ledger']['dt_s']
        if abs(t-self.time_s-dt)>1e-8 or abs(t-physical.state.time_s)>1e-8:
            raise ValueError('sensory routes must read one newly realized owner frame')
        raw=self._owner_values(physical)
        hazards=frame['motor']['regional_hazard']
        # These mappings preserve side and modality. They do not simulate
        # conduction velocities, receptor populations, IX/X afferents, or NTS.
        targets=dict(gas_stress=max(clamp((2.-raw['usable_o2_L'])/2.),clamp((raw['co2_store_L']-.22)/.38)),
            resource_stress=max(clamp((150000.-raw['fuel_J'])/150000.),clamp((raw['heat_fraction']-.65)/.35)),
            pain_L=max(hazards[j+'_L'] for j in ('hip','knee','ankle')),
            pain_R=max(hazards[j+'_R'] for j in ('hip','knee','ankle')),
            tail_hazard=hazards['tail'])
        previous=dict(self.lowpass)
        self.delayed_integrative_proxy=max(previous.values())
        for k,v in targets.items():
            tau=1. if k in ('gas_stress','resource_stress') else .15
            a=1.-math.exp(-dt/tau)
            self.lowpass[k]+=a*(v-self.lowpass[k])
        self.time_s=t;self.frames+=1;self.raw=raw
        self.last=dict(source='realized_V06_owner_frame',sampled_at_s=t,raw=deepcopy(raw),
            ascending_route_proxies=deepcopy(self.lowpass),
            delayed_integrative_proxy=self.delayed_integrative_proxy,
            left_contact_N=frame['contact']['by_foot_N']['L'],
            right_contact_N=frame['contact']['by_foot_N']['R'],
            capture_margin_m=frame['balance']['capture_margin_m'],
            fast_owner_protection_is_unfiltered=True,biophysical_nerve_model=False)
        return deepcopy(self.last)

    def view(self):
        return dict(sampled_at_s=self.time_s,owner_frame_count=self.frames,
            raw=deepcopy(self.raw),ascending_route_proxies=deepcopy(self.lowpass),
            delayed_integrative_proxy=self.delayed_integrative_proxy,
            biophysical_nerve_model=False)

    def conservation_pause(self):
        r=self.raw
        reasons=[]
        # Prespecified extra conservative controller thresholds. Not clinical
        # cutoffs, measured human values, or learned morphology.
        if r['fuel_J']<100000.:reasons.append('fuel_conservation')
        if r['heat_fraction']>.80:reasons.append('heat_conservation')
        if r['max_leg_fatigue']>.52:reasons.append('fatigue_conservation')
        return dict(requested=bool(reasons),reasons=reasons,
            thresholds=dict(fuel_J=100000.,heat_fraction=.80,leg_fatigue=.52))

    def checkpoint(self):
        p=canonical(dict(schema=SCHEMA,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            state=deepcopy(self.__dict__)))
        return dict(payload=p,sha256=digest(p))

    @classmethod
    def restore(cls,c,physical):
        try:
            p=c['payload']
            if digest(p)!=c['sha256'] or p['schema']!=SCHEMA or p['source_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
                raise ValueError('sensory checkpoint integrity/source mismatch')
            obj=cls(physical);obj.__dict__.update(deepcopy(p['state']))
            if abs(obj.time_s-physical.state.time_s)>1e-8:raise ValueError('sensory/physical clocks differ')
            for v in obj.lowpass.values():numeric(v,'ascending proxy',0.,1.)
            if obj.raw!=cls._owner_values(physical):raise ValueError('sensory owner values differ')
            return obj
        except (KeyError,TypeError,AttributeError) as ex:raise ValueError('malformed sensory checkpoint') from ex
