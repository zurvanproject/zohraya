"""Bounded online adaptation of the native coordination governor.

A real controller change, not a learned-outcome claim: adjust preferred CMP
scale after each valid physical step using *actual* recorded joint support.
No safety gate is relaxed. This is an opt-in experiment on disposable bodies.
"""
from copy import deepcopy
from examples.nasuraya_star_motion.coordinated_support import CoordinatedSupport

class AdaptiveSupport(CoordinatedSupport):
    def step(self, environment):
        # Preference is learned from prior owner steps, never preview clones.
        preferred = getattr(self, "adaptive_scale", 1.0)
        preferred = max(0.0, min(1.0, float(preferred)))
        self.adaptive_scale = preferred
        # Run native fail-safe first. Never replace its invalid-frame rejection.
        frame = super().step(environment)
        if frame["balance"]["model_valid"]:
            support = frame["contact"]["joint_support_fraction"]
            if not 0.0 <= support <= 1.0:
                raise ValueError("invalid support feedback")
            # Low support -> more cautious acceleration next time.
            # Comfortable support -> gradual return to the original controller.
            candidate = preferred - 0.1 if support < 0.98 else preferred + 0.02
            self.adaptive_scale = round(max(0.25, min(1.0, candidate)), 5)
            self.adaptive_updates = getattr(self, "adaptive_updates", 0) + 1
        frame["posture"]["adaptive_feedback"] = dict(
            previous_scale=preferred, next_scale=self.adaptive_scale,
            update_count=getattr(self, "adaptive_updates", 0),
            valid=frame["balance"]["model_valid"],
            note="bounded feedback update; improvement not yet established")
        return frame

def attach_adaptive(body):
    """Fresh, explicit opt-in; do not apply to canonical saved state."""
    original=body.checkpoint()
    from examples.nasuraya_star_motion.coordinated_support import attach
    attach(body)
    body.owner.physical.__class__=AdaptiveSupport
    body.owner.physical.adaptive_scale=1.0
    body.owner.physical.adaptive_updates=0
    if body.checkpoint()!=original:
        raise ValueError("attaching adaptive controller changed native checkpoint")
    return body
