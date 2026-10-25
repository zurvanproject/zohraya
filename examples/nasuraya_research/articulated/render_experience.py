"""Replay the preselected unseen push case and verify it before rendering."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import mujoco
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from .canon_trial import CANDIDATE
from .experience_balance import read_plan,write_json
from .experience_stress import load_policy
from .stepping import walk_trial

CASE='holdout_push_right'  # Chosen before any held-out outcome, also used in the chart.


def capture(folder):
    folder=Path(folder);plan=read_plan(folder);policy,raw=load_policy(folder)
    case=next(c for c in plan['holdouts'] if c['id']==CASE)
    out=folder/'visual-replay';out.mkdir(exist_ok=True)
    checks=[]
    for bias in (0.,policy['selected_bias_m']):
        stored=json.loads((folder/f'holdout-{CASE}-{bias:+.3f}.json').read_text())
        result,poses=walk_trial(label=stored['result']['label'],steps=2,model_dir=CANDIDATE,
            geometry_support=True,com_bias_x_m=bias,capture=True,**{k:v for k,v in case.items() if k!='id'})
        trace=result.pop('trace')
        canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        if canonical(result)!=canonical(stored['result']):
            raise ValueError('visual replay differs from original measured outcome')
        trace_blob=gzip.compress(json.dumps(trace,separators=(',',':'),allow_nan=False).encode(),mtime=0)
        if hashlib.sha256(trace_blob).hexdigest()!=stored['trace_sha256']:
            raise ValueError('visual replay trace differs from original measurement')
        target=out/f'poses-{bias:+.3f}.npz'
        if target.exists():raise ValueError('visual evidence is create-only')
        np.savez_compressed(target,qpos=np.array(poses),time=np.array([r['t'] for r in trace]),
                            tilt=np.array([r['tilt_deg'] for r in trace]))
        checks.append(dict(bias_m=bias,all_result_fields_identical=True,
                           full_trace_identical=True,
                           result_sha256=hashlib.sha256(canonical(result)).hexdigest(),
                           poses_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                           frames=len(poses),measured_seconds=result['measured_seconds']))
        print(json.dumps(checks[-1]),flush=True)
    if (folder/'policy.json').read_bytes()!=raw:raise RuntimeError('policy changed')
    write_json(out/'reproduction.json',dict(case=case,checks=checks,native_apply_allowed=False,
                                          purpose='visual reproduction only; not new tuning evidence'))


def render(folder):
    folder=Path(folder);read_plan(folder);policy,_=load_policy(folder);out=folder/'visual-replay'
    verification=json.loads((out/'reproduction.json').read_text())
    records=[]
    for check in verification['checks']:
        p=out/f'poses-{check["bias_m"]:+.3f}.npz'
        if hashlib.sha256(p.read_bytes()).hexdigest()!=check['poses_sha256']:
            raise ValueError('recorded poses changed')
        records.append(np.load(p))
    measured=[json.loads((folder/f'holdout-{CASE}-{c["bias_m"]:+.3f}.json').read_text())['result']
              for c in verification['checks']]
    model=mujoco.MjModel.from_xml_path(str(CANDIDATE/'nasuraya.xml'))
    model.geom_rgba[0]=[.34,.38,.42,1]  # Display-only floor colour.
    model.vis.headlight.ambient[:]=.45
    data=mujoco.MjData(model)
    width,height=1280,860;panel=640;scene_h=610
    renderer=mujoco.Renderer(model,height=scene_h,width=panel)
    camera=mujoco.MjvCamera();camera.lookat[:]=[-.03,0,.98]
    camera.distance=3.25;camera.azimuth=125;camera.elevation=-12
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    large=ImageFont.truetype(font,26);small=ImageFont.truetype(font,18)
    target=out/'comparison.mp4'
    proc=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
        '-s',f'{width}x{height}','-r','20','-i','-','-an','-c:v','libx264','-preset','fast',
        '-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE)
    last=max(float(r['time'][-1]) for r in records)
    for frame,t in enumerate(np.arange(0,last+.025,.05)):
        canvas=Image.new('RGB',(width,height),(18,24,31));draw=ImageDraw.Draw(canvas)
        for side,record in enumerate(records):
            i=max(0,min(int(np.searchsorted(record['time'],t,side='right')-1),len(record['time'])-1))
            data.qpos[:]=record['qpos'][i];mujoco.mj_forward(model,data)
            renderer.update_scene(data,camera=camera)
            canvas.paste(Image.fromarray(renderer.render()),(side*panel,112))
            draw=ImageDraw.Draw(canvas);x=side*panel+20
            colour=(158,185,214) if side==0 else (114,222,185)
            title='No calibration' if side==0 else f'Saved experience: {policy["selected_bias_m"]*1000:+.0f} mm'
            draw.text((x,15),title,font=large,fill=colour)
            draw.text((x,53),'Same 78 kg / 1.70 m body | same motor limits',font=small,fill=(222,228,235))
            draw.text((x,81),'Unseen +10 N lateral push | friction 0.60',font=small,fill=(222,228,235))
            draw.text((x,731),f'Time {record["time"][i]:5.2f} s  |  pelvis tilt {record["tilt"][i]:.3f} deg',font=large,fill=colour)
            status=f'Whole-trial RMS: {measured[side]["tilt_rms_deg"]:.3f} deg | 2 steps'
            if side:
                delta=100*(measured[1]['tilt_rms_deg']/measured[0]['tilt_rms_deg']-1)
                status+=f' | {delta:+.1f}% error'
            draw.text((x,770),status,font=small,fill=(255,195,105) if side else (222,228,235))
            if 2.9<t<=3.1:draw.text((x,690),'Same 10 N disturbance applied to both',font=small,fill=(255,195,105))
        draw.line((640,0,640,height),fill=(85,97,110),width=2)
        draw.text((20,810),'1x physics replay | all measured outputs reproduced exactly | geometric proxy, no tissue simulation',font=small,fill=(195,207,220))
        proc.stdin.write(canvas.tobytes())
        if frame==120:canvas.save(out/'preview.png')
    proc.stdin.close()
    if proc.wait()!=0:raise RuntimeError('ffmpeg failed')
    renderer.close();print(target)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('phase',choices=['capture','render'])
    ap.add_argument('--evidence',type=Path,required=True);a=ap.parse_args()
    {'capture':capture,'render':render}[a.phase](a.evidence)
