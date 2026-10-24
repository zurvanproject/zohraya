"""Experimental 3-D COM runner; not a joint-level or biological body solver.

Axes: x forward, y left, z up (different from native PostureLoop).
Flight is ballistic. Stance is a massless compressive spring plus an explicitly
accounted bounded radial actuator. A one-step shooting controller chooses foot
placement and actuator gain from the measured apex state. There is no hidden
state reset, velocity clamp, or ground impulse at liftoff.
"""
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares


@dataclass(frozen=True)
class Profile:
    name: str = 'original_250cm_195kg'
    height_m: float = 2.5
    mass_kg: float = 195.
    gravity: float = 9.81
    friction: float = .6
    pressure_limit_kpa: float = 300.
    # Experimental limits, not measured actuator/tissue capacities.
    max_vertical_bw: float = 4.5
    max_actuator_power_w_kg: float = 12.
    max_compression_fraction: float = .25
    max_foot_transfer_m_s: float = 6.

    @property
    def scale(self):return self.height_m/2.5
    @property
    def length(self):return 1.42*self.scale
    @property
    def apex(self):return 1.45*self.scale
    @property
    def stiffness(self):return 40000*(self.mass_kg/195)/self.scale
    @property
    def foot_area(self):return .03926651524980653*self.scale**2
    @property
    def lateral_speed(self):return .2*math.sqrt(self.scale)


def load_profile(path=None):
    path=Path(path) if path else Path(__file__).with_name('running_profile_v01.json')
    return Profile(**json.loads(path.read_text())['profile'])


@dataclass(frozen=True)
class Apex:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    side: int = 1

    def array(self):return np.array([self.x,self.y,self.z,self.vx,self.vy,0.])


def simulate(p, state, control, *, detailed=False, max_step=.008, stiffness_factor=1.):
    """control=(forward foot offset/L, signed lateral offset/L, active gain)."""
    dx,dy,u=map(float,control);L=p.length;g=p.gravity;m=p.mass_kg;k=p.stiffness*stiffness_factor
    horizontal_sq=dx*dx+dy*dy
    if horizontal_sq>=1 or state.vx<=0:return {'ok':False,'reason':'invalid_touchdown_geometry'}
    ztd=L*math.sqrt(1-horizontal_sq)
    if state.z<=ztd:return {'ok':False,'reason':'no_descending_touchdown'}
    td=math.sqrt(2*(state.z-ztd)/g)
    foot=np.array([state.x+state.vx*td+dx*L,state.y+state.vy*td+dy*L,0.])
    initial=np.array([-dx*L,-dy*L,ztd,state.vx,state.vy,-g*td,0.])

    def force(y):
        radius=np.linalg.norm(y[:3]);unit=y[:3]/radius;rdot=np.dot(unit,y[3:6])
        compression=max(0,L-radius);spring=k*compression
        active=u*spring*math.tanh(rdot/.25)
        return (spring+active)*unit,active*rdot,compression

    def rhs(t,y):
        f,power,_=force(y)
        return [*y[3:6],f[0]/m,f[1]/m,f[2]/m-g,power]

    def liftoff(t,y):return np.linalg.norm(y[:3])-L
    liftoff.direction=1;liftoff.terminal=True
    def collapse(t,y):return y[2]-.3*L
    collapse.direction=-1;collapse.terminal=True
    sol=solve_ivp(rhs,[0,2.],initial,events=[liftoff,collapse],rtol=2e-8,atol=1e-10,
                  max_step=max_step,dense_output=detailed)
    if not len(sol.t_events[0]):return {'ok':False,'reason':'collapse_or_no_liftoff'}
    final=sol.y[:,-1];up=final[5]/g
    if up<=0 or final[3]<=0:return {'ok':False,'reason':'no_forward_airborne_apex'}
    pos=foot+final[:3]+final[3:6]*up;pos[2]-=.5*g*up*up
    next_state=Apex(float(pos[0]),float(pos[1]),float(pos[2]),float(final[3]),float(final[4]),-state.side)
    out={'ok':True,'state':asdict(next_state),'control':[dx,dy,u], 'foot_m':foot.tolist(),
         'duration_s':td+sol.t[-1]+up,'stance_s':float(sol.t[-1]),'descent_s':td,'ascent_s':up,
         'actuator_work_j':float(final[6])}
    if detailed:
        samples=sol.sol(np.linspace(0,sol.t[-1],301))
        forces=[];powers=[];compressions=[];energies=[]
        for y in samples.T:
            f,power,compression=force(y);forces.append(f);powers.append(power);compressions.append(compression)
            energies.append(.5*m*np.dot(y[3:6],y[3:6])+m*g*y[2]+.5*k*compression**2)
        forces=np.array(forces);powers=np.array(powers);energies=np.array(energies)
        active=forces[:,2]>1.
        peak=float(max(forces[:,2]));mu=float(max(np.linalg.norm(forces[active,:2],axis=1)/forces[active,2]))
        out['metrics']={'peak_vertical_bw':peak/(m*g),'peak_vertical_n':peak,
            'mean_patch_pressure_peak_kpa':peak/p.foot_area/1000,'required_mu':mu,
            'peak_actuator_power_w':float(max(abs(powers))),
            'max_compression_m':float(max(compressions)),
            'work_energy_relative_error':float(max(abs(energies-energies[0]-samples[6]))/energies[0])}
        errors=[];met=out['metrics']
        if met['peak_vertical_bw']>p.max_vertical_bw:errors.append('vertical_force_limit')
        if met['mean_patch_pressure_peak_kpa']>p.pressure_limit_kpa:errors.append('mean_pressure_limit')
        if mu>p.friction:errors.append('friction_limit')
        if met['peak_actuator_power_w']>p.max_actuator_power_w_kg*m:errors.append('actuator_power_limit')
        if met['max_compression_m']>p.max_compression_fraction*L:errors.append('compression_limit')
        out['limits_ok']=not errors;out['violations']=errors
    return out


class Runner:
    """Atomic apex transitions: invalid plans do not replace the accepted state.

    This controller assumes exact state feedback and an exact nominal model.
    The caller may test plant stiffness mismatch independently of planning.
    """
    def __init__(self,profile, speed=3.,state=None):
        if not 2<=speed<=4:raise ValueError('experimental speed range is 2..4 m/s')
        if profile.mass_kg<=0 or profile.height_m<=0:raise ValueError('positive body dimensions required')
        self.profile=profile;self.speed=speed
        self.state=state or Apex(0,0,profile.apex,speed,profile.lateral_speed,1)
        self.guess=np.array([.245,.09,0.]);self.time=0.;self.feet={};self.last_plan=None

    def plan(self):
        p=self.profile;s=self.state
        # Relative lateral offset must stay on the stance side of the COM.
        def physical(q):return [q[0],s.side*q[1],q[2]]
        def residual(q):
            trial=simulate(p,s,physical(q))
            if not trial['ok']:return [10+q[0],10+q[1],10+q[2]]
            t=trial['state']
            return [(t['z']-p.apex)/p.length,(t['vx']-self.speed)/math.sqrt(p.gravity*p.length),
                    (t['vy']+s.side*p.lateral_speed+1.2*t['y'])/math.sqrt(p.gravity*p.length)]
        def jacobian(q):
            # Absolute perturbations are essential near u=0: relative finite
            # differences otherwise fall below the ODE's integration accuracy.
            columns=[]
            for j in range(3):
                offset=np.zeros(3);offset[j]=1e-4
                columns.append((np.array(residual(q+offset))-np.array(residual(q-offset)))/2e-4)
            return np.array(columns).T
        opt=least_squares(residual,self.guess,jac=jacobian,bounds=([.08,.025,-.3],[.5,.25,.3]),
                          xtol=2e-7,ftol=2e-7,gtol=2e-7,max_nfev=22)
        error=float(np.linalg.norm(residual(opt.x)))
        if not np.isfinite(error) or error>2e-4:
            return {'ok':False,'reason':'no_feasible_plan','residual':error}
        return {'ok':True,'control':physical(opt.x),'guess':opt.x,'residual':error,'evaluations':opt.nfev}

    def step(self,*,feedback=True,fixed_control=None,stiffness_factor=1.):
        plan=self.plan() if feedback else {'ok':True,'control':fixed_control}
        if not plan['ok']:return plan
        result=simulate(self.profile,self.state,plan['control'],detailed=True,stiffness_factor=stiffness_factor)
        if not result['ok']:return result
        foot=np.array(result['foot_m']);side=self.state.side;touchdown=self.time+result['descent_s']
        if side in self.feet:
            previous=self.feet[side];swing=touchdown-previous['liftoff_time_s']
            # Straight-line lower bound only; no swing inertia or full foot arc.
            speed=float(np.linalg.norm(foot-np.array(previous['foot_m']))/swing) if swing>0 else float('inf')
            result['metrics']['foot_transfer_lower_bound_m_s']=speed
            if speed>self.profile.max_foot_transfer_m_s:
                result['violations'].append('foot_transfer_limit');result['limits_ok']=False
        if not result['limits_ok']:
            return {**result,'ok':False,'reason':'engineering_limit'}
        self.feet[side]={'foot_m':foot.tolist(),'liftoff_time_s':touchdown+result['stance_s']}
        self.state=Apex(**result['state']);self.time+=result['duration_s']
        if feedback:self.guess=plan['guess'];self.last_plan=plan
        return result


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile',type=Path)
    ap.add_argument('--speed',type=float,default=3.)
    ap.add_argument('--steps',type=int,default=30)
    args=ap.parse_args()
    if not 1<=args.steps<=1000:ap.error('steps must be between 1 and 1000')
    r=Runner(load_profile(args.profile),args.speed)
    for i in range(args.steps):
        f=r.step();print(json.dumps({'step':i+1,**f}),flush=True)
        if not f['ok']:raise SystemExit(1)
