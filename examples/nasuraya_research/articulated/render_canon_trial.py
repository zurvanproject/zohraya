"""Render two recorded rollouts of the same body, before/after support repair."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np
import mujoco
from PIL import Image,ImageDraw,ImageFont
from .canon_trial import CANDIDATE,EVIDENCE


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence',type=Path,default=EVIDENCE)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    results=json.loads((args.evidence/'results.json').read_text())
    rows={r['label']:r for r in results['trials']}
    labels=['v03_legacy','v03_geometry']
    records=[np.load(args.evidence/(label+'-poses.npz')) for label in labels]
    model=mujoco.MjModel.from_xml_path(str(CANDIDATE/'nasuraya.xml'))
    # Display-only floor colour; all poses are the actual saved solver output.
    model.geom_rgba[0]=[.34,.38,.42,1]
    model.vis.headlight.ambient[:]=.45
    data=mujoco.MjData(model)
    width,height=1280,800;panel=640;scene_h=656
    renderer=mujoco.Renderer(model,height=scene_h,width=panel)
    camera=mujoco.MjvCamera();camera.lookat[:]=[-.03,0,.98]
    camera.distance=3.25;camera.azimuth=125;camera.elevation=-12
    font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    try:
        large=ImageFont.truetype(font_path,27);small=ImageFont.truetype(font_path,19)
    except OSError:
        large=ImageFont.load_default(size=27);small=ImageFont.load_default(size=19)
    process=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
        '-s',f'{width}x{height}','-r','20','-i','-','-an','-c:v','libx264','-preset','fast',
        '-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)],stdin=subprocess.PIPE)
    final_time=max(float(r['time'][-1]) for r in records)
    for frame_index,time in enumerate(np.arange(0,final_time+.025,.05)):
        canvas=Image.new('RGB',(width,height),(18,24,31));draw=ImageDraw.Draw(canvas)
        for side,(label,record) in enumerate(zip(labels,records)):
            index=max(0,min(int(np.searchsorted(record['time'],time,side='right')-1),len(record['time'])-1))
            data.qpos[:]=record['qpos'][index];mujoco.mj_forward(model,data)
            renderer.update_scene(data,camera=camera)
            canvas.paste(Image.fromarray(renderer.render()),(side*panel,108))
            draw=ImageDraw.Draw(canvas)
            color=(249,169,115) if side==0 else (114,222,185)
            title='BEFORE: old foot assumptions' if side==0 else 'AFTER: geometry-aware support'
            draw.text((side*panel+20,14),title,font=large,fill=color)
            draw.text((side*panel+20,53),'Same body: 78 kg | 1.70 m | tail 0.85 m',font=small,fill=(220,225,230))
            stopped=side==0 and time>float(record['time'][-1])
            status=(f'STOPPED at {rows[label]["simulated_seconds"]:.2f} s: tilt limit; frame held'
                    if stopped else f'Recorded time: {float(record["time"][index]):.2f} s')
            draw.text((side*panel+20,80),status,font=small,fill=color)
        draw.line((640,0,640,height),fill=(85,97,110),width=2)
        draw.text((20,773),'MuJoCo physics replay | 1x speed | geometric proxy; no facial mesh or tissue simulation',font=small,fill=(195,207,220))
        process.stdin.write(canvas.tobytes())
        if frame_index==120:canvas.save(args.output.with_suffix('.png'))
    process.stdin.close()
    if process.wait()!=0:raise RuntimeError('ffmpeg render failed')
    renderer.close()
    print(args.output)


if __name__=='__main__':main()
