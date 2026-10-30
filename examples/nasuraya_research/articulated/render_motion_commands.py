"""Real-time portrait replay of recorded, continuous movement commands.

No physics is executed here. Every displayed pose is a saved MuJoCo state,
sampled with zero-order hold at 20 fps. Model colours and cameras are cosmetic.
"""
import os
os.environ.setdefault("MUJOCO_GL", "egl")

import argparse
import json
import math
from pathlib import Path
import subprocess

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .canon_trial import CANDIDATE

PHASES = {
    "initial": "آمادهٔ حرکت",
    "transfer": "انتقال وزن",
    "swing": "برداشتن پا",
    "landing": "فرود پا",
    "recenter": "بازگشت تعادل",
    "settle": "توقف متعادل",
}
NUMERALS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")


def load_records(folder):
    folder = Path(folder)
    state = json.loads((folder / "session.json").read_text())
    if state.get("schema") != "nasuraya-motion-session/1":
        raise ValueError("Unknown motion session schema")
    records = []
    for item in state["commands"]:
        if item["status"] != "completed":
            raise ValueError("The presentation requires completed commands")
        receipt = json.loads((folder / item["receipt"]).read_text())
        result = receipt["result"]
        if not result["walk_pass"] or result.get("checkpoint") is None:
            raise ValueError("Command did not finish at a settled boundary")
        with np.load(folder / item["poses"], allow_pickle=False) as capture:
            times = capture["time"].copy()
            poses = capture["qpos"].copy()
        if (times.ndim != 1 or poses.ndim != 2 or len(times) != len(poses)
                or len(times) < 2 or not np.isfinite(times).all()
                or not np.isfinite(poses).all() or np.any(np.diff(times) < 0)):
            raise ValueError("Invalid recorded time/pose arrays")
        if (abs(times[0] - result["start_time"]) > 1e-9
                or abs(times[-1] - result["end_time"]) > 1e-9
                or not np.array_equal(poses[0], result["initial_qpos"])
                or not np.array_equal(poses[-1], result["final_qpos"])):
            raise ValueError("Capture and command receipt disagree")
        if records:
            previous = records[-1]["result"]
            if (abs(previous["end_time"] - result["start_time"]) > 1e-9
                    or not np.array_equal(previous["final_qpos"], result["initial_qpos"])
                    or not np.array_equal(previous["final_qvel"], result["initial_qvel"])):
                raise ValueError("Commands do not share the same physical boundary")
        trace = result["trace"]
        if not trace:
            raise ValueError("A command has no measured trace")
        records.append(dict(item=item, result=result, time=times, qpos=poses,
                            trace_time=np.asarray([r["t"] for r in trace])))
    if not records:
        raise ValueError("There are no completed commands to replay")
    return records


def render(session, output, preview=False):
    records = load_records(session)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    first = float(records[0]["time"][0])
    last = float(records[-1]["time"][-1])
    total = last - first
    if not 0 < total < 600:
        raise ValueError("Unsupported replay duration")
    fps = 20
    frames = max(1, math.ceil(total * fps - 1e-7))
    starts = np.asarray([r["result"]["start_time"] for r in records])
    m = mujoco.MjModel.from_xml_path(str(CANDIDATE / "nasuraya.xml"))
    d = mujoco.MjData(m)
    if any(r["qpos"].shape[1] != m.nq for r in records):
        raise ValueError("Capture dimensions do not match v03")
    # Appearance changes apply only to the replay model.
    m.geom_rgba[0] = [.033, .051, .061, 1]
    m.vis.headlight.ambient[:] = .47
    m.vis.headlight.diffuse[:] = .73
    m.vis.quality.shadowsize = 2048
    for geom in range(1, m.ngeom):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, geom) or ""
        m.geom_rgba[geom] = [.65, .30, .13, 1]
        if name.startswith(("horn", "ball_", "toe_pad_")):
            m.geom_rgba[geom] = [.32, .20, .13, 1]
        if name in ("torso_mass", "pelvis_mass"):
            m.geom_rgba[geom] = [.39, .20, .12, 1]
    width, height, scene_height = 720, 1080, 630
    main_renderer = mujoco.Renderer(m, height=scene_height, width=width)
    foot_renderer = mujoco.Renderer(m, height=190, width=290)
    camera = mujoco.MjvCamera()
    initial = records[0]["qpos"][0]
    final = records[-1]["qpos"][-1]
    centre_x = float((initial[0] + final[0]) / 2)
    camera.lookat[:] = [centre_x, 0, .99]
    camera.distance = 3.35
    camera.azimuth = 40
    camera.elevation = -12
    closeup = mujoco.MjvCamera()
    closeup.lookat[:] = [centre_x + .045, 0, .19]
    closeup.distance = .90
    closeup.azimuth = 72
    closeup.elevation = -17
    regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    fonts = {key: ImageFont.truetype(path, size) for key, path, size in (
        ("title", bold, 36), ("command", bold, 28),
        ("body", regular, 23), ("small", regular, 18), ("tiny", regular, 15))}
    ivory, gold, muted = (240, 230, 209), (222, 172, 104), (161, 182, 187)
    bg = (8, 17, 23)

    def text(draw, xy, value, style="body", fill=ivory):
        draw.text(xy, value, font=fonts[style], fill=fill, anchor="mm",
                  direction="rtl", language="fa")

    def frame_at(frame):
        relative_time = min(frame / fps, total)
        absolute_time = first + relative_time
        command_index = max(0, min(int(np.searchsorted(starts, absolute_time, side="right") - 1), len(records) - 1))
        record = records[command_index]
        ix = max(0, min(int(np.searchsorted(record["time"], absolute_time, side="right") - 1), len(record["time"]) - 1))
        d.qpos[:] = record["qpos"][ix]
        mujoco.mj_forward(m, d)
        local_time = absolute_time - record["result"]["start_time"]
        trace_ix = max(0, min(int(np.searchsorted(record["trace_time"], local_time, side="right") - 1), len(record["trace_time"]) - 1))
        trace = record["result"]["trace"][trace_ix]
        phase = PHASES.get(trace["phase"], trace["phase"])
        main_renderer.update_scene(d, camera=camera)
        foot_renderer.update_scene(d, camera=closeup)
        picture = Image.new("RGB", (width, height), bg)
        picture.paste(Image.fromarray(main_renderer.render()), (0, 139))
        picture.paste(Image.fromarray(foot_renderer.render()), (28, 801))
        draw = ImageDraw.Draw(picture)
        text(draw, (360, 42), "ناسورایا | فرمان و حرکت", "title")
        text(draw, (360, 87), "۷۸ کیلوگرم  •  قد ۱۷۰ سانتی‌متر", "small", gold)
        text(draw, (360, 117), "حرکت ثبت‌شدهٔ مدل مفصلی  •  سرعت واقعی", "small", muted)
        # Side inset remains a second view of the exact same recorded pose.
        draw.rounded_rectangle((26, 799, 320, 993), radius=6, outline=(79, 102, 108), width=2)
        text(draw, (173, 782), "نمای نزدیک پاها", "small", muted)
        command_name = "فرمان اول" if command_index == 0 else "فرمان دوم" if command_index == 1 else f"فرمان {str(command_index + 1).translate(NUMERALS)}"
        text(draw, (515, 804), command_name, "command", gold)
        steps = record["item"]["steps"]
        verb = "یک قدم جلو برو" if steps == 1 else "دو قدم جلو برو"
        text(draw, (515, 847), verb)
        text(draw, (515, 880), "و بایست")
        text(draw, (515, 930), phase, "body", gold)
        sub = "ادامه از وضعیت قبلی" if command_index else "آغاز حرکت"
        text(draw, (515, 970), sub, "small", muted)
        stamp = f"{relative_time:.1f} / {total:.1f}".translate(NUMERALS)
        text(draw, (360, 1015), stamp + " ثانیه", "small", ivory)
        x0, x1, y = 38, 682, 1043
        draw.line((x0, y, x1, y), fill=(51, 72, 80), width=4)
        draw.line((x0, y, x0 + (x1 - x0) * relative_time / total, y), fill=gold, width=4)
        for boundary in starts[1:]:
            x = x0 + (x1 - x0) * (boundary - first) / total
            draw.line((x, y - 6, x, y + 6), fill=ivory, width=2)
        text(draw, (360, 1064), "مدل فنی بدن؛ بازپخش دادهٔ شبیه‌ساز", "tiny", muted)
        return picture

    # Prefer actual swing midpoints and settled states for visual QA.
    samples = []
    for record in records:
        swing = [r for r in record["result"]["trace"] if r["phase"] == "swing"]
        if swing:
            samples.append(record["result"]["start_time"] + swing[len(swing) // 2]["t"] - first)
        samples.append(record["result"]["end_time"] - first - .1)
    selected = sorted(set(max(0, min(frames - 1, round(t * fps))) for t in samples))[:4]
    if preview:
        selected = selected or [0]
        sequence = selected
        process = None
    else:
        process = subprocess.Popen([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
            "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ], stdin=subprocess.PIPE)
        sequence = range(frames)
    previews = []
    try:
        for frame in sequence:
            picture = frame_at(frame)
            if frame in selected:
                picture.save(output.with_name(output.stem + f"-frame-{frame:04d}.jpg"), quality=92)
                previews.append(picture.resize((360, 540)))
            if process:
                process.stdin.write(picture.tobytes())
    finally:
        main_renderer.close()
        foot_renderer.close()
        if process:
            process.stdin.close()
            returncode = process.wait()
            if returncode:
                raise RuntimeError(f"ffmpeg failed with code {returncode}")
    if previews:
        sheet = Image.new("RGB", (720, 540 * math.ceil(len(previews) / 2)), bg)
        for index, picture in enumerate(previews):
            sheet.paste(picture, ((index % 2) * 360, (index // 2) * 540))
        sheet.save(output.with_suffix(".contact-sheet.jpg"), quality=94)
    if not preview:
        metadata = dict(width=width, height=height, fps=fps, frames=frames,
                        video_duration_s=frames / fps, simulation_span_s=total,
                        simulation_start_s=first, simulation_end_s=last,
                        initialization_included=False, speed=1.0, audio=False,
                        motion_source="saved MuJoCo integration results",
                        pose_sampling="previous recorded state; zero-order hold; no interpolation",
                        continuous_command_boundaries=True,
                        generated_motion=False, facial_mesh=False,
                        command_ids=[r["item"]["id"] for r in records])
        output.with_suffix(".render.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(output.with_suffix(".contact-sheet.jpg") if preview else output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    render(args.session, args.output, args.preview)
