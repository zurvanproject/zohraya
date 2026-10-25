"""Observe final joint speeds in an exact replay of the unsettled baseline."""
import argparse,gzip,hashlib,json
from pathlib import Path
from unittest.mock import patch
import mujoco
import numpy as np
from . import stepping
from .canon_trial import CANDIDATE
from .experience_balance import read_plan,write_json


def diagnose(folder):
    folder=Path(folder);read_plan(folder)
    source=folder/'secondary-new_context_10-+0.000.json'
    stored=json.loads(source.read_text());observed={};original_load=stepping.load
    def observe_load(*args,**kwargs):
        # Return exactly the original objects; no controller, force or state edit.
        model,data=original_load(*args,**kwargs)
        observed.update(model=model,data=data)
        return model,data
    with patch.object(stepping,'load',side_effect=observe_load):
        result=stepping.walk_trial(label=stored['result']['label'],model_dir=CANDIDATE,
            geometry_support=True,com_bias_x_m=0.,**{k:v for k,v in stored['case'].items() if k!='id'})
    trace=result.pop('trace')
    canonical=lambda r:json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False)
    blob=gzip.compress(json.dumps(trace,separators=(',',':')).encode(),mtime=0)
    if canonical(result)!=canonical(stored['result']) or hashlib.sha256(blob).hexdigest()!=stored['trace_sha256']:
        raise ValueError('observation changed the recorded outcome')
    model,data=observed['model'],observed['data'];top=[]
    for dof in np.argsort(abs(data.qvel))[::-1][:10]:
        joint=int(np.searchsorted(model.jnt_dofadr,dof,side='right')-1)
        axis=int(dof-model.jnt_dofadr[joint]);kind=int(model.jnt_type[joint])
        unit='m/s' if kind==2 or (kind==0 and axis<3) else 'rad/s'
        top.append(dict(joint=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,joint),
                        dof=int(dof),axis=axis,speed=float(data.qvel[dof]),unit=unit))
    report=dict(source=source.name,all_result_fields_and_trace_identical=True,
                observation_only=True,final_max_generalized_speed=result['final_max_generalized_speed'],
                settle_limit=.05,top_joint_speeds=top,root_velocity=data.qvel[:6].tolist(),
                native_apply_allowed=False)
    write_json(folder/'settling-diagnosis.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True)
    diagnose(p.parse_args().evidence)
