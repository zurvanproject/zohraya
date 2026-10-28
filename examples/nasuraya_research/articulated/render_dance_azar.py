"""Portrait replay of measured poses with an original deterministic score.

Rendering never advances, corrects, or interpolates the physical trajectory.
Joint markers and stage rings are cosmetic; they do not enter the simulator.
"""
import os
os.environ.setdefault('MUJOCO_GL','egl')
import argparse
import json
import math
from pathlib import Path
import subprocess
import wave

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .canon_trial import CANDIDATE
from .dance_azar import score, duration, INTRO

PHRASES_FA = {'listen':'شنیدن', 'open':'گشودن', 'left_arc':'قوسِ چپ',
    'right_arc':'قوسِ راست', 'open_sky':'رو به آسمان', 'gather':'گردآوردن',
    'left_wave':'موجِ چپ', 'right_wave':'موجِ راست', 'return':'آرام گرفتن'}


def music(path, bpm, total, sr=48000):
    """New synthesized percussion and plucked tones; no sampled recording."""
    n=round(total*sr)
    audio=np.zeros((n,2),dtype=np.float64)
    rng=np.random.default_rng(20261029)
    def add(x,t,pan=0.,gain=1.):
        start=round(t*sr)
        if start>=n:return
        x=x[:n-start]*gain
        audio[start:start+len(x),0]+=x*np.sqrt((1-pan)/2)
        audio[start:start+len(x),1]+=x*np.sqrt((1+pan)/2)
    def drum(low):
        tt=np.arange(round((.45 if low else .16)*sr))/sr
        noise=rng.normal(0,1,len(tt))
        if low:
            f0,f1=85,43
            phase=2*np.pi*(f1*tt+(f0-f1)*.025*(1-np.exp(-tt/.025)))
            x=np.sin(phase)*np.exp(-tt*12)+.08*noise*np.exp(-tt*80)
        else:
            x=.45*noise*np.exp(-tt*35)+.35*np.sin(2*np.pi*340*tt)*np.exp(-tt*27)
        return x*np.minimum(1,tt/.002)
    for beat in range(32):
        t=INTRO+beat*60/bpm
        add(drum(beat%4 in (0,2)),t,pan=-.12 if beat%4 in (0,2) else .15,gain=.34 if beat%4==0 else .22)
        tt=np.arange(round(.065*sr))/sr
        x=np.diff(rng.normal(0,1,len(tt)+1))*np.exp(-tt*60)
        add(x,t+.5*60/bpm,pan=.30*(-1)**beat,gain=.025)
    notes=[57,60,64,62,57,55,60,57,60,64,67,64,62,60,57,57]
    for k,note in enumerate(notes):
        tt=np.arange(round(2.1*sr))/sr
        f=440*2**((note-69)/12)
        x=sum((1/h**1.65)*np.sin(2*np.pi*f*h*tt)*np.exp(-tt*(2.1+.7*h)) for h in range(1,8))
        x*=np.minimum(tt/.005,1)
        add(x,INTRO+2*k*60/bpm,pan=.22*math.sin(k),gain=.13)
        add(x,INTRO+2*k*60/bpm+.17,pan=-.22*math.sin(k),gain=.035)
    t=np.arange(n)/sr
    drone=(np.sin(2*np.pi*110*t)+.22*np.sin(2*np.pi*165*t))*np.minimum(t/2,1)*np.minimum((total-t)/3,1)
    audio[:,0]+=.012*drone;audio[:,1]+=.012*drone
    audio*=np.minimum(np.arange(n)/(sr*.03),1)[:,None]
    audio*=np.minimum((n-1-np.arange(n))/(sr*.3),1)[:,None]
    audio=np.tanh(audio*1.3)
    peak=float(np.max(abs(audio)))
    pcm=np.int16(np.clip(audio/max(peak,.5)*.86,-1,1)*32767)
    with wave.open(str(path),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(pcm.tobytes())
    return {'sample_rate':sr,'channels':2,'duration_s':n/sr,'seed':20261029,
            'copyright':'Original procedural composition; no sampled recording or external song.',
            'pre_normalization_peak':peak}


def decorate(scene,m,d,time):
    gold=np.array([.74,.46,.20,1.],dtype=np.float32)
    teal=np.array([.10,.46,.45,1.],dtype=np.float32)
    def line(a,b,r,color):
        if scene.ngeom>=scene.maxgeom:return
        g=scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(g,mujoco.mjtGeom.mjGEOM_CAPSULE,np.zeros(3),np.zeros(3),np.eye(3).ravel(),color)
        mujoco.mjv_connector(g,mujoco.mjtGeom.mjGEOM_CAPSULE,r,np.asarray(a),np.asarray(b))
        scene.ngeom+=1
    for radius,color in [(1.05,teal),(1.12,gold)]:
        for j in range(96):
            a,b=2*np.pi*j/96,2*np.pi*(j+1)/96
            line([radius*np.cos(a),radius*np.sin(a),.004],
                 [radius*np.cos(b),radius*np.sin(b),.004],.002,color)
    for j in range(1,m.njnt):
        name=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_JOINT,j)
        if not name.startswith(('shoulder_pitch','elbow_','wrist_pitch','hip_pitch','knee_','hock_pitch','waist_yaw','neck_yaw')):continue
        r=.023 if name.startswith(('shoulder','hip','knee')) else .015
        g=scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(g,mujoco.mjtGeom.mjGEOM_SPHERE,np.array([r,r,r]),d.xanchor[j],np.eye(3).ravel(),gold)
        scene.ngeom+=1


def render(evidence,output,fps=24,preview=False):
    evidence=Path(evidence);output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    protocol=json.loads((evidence/'protocol.json').read_text())
    result=json.loads((evidence/'result.json').read_text())
    if not result['accepted']:
        raise ValueError('Use a complete accepted performance for the presentation replay')
    record=np.load(evidence/'poses.npz')
    bpm=protocol['bpm'];total=duration(bpm)
    m=mujoco.MjModel.from_xml_path(str(CANDIDATE/'nasuraya.xml'));d=mujoco.MjData(m)
    m.geom_rgba[0]=[.032,.052,.063,1]
    m.vis.headlight.ambient[:]=.40;m.vis.headlight.diffuse[:]=.70
    m.vis.quality.shadowsize=4096
    # Bronze technical mannequin; no face or anatomical skin is claimed.
    for g in range(1,m.ngeom):
        name=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,g) or ''
        m.geom_rgba[g]=[.63,.27,.115,1]
        if name.startswith(('horn','ball_','toe_pad_')):m.geom_rgba[g]=[.23,.15,.12,1]
        if name in ('torso_mass','pelvis_mass'):m.geom_rgba[g]=[.30,.15,.10,1]
    width,height,stage_h=720,1280,914
    renderer=mujoco.Renderer(m,height=stage_h,width=width)
    camera=mujoco.MjvCamera();camera.lookat[:]=[-.03,0,.97]
    camera.distance=3.55;camera.azimuth=32;camera.elevation=-14
    regular='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    bold='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    fonts={k:ImageFont.truetype(p,s) for k,p,s in [('title',bold,51),('subtitle',regular,24),('small',regular,18),('phrase',regular,31)]}
    bg=(9,16,21);ivory=(242,228,204);gold=(217,166,91);muted=(153,175,180)
    def label(draw,xy,text,font,fill=ivory,anchor='mm'):
        draw.text(xy,text,font=fonts[font],fill=fill,anchor=anchor,direction='rtl',language='fa')
    sequence=[round(8*fps)] if preview else range(round(total*fps))
    if not preview:
        audio=output.with_suffix('.wav');audio_meta=music(audio,bpm,total)
        proc=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
            '-s',f'{width}x{height}','-r',str(fps),'-i','-','-i',str(audio),'-c:v','libx264',
            '-preset','fast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',
            '-t',str(total),'-movflags','+faststart',str(output)],stdin=subprocess.PIPE)
    for frame in sequence:
        t=frame/fps
        ix=max(0,min(int(np.searchsorted(record['time'],t,side='right')-1),len(record['time'])-1))
        d.qpos[:]=record['qpos'][ix];d.qvel[:]=record['qvel'][ix];mujoco.mj_forward(m,d)
        renderer.update_scene(d,camera=camera);decorate(renderer.scene,m,d,t)
        picture=Image.new('RGB',(width,height),bg)
        picture.paste(Image.fromarray(renderer.render()),(0,157))
        draw=ImageDraw.Draw(picture)
        label(draw,(width/2,50),'رقصِ آذر','title')
        label(draw,(width/2,99),'ناسورایا  |  اجرای نخست','subtitle',gold)
        label(draw,(width/2,136),'بازپخش حرکت ثبت‌شدهٔ مدل مفصلی','small',muted)
        _,_,beat,phrase=score(t,bpm)
        if t<INTRO:phrase='listen'
        label(draw,(width/2,1102),PHRASES_FA[phrase],'phrase',gold)
        for b in range(32):
            x=68+b*(584/31)
            done=beat>=b
            r=4.5 if b%4==0 else 2.7
            draw.ellipse((x-r,1150-r,x+r,1150+r),fill=gold if done else (55,74,82))
        fa=lambda s:str(s).translate(str.maketrans('0123456789.','۰۱۲۳۴۵۶۷۸۹٫'))
        footer=f'{fa(f"{total:g}")} ثانیه  •  {fa(f"{bpm:g}")} ضرب در دقیقه  •  {fa(m.nu)} مفصل'
        label(draw,(width/2,1195),footer,'small',ivory)
        label(draw,(width/2,1235),'طراحی حرکت و موسیقی: پروژهٔ ناسورایا','small',muted)
        if preview:
            picture.save(output.with_suffix('.png'))
        else:
            proc.stdin.write(picture.tobytes())
            if frame in [round(4.5*fps),round(8*fps),round(12*fps),round(16*fps),round(20*fps)]:
                picture.save(output.parent/f'dance-frame-{frame:04d}.png')
    renderer.close()
    if not preview:
        proc.stdin.close()
        if proc.wait():raise RuntimeError('ffmpeg failed')
        (output.with_suffix('.render.json')).write_text(json.dumps({'width':width,'height':height,
            'fps':fps,'frames':round(total*fps),'duration_s':total,'audio':audio_meta,
            'trajectory_sampling':'previous measured 40 Hz state; no synthetic interpolation',
            'speed':1.,'motion_source':'MuJoCo mj_step rollout','still_image_animation':False,
            'face_mesh':False,'native_tadash_migration':False},indent=2)+'\n')
    print(output,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--preview',action='store_true')
    a=p.parse_args();render(a.evidence,a.output,preview=a.preview)
