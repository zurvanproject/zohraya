"""Render recorded physical rollout poses; never generate synthetic motion."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
import subprocess
from pathlib import Path
import numpy as np
import mujoco
from PIL import Image, ImageDraw
from .resize import SMALL
from .build import ROOT


def main():
    folder=ROOT/'evidence/articulated-stepping-v01'
    record=np.load(folder/'six-steps-poses.npz')
    model=mujoco.MjModel.from_xml_path(str(SMALL/'nasuraya.xml'))
    data=mujoco.MjData(model)
    width,height=640,480
    renderer=mujoco.Renderer(model,height=height,width=width)
    camera=mujoco.MjvCamera();camera.lookat[:]=[.12,0,.92]
    camera.distance=3.6;camera.azimuth=120;camera.elevation=-13
    output=folder/'six-steps-2x.mp4'
    process=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}',
                              '-r','40','-i','-','-an','-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p',
                              '-movflags','+faststart',str(output)],stdin=subprocess.PIPE)
    for index,(qpos,time) in enumerate(zip(record['qpos'],record['time'])):
        data.qpos[:]=qpos;mujoco.mj_forward(model,data)
        renderer.update_scene(data,camera=camera)
        picture=Image.fromarray(renderer.render());draw=ImageDraw.Draw(picture)
        draw.rectangle((0,0,width,44),fill=(15,18,22))
        draw.text((12,8),f'PHYSICS REPLAY | 85 kg / 1.85 m | t = {time:.2f} s',fill='white')
        draw.text((12,25),'Slow walking - 2x playback - recorded MuJoCo poses',fill=(180,210,225))
        process.stdin.write(picture.tobytes())
        if index==100:picture.save(folder/'preview.png')
    process.stdin.close()
    if process.wait()!=0:raise RuntimeError('ffmpeg failed')
    renderer.close()
    print(output)

if __name__=='__main__':main()
