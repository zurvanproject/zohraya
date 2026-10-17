"""Opt-in, read-only bridge from the canonical native body to research adapters.

No body cycles, action requests, weight training, or private state persistence.
Requires the caller to supply its own already-initialized body instance.
"""
from copy import deepcopy
from .adapters import sensory_sample, geometry, monitoring_stats, project_trajectory


def observe_native_body(body, *, frame_yaw_rad=0.0, decisions=None, events=None,
                        include_geometry=False):
    """Take a bounded research observation without granting control authority.

    Optional decision/event records must originate from the caller's completed
    native trials; this function does not invent outcomes or run a trial.
    Geometry needs the optional pinned CPU torch environment.
    """
    before = deepcopy(body.checkpoint())
    result = {
        "mode": "read_only_research",
        "source_checkpoint_sha256": before["sha256"],
        "sensory": sensory_sample(body),
        "native_cycles_executed": 0,
        "action_requests_executed": 0,
        "model_api_calls": 0,
    }
    if include_geometry:
        result["geometry"] = geometry(body, frame_yaw_rad)
    if decisions is not None:
        result["monitoring"] = monitoring_stats(decisions)
    if events is not None:
        result["trajectory"] = project_trajectory(events)
    after = body.checkpoint()
    if after != before:
        raise RuntimeError("research observation changed canonical body checkpoint")
    return result
