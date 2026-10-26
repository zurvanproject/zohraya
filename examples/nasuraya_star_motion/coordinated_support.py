"""One-tick landing/transfer/stop governor with confirmed waypoint feedback.

Native pressure, force, friction, tail, gas and energy limits are untouched.
Near landing, walking weight transfer or native stand/closure, accelerations
are tried on isolated native clones;
the chosen command is then integrated once by the real owner.
"""
from copy import deepcopy
from posture_step import PostureLoop


class CoordinatedSupport(PostureLoop):
    def _preview(self,contact,cop,desired_cmp,proposed_feet,dt,e):
        scale=getattr(self,'_cmp_scale',None)
        if scale is not None and not self.state.reflex_recovery and contact['feasible']:
            com=self.state.com_m
            target=[com[k]+scale*(desired_cmp[k]-com[k]) for k in range(2)]
            candidate=self.contact.solve(self.state.feet_m,self._active(),target,self.weight,e.inactive_patches)
            if candidate['feasible']:
                selected=list(candidate['cop_m']);contact.clear();contact.update(candidate)
                cop[:]=selected;contact['cop_m']=cop;desired_cmp[:]=selected
        return super()._preview(contact,cop,desired_cmp,proposed_feet,dt,e)

    def _integrate_once(self,e,scale=None):
        cursor=deepcopy(getattr(self,'star_started',None))
        self._cmp_scale=scale
        try:frame=PostureLoop.step(self,e)
        finally:self._cmp_scale=None
        if cursor is not None:
            self.star_started=cursor
            for event in frame['posture']['events_this_frame']:
                if event['name']=='touchdown' and event.get('kind')=='walk':
                    side=event['side'];i=cursor[side];targets=self.star_targets[side]
                    if i<len(targets) and max(abs(a-b) for a,b in zip(event['position_m'],targets[i]))<1e-9:
                        cursor[side]+=1
        return frame

    def _needs_support_prediction(self,e):
        q=self.state.swing
        # Both stopping and walking can leave settle within this tick. Keep
        # prediction through the subsequent braking/weight-transfer phase.
        transfer=e.command=='walk' and self.state.phase in ('double_support','shift')
        return e.command=='stand' or transfer or self.state.phase=='settle' or (q is not None and q['kind']=='walk' and q['progress']>.85)

    def step(self,e):
        near_landing=self._needs_support_prediction(e)
        selected=None;diagnostic=None
        if near_landing and self.state.phase!='failed':
            trial=deepcopy(self);predicted=trial._integrate_once(e)
            self.support_searches=getattr(self,'support_searches',0)+1
            if not predicted['balance']['model_valid'] and predicted['posture']['failed_reason']=='insufficient_joint_or_energy_support':
                for scale in (.75,.5,.25,0.):
                    probe=deepcopy(self);candidate=probe._integrate_once(e,scale)
                    if candidate['balance']['model_valid']:
                        selected=scale
                        diagnostic=dict(rejected_reason=predicted['posture']['failed_reason'],acceleration_scale=scale,
                            probe_support_fraction=candidate['contact']['joint_support_fraction'])
                        break
        frame=self._integrate_once(e,selected)
        if selected is not None:
            self.support_adjustments=getattr(self,'support_adjustments',0)+1
            self.last_support_adjustment=diagnostic
        frame['posture']['coordination_governor']=dict(acceleration_scale=selected,adjusted=selected is not None,
            waypoint_cursor=deepcopy(getattr(self,'star_started',None)),
            prediction_scope='same-model one-tick rollout; not independent empirical evidence')
        return frame


def attach(body,controller=None):
    p=body.owner.physical;p.__class__=CoordinatedSupport
    if controller:
        for k,v in controller.items():setattr(p,k,deepcopy(v))
    return body
