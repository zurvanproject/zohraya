"""Conservative pressure bounds for flat, axis-aligned ball-pad contacts.

Bounds are expressed about the foot contact site. Only the rigid ball pad is
used; independently articulated toes do not enlarge its support rectangle.
This is a flat-ground approximation, not a general terrain contact model.
"""
import numpy as np
import mujoco


def support_bounds(model, inset=.9):
    if not 0 < inset < 1:
        raise ValueError('inset must be strictly between zero and one')
    out=[]
    for side in ('L','R'):
        g=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'ball_'+side)
        s=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_SITE,'foot_contact_'+side)
        if g<0 or s<0 or model.geom_type[g]!=mujoco.mjtGeom.mjGEOM_BOX:
            raise ValueError('named box pad and contact site required')
        if (model.geom_bodyid[g]!=model.site_bodyid[s]
                or not np.allclose(model.geom_quat[g],[1,0,0,0])
                or not np.allclose(model.site_quat[s],[1,0,0,0])):
            raise ValueError('pad/site must share an axis-aligned body frame')
        center=model.geom_pos[g,:2]-model.site_pos[s,:2]
        half=model.geom_size[g,:2]*inset
        out.append([center[0]-half[0],center[0]+half[0],center[1]-half[1],center[1]+half[1]])
    return np.array(out)
