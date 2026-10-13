"""Bounded functional nociception, not evidence of felt pain. stdlib only.
All gains/times/thresholds are design fixtures, not human physiological fits.
"""
import math, json
from collections import deque
from pathlib import Path

def unit(x):
    if not isinstance(x,(float,int)) or not math.isfinite(x) or not 0<=x<=1: raise ValueError('expected finite unit interval')
    return float(x)

class PainSystem:
    def __init__(self, regions=None, breath_gain=.25):
        self.regions=regions or json.loads(Path(__file__).with_name('regions.json').read_text())
        self.gain=unit(breath_gain);self.time=0.;self.calming=0.;self.enabled=True
        self.slow={k:0. for k in self.regions};self.sens={k:0. for k in self.regions}
        self.queue=deque();self.last={};self.memory=deque(maxlen=128)
    def step(self, stimuli=None, dt=.1, paced=False, oxygen=1., co2_ok=1., ventilation_ok=True, inhale_s=4., exhale_s=6.):
        if not isinstance(dt,(int,float)) or not math.isfinite(dt) or not 0<dt<=1:raise ValueError('dt outside (0,1]')
        oxygen=unit(oxygen);co2_ok=unit(co2_ok)
        if any(not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in [inhale_s,exhale_s]): raise ValueError('invalid breath timing')
        stimuli=stimuli or {};checked={}
        for k,v in stimuli.items():
            if k not in self.regions:raise ValueError('unknown region')
            if set(v)-{'mechanical','thermal','chemical','ischemia','damage','nerve_injury','touch'}:raise ValueError('unknown modality')
            checked[k]={a:unit(b) for a,b in v.items()}
        # Validate completely before mutating; no hidden simulated time.
        self.time+=dt
        available=bool(paced and ventilation_ok and oxygen>=.9 and co2_ok>=.9 and 6<=inhale_s+exhale_s<=12)
        self.calming+=(float(available)-self.calming)*(1-math.exp(-dt/12))
        delivered={}
        while self.queue and self.queue[0][0]<=self.time+1e-9:
            _,k,x=self.queue.popleft();delivered[k]=max(x,delivered.get(k,0.))
        rows=[]
        for k,meta in self.regions.items():
            s=checked.get(k,{});get=lambda key:s.get(key,0.)
            physical=max(get('mechanical'),get('thermal'),get('chemical'),get('ischemia'))
            direct=meta['direct_nociception_proxy']
            # Injury warning is independent of the sensory channel and breath.
            danger=max(physical,get('damage'),get('nerve_injury'))
            afferent=max(physical*direct,get('nerve_injury'))
            self.sens[k]=min(.5,max(0.,self.sens[k]+dt*(.03*get('damage')-.02*(danger==0))))
            fast=min(1.,afferent*(1+self.sens[k])+.15*get('touch')*self.sens[k])
            self.queue.append((self.time+.2,k,fast))
            self.slow[k]+=(afferent-self.slow[k])*(1-math.exp(-dt/2))
            spinal=max(delivered.get(k,0.),.65*self.slow[k]);ascending=min(1.,spinal)
            modulated=ascending*(1-self.gain*(self.calming if available else 0.)) if self.enabled else 0.
            intensity=10*modulated
            # Bounded control score; no claim of phenomenological unpleasantness.
            aversive=min(3.5,3.5*modulated)
            withdraw=bool(danger>=.65);limit=max(0.,1-danger)
            referred=meta.get('referred_to') if ascending>0 else None
            rows.append({'id':k,'raw_hazard':danger,'fast_afferent':fast,'slow_afferent':self.slow[k],
                         'spinal_or_trigeminal':spinal,'thalamic_relay_proxy':ascending,
                         'somatosensory_intensity_proxy_0_10':intensity,'insula_ACC_control_score_0_3_5':aversive,
                         'PAG_RVM_gain_proxy':1-self.gain*(self.calming if available else 0.),'withdraw_or_unload':withdraw,
                         'motor_fraction_cap':limit,'referred_to':referred})
        peak=max(rows,key=lambda x:x['somatosensory_intensity_proxy_0_10'])
        out={'time_s':self.time,'breath_phase':'inhale' if self.time%(inhale_s+exhale_s)<inhale_s else 'exhale',
             'breath_modulation_available':available,'calming_proxy':self.calming,'regions':rows,
             'brain_workspace':{'source':peak['id'],'intensity_proxy':peak['somatosensory_intensity_proxy_0_10'],
                                'attention_priority':max(x['raw_hazard'] for x in rows),
                                'global_motor_cap':min(x['motor_fraction_cap'] for x in rows),
                                'protective_stop':any(x['withdraw_or_unload'] for x in rows)}}
        if any(x['raw_hazard']>=.65 for x in rows):self.memory.append({'t':self.time,'hazards':[x['id'] for x in rows if x['raw_hazard']>=.65]})
        self.last=out;return out
    def comfort_pause(self):
        """Disable aversive/intensity output, retain hazard protection and injury input."""
        self.enabled=False
    def resume(self):self.enabled=True
    def apply_to_motor(self,requested_force_N,frame=None):
        if not isinstance(requested_force_N,(float,int)) or not math.isfinite(requested_force_N) or requested_force_N<0:raise ValueError('invalid force')
        b=(frame or self.last)['brain_workspace']
        return 0. if b['protective_stop'] else requested_force_N*b['global_motor_cap']
