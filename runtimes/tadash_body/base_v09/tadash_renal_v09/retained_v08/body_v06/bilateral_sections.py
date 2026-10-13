"""Per-leg lever fixtures; no change to external anatomy or resource stocks.

Knee and ankle copy the existing representative *per-joint* section. Hip is
an explicit new, unvalidated torque ceiling, not a verified muscle allocation.
All eight channels use one fuel/reserve/water/material ledger in BodyLoop.
"""
from copy import deepcopy
from baseline.motion.sections import section_models

def bilateral_sections():
    old = {s['id']: s for s in section_models()}
    sections = {k: deepcopy(old[k]) for k in ('elbow', 'tail')}
    for side in ('L', 'R'):
        for name in ('knee', 'ankle'):
            key = name + '_' + side
            sections[key] = {**deepcopy(old[name]), 'id': key,
                             'source': 'retained representative per-joint fixture'}
        key = 'hip_' + side
        sections[key] = {
            'id': key, 'muscle_force_N': 9000., 'muscle_moment_arm_m': .065,
            'tendon_allowable_force_N': 10000., 'bone_allowable_moment_Nm': 750.,
            'joint_allowable_moment_Nm': 450., 'external_load_arm_m': .30,
            'external_force_ceiling_N': 1500.,
            'status': 'new assumed hip torque fixture; no validated anatomy or tissue',
        }
    return sections
