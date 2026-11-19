#!/usr/bin/env python3
"""Render a source-trace-only Tadash prayer/posture numerical replay.

Every video frame is an unmodified sampled state from the JSON trace.  Contact
disks have the same area as the supplied contact patches, not an invented paw
outline.  The optional leg diagram projects supplied IK joint coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, features


W, H = 1280, 720
C = {
    "bg": "#091b21", "panel": "#10262d", "edge": "#25434b",
    "grid": "#28424a", "fg": "#ecf3f1", "muted": "#91a9ad",
    "teal": "#69d3c5", "copper": "#e5a06e", "white": "#eff4ee",
    "red": "#eb8b84", "green": "#9bd5ad", "dim": "#47636b",
}
STAGE_FA = {"observe": "مشاهده", "geometry": "هندسه", "revise": "بازنگری"}
STAGE_COLOR = {"observe": "#69d3c5", "geometry": "#e5a06e", "revise": "#a2b9db"}
FA_FONT = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
FA_BOLD = "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"
EN_FONT = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
EN_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"


def font(size: int, fa=False, bold=False):
    p = FA_BOLD if fa and bold else FA_FONT if fa else EN_BOLD if bold else EN_FONT
    if not Path(p).is_file():
        p = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, size, layout_engine=ImageFont.Layout.RAQM)


FONTS = {(s, fa, bold): font(s, fa, bold) for s in range(11, 39)
         for fa in (False, True) for bold in (False, True)}


def txt(draw, xy, text, size=18, color=None, fa=False, bold=False, anchor=None):
    draw.text(xy, str(text), font=FONTS[(size, fa, bold)],
              fill=color or C["fg"], direction="rtl" if fa else "ltr",
              language="fa" if fa else "en", anchor=anchor or ("rt" if fa else "lt"))


def width(draw, text, size=18, fa=False, bold=False):
    return draw.textlength(str(text), font=FONTS[(size, fa, bold)],
                           direction="rtl" if fa else "ltr")


def fitted(draw, xy, text, max_width, size=24, min_size=15, **kw):
    while size > min_size and width(draw, text, size, kw.get("fa", False), kw.get("bold", False)) > max_width:
        size -= 1
    if width(draw, text, size, kw.get("fa", False), kw.get("bold", False)) > max_width:
        raise ValueError(f"Text does not fit its reserved width: {text!r}")
    txt(draw, xy, text, size=size, **kw)


def wrapped(draw, text, max_width, size=24, max_lines=2, min_size=16):
    """Wrap complete source text; never truncate a prayer cue."""
    for trial in range(size, min_size - 1, -1):
        lines, line = [], ""
        for word in str(text).split():
            proposal = f"{line} {word}".strip()
            if line and width(draw, proposal, trial, fa=True) > max_width:
                lines.append(line)
                line = word
            else:
                line = proposal
        if line:
            lines.append(line)
        if len(lines) <= max_lines and all(width(draw, t, trial, fa=True) <= max_width for t in lines):
            return lines, trial
    raise ValueError("Source prayer cue cannot fit without truncation; shorten the authored cue or enlarge the renderer.")


def card(draw, box, radius=14):
    draw.rounded_rectangle(box, radius=radius, fill=C["panel"], outline=C["edge"], width=1)


def rgb(c):
    return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))


def blend(a, b, t):
    aa, bb = rgb(a), rgb(b)
    return tuple(int(x + (y-x)*min(1., max(0., t))) for x, y in zip(aa, bb))


def pressure_color(value, vmax):
    return blend("#2e666c", "#f4b481", float(value) / max(vmax, 1e-12))


def dashed(draw, a, b, fill, width=1, on=6, off=5):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    if length < .01:
        return
    for start in np.arange(0, length, on+off):
        end = min(length, start+on)
        draw.line((a[0]+dx*start/length, a[1]+dy*start/length,
                   a[0]+dx*end/length, a[1]+dy*end/length), fill=fill, width=width)


def dashed_path(draw, points, fill, width=1, on=6, off=5):
    # Arclength phase carries across segments, including long near-flat traces.
    period, position = on+off, 0.
    for a, b in zip(points[:-1], points[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        used = 0.
        while used < length - 1e-8:
            phase = position % period
            active = phase < on
            remaining = (on-phase) if active else (period-phase)
            if remaining < 1e-8:
                remaining = 1e-6
            chunk = min(length-used, remaining)
            if active:
                draw.line((a[0]+dx*used/length, a[1]+dy*used/length,
                           a[0]+dx*(used+chunk)/length, a[1]+dy*(used+chunk)/length), fill=fill, width=width)
            used += chunk
            position += chunk


def nice_number(v, decimals=2):
    if abs(v) < .5*10**(-decimals):
        v = 0.
    return f"{v:.{decimals}f}"


def json_vector(value, n, where):
    a = np.asarray(value, float)
    if a.shape != (n,) or not np.all(np.isfinite(a)):
        raise ValueError(f"Expected finite {n}-vector at {where}")
    return a


class Renderer:
    def __init__(self, trace, source_bytes):
        self.trace = trace
        self.frames = trace["frames"]
        self.source_hash = hashlib.sha256(source_bytes).hexdigest()
        self.times = np.array([f["t_s"] for f in self.frames], float)
        self.dt = float(trace["dt_s"])
        if len(self.frames) < 3 or not np.isfinite(self.times).all():
            raise ValueError("At least three finite source states are required")
        if not np.allclose(np.diff(self.times), self.dt, atol=1e-8, rtol=0):
            raise ValueError("Trace must have a strictly regular source sampling interval")
        if not math.isclose(self.dt, .05, abs_tol=1e-9):
            raise ValueError("This renderer requires the agreed dt_s = 0.05 source trace")
        self.duration = float(self.times[-1] - self.times[0])
        self.prayer = trace["prayer"]
        self.stages = {str(s["id"]): s for s in self.prayer["stages"]}
        self.model = trace["model"]
        self.mass = float(self.model["mass_kg"])
        self.com = np.array([json_vector(f["com_m"], 2, "com_m") for f in self.frames])
        self.target = np.array([json_vector(f["target_offset_m"], 2, "target_offset_m") for f in self.frames])
        self.velocity = np.array([json_vector(f["velocity_m_s"], 2, "velocity_m_s") for f in self.frames])
        self.margin = np.array([f["capture_margin_m"] for f in self.frames], float)
        self.pressure = np.array([f["max_pressure_kpa"] for f in self.frames], float)
        if not all(np.isfinite(a).all() for a in [self.margin, self.pressure]):
            raise ValueError("Margin and pressure values must be finite")
        self.maxpressure = max(.001, float(self.pressure.max()))
        self.rounds = max(int(f["round"]) for f in self.frames)
        self.segment_starts = [0] + [i for i in range(1, len(self.frames))
                                    if (self.frames[i]["round"], self.frames[i]["stage"]) !=
                                    (self.frames[i-1]["round"], self.frames[i-1]["stage"])]
        self.segment_ends = self.segment_starts[1:] + [len(self.frames)-1]
        self._validate_patches()
        points, rad = [], []
        for f in self.frames:
            for p in f["patches"]:
                points.append(p["xy"])
                rad.append(math.sqrt(float(p["area_m2"])/math.pi))
        a, r = np.asarray(points), np.asarray(rad)
        self.contact_bounds = (np.min(a-r[:, None], axis=0), np.max(a+r[:, None], axis=0))
        self.contact_bounds = (np.minimum(self.contact_bounds[0], self.com.min(axis=0)),
                               np.maximum(self.contact_bounds[1], self.com.max(axis=0)))
        self.contact_bounds = (np.minimum(self.contact_bounds[0], self.target.min(axis=0)),
                               np.maximum(self.contact_bounds[1], self.target.max(axis=0)))
        self.joint_bounds = self._joint_bounds()
        self.trace_ylim = []
        for j in range(2):
            v = np.r_[self.com[:, j], self.target[:, j]] * 1000
            lo, hi = min(float(v.min()), 0), max(float(v.max()), 0)
            half = max(abs(lo), abs(hi), .0001) * 1.15
            self.trace_ylim.append((-half, half))

    def _validate_patches(self):
        for f in self.frames:
            if f["stage"] not in self.stages:
                raise ValueError(f"No source-authored cue for stage {f['stage']!r}")
            for side in ("L", "R"):
                patches = [p for p in f["patches"] if p["side"] == side]
                pads = [p for p in patches if self.is_pad(p)]
                if len(patches) != 4 or len(pads) != 1:
                    raise ValueError(f"{side} needs exactly 3 toe contacts plus 1 ball/pad contact at t={f['t_s']}")
                for p in patches:
                    json_vector(p["xy"], 2, "patch.xy")
                    if not (math.isfinite(p["area_m2"]) and p["area_m2"] > 0):
                        raise ValueError("Patch area must be positive")
                    if not all(math.isfinite(p[k]) and p[k] >= -1e-9 for k in ["normal_N", "pressure_kpa"]):
                        raise ValueError("Contact pressure/normal load must be finite and nonnegative")

    @staticmethod
    def is_pad(p):
        return any(s in str(p["id"]).lower() for s in ("ball", "pad"))

    @staticmethod
    def project(v):
        x, y, z = v
        return np.array([.8660254038*x + .5*y, .22*y-z])

    def _joint_bounds(self):
        pts = []
        for f in self.frames:
            kin = f.get("kinematics", {})
            for side in ("L", "R"):
                joints = kin.get(side, {}).get("joints_m", {})
                for name in ("hip", "knee", "ankle", "foot_anchor"):
                    if name in joints:
                        pts.append(self.project(json_vector(joints[name], 3, "joint")))
        if not pts:
            return None
        a = np.asarray(pts)
        return a.min(axis=0), a.max(axis=0)

    def header(self, d, summary=False):
        txt(d, (32, 21), "TADASH  /  NUMERICAL REPLAY", 14, C["teal"], bold=True)
        title = self.prayer.get("title_fa", "دعا و تعادل")
        fitted(d, (1248, 19), title, 790, size=31, min_size=21, fa=True, bold=True)
        model_text = f"مدل کاهش‌یافتهٔ {self.mass:g} کیلوگرمی؛ بازپخش داده‌های شبیه‌سازی"
        txt(d, (1248, 65), model_text, 16, C["muted"], fa=True)
        txt(d, (32, 52), "SOURCE TRACE  /  NO AUDIO", 12, C["muted"])
        if summary:
            txt(d, (32, 77), f"{self.duration:.2f} s  |  dt = {self.dt:.3f} s  |  {len(self.frames)} source states", 12, C["muted"])

    def cue(self, d, i):
        f = self.frames[i]
        card(d, (32, 102, 1248, 231))
        d.line((268, 118, 268, 214), fill=C["edge"], width=1)
        txt(d, (56, 119), f"{f['t_s']:05.1f}", 38, C["fg"], bold=True)
        txt(d, (168, 137), f"/ {self.times[-1]:.1f} s", 16, C["muted"])
        txt(d, (244, 174), f"دور {f['round']} از {self.rounds}", 18, C["teal"], fa=True, bold=True)
        st = self.stages[f["stage"]]
        fitted(d, (244, 204), st.get("title_fa", STAGE_FA.get(f["stage"], f["stage"])), 192,
               size=17, min_size=14, color=C["muted"], fa=True)
        txt(d, (1226, 120), "دعای تألیفی؛ نشانهٔ متنی", 16, C["copper"], fa=True)
        lines, size = wrapped(d, st["prayer_fa"], 908, size=25, max_lines=2)
        line_height = size + 11
        for j, line in enumerate(lines):
            txt(d, (1226, 154+j*line_height), line, size, fa=True)
        # Segment widths come from source state transition times.
        y = 228
        for start, end in zip(self.segment_starts, self.segment_ends):
            x1 = 32 + (self.times[start]-self.times[0])/self.duration*1216
            x2 = 32 + (self.times[end]-self.times[0])/self.duration*1216
            fill = STAGE_COLOR.get(self.frames[start]["stage"], C["muted"])
            d.line((x1, y, x2, y), fill=fill if start <= i else C["edge"], width=3)
        x = 32 + (f["t_s"]-self.times[0])/self.duration*1216
        d.ellipse((x-3, y-3, x+3, y+3), fill=C["white"])

    def contact(self, d, f, box=(32, 247, 476, 624), summary=False):
        x0, y0, x1, y1 = box
        card(d, box)
        txt(d, (x1-18, y0+18), "تماس پاها و فشار", 21, fa=True, bold=True)
        txt(d, (x1-18, y0+54), "نمای بالا؛ دایره‌ها با مساحت معادل", 14, C["muted"], fa=True)
        ly = y0+80
        d.polygon([(x0+27, ly-4), (x0+31, ly), (x0+27, ly+4), (x0+23, ly)], fill=C["teal"])
        txt(d, (x0+38, ly-6), "COM", 11, C["muted"])
        d.line((x0+95, ly, x0+105, ly), fill=C["white"], width=1)
        d.line((x0+100, ly-5, x0+100, ly+5), fill=C["white"], width=1)
        txt(d, (x0+111, ly-6), "target", 11, C["muted"])
        inner = (x0+40, y0+92, x1-30, y1-92)
        lo, hi = self.contact_bounds
        span = np.maximum(hi-lo, .1)
        scale = min((inner[2]-inner[0])/span[0], (inner[3]-inner[1])/span[1])*.86
        center = (lo+hi)/2
        def point(p):
            return (float((p[0]-center[0])*scale+(inner[0]+inner[2])/2),
                    float(-(p[1]-center[1])*scale+(inner[1]+inner[3])/2))
        # Metric coordinate guides, independent of foot anatomy.
        origin = point([0, 0])
        if inner[0] <= origin[0] <= inner[2]:
            d.line((origin[0], inner[1], origin[0], inner[3]), fill=C["grid"], width=1)
        if inner[1] <= origin[1] <= inner[3]:
            d.line((inner[0], origin[1], inner[2], origin[1]), fill=C["grid"], width=1)
        txt(d, (inner[2]-2, inner[3]-3), "+x", 12, C["muted"], anchor="rb")
        txt(d, (inner[0]+2, inner[1]), "+y", 12, C["muted"])
        for side in ("L", "R"):
            patches = [p for p in f["patches"] if p["side"] == side]
            toes = sorted([p for p in patches if not self.is_pad(p)], key=lambda p: str(p["id"]))
            labels = {str(p["id"]): str(j+1) for j, p in enumerate(toes)}
            foot_xy = np.mean([p["xy"] for p in patches], axis=0)
            fp = point(foot_xy)
            for p in patches:
                px, py = point(p["xy"])
                rr = math.sqrt(p["area_m2"]/math.pi)*scale
                fill = pressure_color(p["pressure_kpa"], self.maxpressure) if p["normal_N"] > 1e-8 else C["dim"]
                d.ellipse((px-rr, py-rr, px+rr, py+rr), fill=fill, outline=C["white"], width=1)
                label = "PAD" if self.is_pad(p) else labels[str(p["id"])]
                txt(d, (px, py), label, 11 if self.is_pad(p) else 13, C["bg"], bold=True, anchor="mm")
            txt(d, (fp[0], max(point(p["xy"])[1]+math.sqrt(p["area_m2"]/math.pi)*scale for p in patches)+10),
                side, 15, C["fg"], bold=True, anchor="mt")
        cx, cy = point(f["com_m"])
        tx, ty = point(f["target_offset_m"])
        d.line((tx-6, ty, tx+6, ty), fill=C["white"], width=2)
        d.line((tx, ty-6, tx, ty+6), fill=C["white"], width=2)
        d.polygon([(cx, cy-5), (cx+5, cy), (cx, cy+5), (cx-5, cy)], fill=C["teal"])
        bar = .1*scale
        bx, by = inner[0]+5, inner[3]+21
        d.line((bx, by, bx+bar, by), fill=C["muted"], width=2)
        d.line((bx, by-3, bx, by+3), fill=C["muted"], width=1)
        d.line((bx+bar, by-3, bx+bar, by+3), fill=C["muted"], width=1)
        txt(d, (bx, by+6), "100 mm", 11, C["muted"])
        # Common, fixed pressure scale across every frame.
        lx, ly, lw = x0+25, y1-55, 128
        for k in range(lw):
            d.line((lx+k, ly, lx+k, ly+6), fill=pressure_color(k/lw*self.maxpressure, self.maxpressure))
        txt(d, (lx, ly+13), "0", 11, C["muted"])
        txt(d, (lx+lw, ly+13), f"{self.maxpressure:.1f} kPa", 11, C["muted"], anchor="rt")
        txt(d, (x1-18, y1-57), "۳ پنجه و ۱ بالشتک در هر پا", 13, C["fg"], fa=True)
        txt(d, (x1-18, y1-30), "بالشتک، پنجهٔ چهارم نیست", 12, C["muted"], fa=True)

    def legs(self, d, f):
        box = (492, 247, 748, 624)
        card(d, box)
        txt(d, (730, 265), "هندسهٔ پا", 21, fa=True, bold=True)
        txt(d, (730, 301), "مختصات مفصل‌های مدل", 14, C["muted"], fa=True)
        txt(d, (510, 266), "IK", 14, C["teal"], bold=True)
        if self.joint_bounds is None:
            txt(d, (730, 406), "دادهٔ مفصل موجود نیست", 15, C["muted"], fa=True)
            return
        lo, hi = self.joint_bounds
        span = np.maximum(hi-lo, .05)
        scale = min(190/span[0], 232/span[1])*.9
        center = (lo+hi)/2
        def point(v):
            a = self.project(v)
            return tuple((a-center)*scale+np.array([620, 447]))
        for side in ("R", "L"):
            col = C["teal"] if side == "L" else C["copper"]
            joints = f.get("kinematics", {}).get(side, {}).get("joints_m", {})
            names = [n for n in ("hip", "knee", "ankle", "foot_anchor") if n in joints]
            pts = [point(joints[n]) for n in names]
            if len(pts) > 1:
                d.line(pts, fill=col, width=4, joint="curve")
            for p in pts:
                d.ellipse((p[0]-4, p[1]-4, p[0]+4, p[1]+4), fill=C["panel"], outline=col, width=2)
            if pts:
                label_left = pts[0][0] < 620
                txt(d, (pts[0][0] + (-11 if label_left else 11), pts[0][1]-16), side, 13, col,
                    bold=True, anchor="rm" if label_left else "lm")
        txt(d, (730, 570), "فرافکنی مایل با مقیاس ثابت", 13, C["muted"], fa=True)
        txt(d, (730, 596), "فقط اندام‌های مدل‌شده", 12, C["muted"], fa=True)

    def graph(self, d, box, series, targets=None, i=None, color=None, ylabel="", ylim=None,
              show_xticks=True, stage_bands=False, label_size=11):
        x0, y0, x1, y1 = box
        v = np.asarray(series)
        if ylim is None:
            both = v if targets is None else np.r_[v, targets]
            lo, hi = float(both.min()), float(both.max())
            span = max(hi-lo, max(abs(lo), abs(hi))*.08, .001)
            ylim = (lo-span*.12, hi+span*.12)
        lo, hi = ylim
        def x(t):
            return x0+(t-self.times[0])/self.duration*(x1-x0)
        def y(value):
            return y1-(value-lo)/(hi-lo)*(y1-y0)
        if stage_bands:
            for start, end in zip(self.segment_starts, self.segment_ends):
                st = self.frames[start]["stage"]
                tint = blend(C["panel"], STAGE_COLOR.get(st, C["muted"]), .08)
                d.rectangle((x(self.times[start]), y0, x(self.times[end]), y1), fill=tint)
        ticks = [lo, (lo+hi)/2, hi]
        for val in ticks:
            yy = y(val)
            d.line((x0, yy, x1, yy), fill=C["grid"], width=1)
            decimals = 3 if abs(hi-lo) < .05 else 2 if abs(hi-lo) < 2 else 1
            txt(d, (x0-8, yy), nice_number(val, decimals), label_size, C["muted"], anchor="rm")
        for t in np.linspace(self.times[0], self.times[-1], 5):
            xx = x(t)
            d.line((xx, y0, xx, y1), fill=C["grid"], width=1)
            if show_xticks:
                txt(d, (xx, y1+8), f"{t:g}", label_size, C["muted"], anchor="mt")
        n = len(self.frames) if i is None else i+1
        pts = [(x(t), y(val)) for t, val in zip(self.times[:n], v[:n])]
        if targets is not None:
            targetpts = [(x(t), y(val)) for t, val in zip(self.times[:n], targets[:n])]
            dashed_path(d, targetpts, C["muted"], width=2)
        if len(pts) > 1:
            d.line(pts, fill=color or C["teal"], width=2)
        if i is not None:
            xx, yy = pts[-1]
            d.line((xx, y0, xx, y1), fill=C["dim"], width=1)
            d.ellipse((xx-3, yy-3, xx+3, yy+3), fill=color or C["teal"])
        txt(d, (x0, y0-20), ylabel, 12, C["fg"], bold=True)

    def trace_panel(self, d, i):
        card(d, (764, 247, 1248, 624))
        txt(d, (1230, 265), "مرکز جرم و هدف", 21, fa=True, bold=True)
        txt(d, (1230, 301), "بزرگ‌نماییِ محورها؛ واحد میلی‌متر", 14, C["muted"], fa=True)
        for j in range(2):
            y0 = 356+j*122
            self.graph(d, (817, y0, 1229, y0+76), self.com[:, j]*1000, self.target[:, j]*1000,
                       i=i, color=C["teal"] if j == 0 else C["copper"],
                       ylabel=f"{'x' if j == 0 else 'y'}  /  mm", ylim=self.trace_ylim[j], show_xticks=j == 1)
        d.line((790, 596, 815, 596), fill=C["teal"], width=2)
        txt(d, (823, 590), "COM", 12, C["muted"])
        dashed(d, (885, 596), (913, 596), C["muted"], width=2)
        txt(d, (923, 590), "target", 12, C["muted"])
        txt(d, (1228, 591), "time / s", 12, C["muted"], anchor="rt")

    def metrics(self, d, f, y0=640):
        speed = float(np.linalg.norm(f["velocity_m_s"]))*1000
        items = [
            ("حاشیهٔ تعادل مدل", f"{f['capture_margin_m']*1000:.1f}", "mm", C["teal"]),
            ("بیشینهٔ فشار تماس", f"{f['max_pressure_kpa']:.2f}", "kPa", C["copper"]),
            ("سرعت مرکز جرم", f"{speed:.3f}", "mm/s", C["fg"]),
            ("کنترل قیود این گام", "PASS" if f["passed"] else "FAIL", "", C["green"] if f["passed"] else C["red"]),
        ]
        for j, (label, value, unit, color) in enumerate(items):
            x0 = 32+j*308
            card(d, (x0, y0, x0+292, y0+64), radius=11)
            txt(d, (x0+275, y0+11), label, 13, C["muted"], fa=True)
            txt(d, (x0+18, y0+30), value, 23, color, bold=True)
            vwidth = width(d, value, 23, bold=True)
            txt(d, (x0+27+vwidth, y0+39), unit, 12, C["muted"])

    def frame(self, i):
        img = Image.new("RGB", (W, H), C["bg"])
        d = ImageDraw.Draw(img)
        self.header(d)
        self.cue(d, i)
        f = self.frames[i]
        self.contact(d, f)
        self.legs(d, f)
        self.trace_panel(d, i)
        self.metrics(d, f)
        return img

    def summary(self):
        img = Image.new("RGB", (1280, 1170), C["bg"])
        d = ImageDraw.Draw(img)
        self.header(d, summary=True)
        card(d, (32, 112, 1248, 201))
        items = [
            ("کمترین حاشیهٔ تعادل مدل", f"{self.margin.min()*1000:.2f} mm", C["teal"]),
            ("بیشترین فشار تماس", f"{self.pressure.max():.3f} kPa", C["copper"]),
            ("بیشترین سرعت مرکز جرم", f"{np.linalg.norm(self.velocity, axis=1).max()*1000:.3f} mm/s", C["fg"]),
            ("گام‌های مردود", f"{sum(not f['passed'] for f in self.frames)} / {len(self.frames)}", C["green"]),
        ]
        for j, (label, value, color) in enumerate(items):
            x = 50+j*304
            if j:
                d.line((x-18, 128, x-18, 184), fill=C["edge"], width=1)
            txt(d, (x+265, 128), label, 14, C["muted"], fa=True)
            txt(d, (x, 162), value, 22, color, bold=True)
        card(d, (32, 218, 827, 983))
        txt(d, (805, 237), "مسیر کاملِ محاسبه", 22, fa=True, bold=True)
        txt(d, (805, 276), "خط پیوسته: مدل؛ خط‌چین: هدف؛ نوارها: مراحل دعا", 14, C["muted"], fa=True)
        series = [self.com[:, 0]*1000, self.com[:, 1]*1000, self.margin*1000, self.pressure]
        labels = ["COM x / mm", "COM y / mm", "Capture margin / mm", "Maximum pressure / kPa"]
        for j in range(4):
            y0 = 336+j*153
            target = self.target[:, j]*1000 if j < 2 else None
            ylim = self.trace_ylim[j] if j < 2 else None
            self.graph(d, (108, y0, 803, y0+98), series[j], target,
                       color=C["teal"] if j in (0, 2) else C["copper"], ylabel=labels[j],
                       ylim=ylim, show_xticks=True, stage_bands=True, label_size=12)
        txt(d, (803, 960), "زمان شبیه‌سازی، ثانیه", 13, C["muted"], fa=True)
        self.contact(d, self.frames[-1], box=(845, 218, 1248, 658), summary=True)
        card(d, (845, 675, 1248, 1115))
        txt(d, (1228, 697), "دعای تألیفی؛ نشانهٔ متنی", 18, C["copper"], fa=True, bold=True)
        y = 739
        for st in self.prayer["stages"]:
            title = st.get("title_fa", STAGE_FA.get(st["id"], st["id"]))
            txt(d, (1228, y), title, 15, STAGE_COLOR.get(st["id"], C["teal"]), fa=True, bold=True)
            lines, size = wrapped(d, st["prayer_fa"], 363, size=15, min_size=12, max_lines=3)
            for k, line in enumerate(lines):
                txt(d, (1228, y+27+k*(size+8)), line, size, C["fg"], fa=True)
            y += max(75, 30+len(lines)*(size+8))
        if y > 1110:
            raise ValueError("Prayer source text exceeds the summary card; adjust layout")
        card(d, (32, 999, 827, 1115))
        txt(d, (805, 1018), "بازپخش با زمان واقعیِ داده‌ها", 18, C["teal"], fa=True, bold=True)
        txt(d, (805, 1053), "هر دو نمونهٔ محاسباتی، یک فریم؛ بدون درون‌یابی و تکرار", 15, C["fg"], fa=True)
        txt(d, (805, 1084), "حرکت مفصل‌ها و فشارها از ردّ عددی مدل خوانده شده‌اند", 14, C["muted"], fa=True)
        txt(d, (32, 1131), "10 fps; terminal state retained in this summary. Source JSON SHA-256:", 12, C["muted"])
        txt(d, (32, 1151), self.source_hash, 11, C["muted"])
        return img

    def write(self, out, fps=10, preview_only=False):
        out.mkdir(parents=True, exist_ok=True)
        if fps != 10:
            raise ValueError("Output fps must be 10 for the agreed every-second-frame replay")
        n_video = round(self.duration*fps)
        if not math.isclose(n_video/fps, self.duration, abs_tol=1e-8):
            raise ValueError("Trace must end at an exact 0.1 s boundary; endpoint is a terminal state")
        indices = np.arange(n_video, dtype=int)*2
        if indices[-1] >= len(self.frames):
            raise ValueError("Video would sample beyond the source trace")
        expected = self.times[0]+np.arange(n_video)/fps
        if not np.allclose(self.times[indices], expected, atol=1e-8, rtol=0):
            raise ValueError("Source and video sample times disagree")
        # The preview samples a real geometry stage if available.
        candidates = [i for i, f in enumerate(self.frames) if f["stage"] == "geometry"]
        preview_i = candidates[len(candidates)//2] if candidates else len(self.frames)//2
        preview_i = (preview_i//2)*2  # Exactly a state that also appears in the 10 fps replay.
        self.frame(preview_i).save(out/"prayer_sim_replay_frame.png")
        self.summary().save(out/"prayer_sim_summary.png")
        video = out/"prayer_sim_replay.mp4"
        if not preview_only:
            if not shutil.which("ffmpeg"):
                raise RuntimeError("ffmpeg is required")
            log_path = out/"ffmpeg_render.log"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                       "-pixel_format", "rgb24", "-video_size", f"{W}x{H}", "-framerate", str(fps),
                       "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)]
            with log_path.open("wb") as log:
                proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
                try:
                    for n, i in enumerate(indices):
                        proc.stdin.write(self.frame(int(i)).tobytes())
                        if n % 100 == 0:
                            print(f"Rendered {n}/{n_video} frames; source t={self.times[i]:.2f}s", flush=True)
                    proc.stdin.close()
                    code = proc.wait()
                    if code:
                        raise RuntimeError(f"ffmpeg failed ({code}): {log_path.read_text()}")
                except BaseException:
                    proc.kill()
                    proc.wait()
                    raise
        report = {
            "source_sha256": self.source_hash,
            "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_schema": self.trace.get("schema"),
            "source_dt_s": self.dt,
            "source_states": len(self.frames),
            "source_start_s": float(self.times[0]),
            "source_terminal_s": float(self.times[-1]),
            "video_fps": fps,
            "video_frames": int(n_video),
            "video_duration_s": n_video/fps,
            "video_sampling": "Every second source state at t_start + n/10; terminal state is not held for an extra frame.",
            "interpolation": False,
            "loops": False,
            "audio_track": False,
            "preview_source_index": preview_i,
            "preview_source_time_s": float(self.times[preview_i]),
            "resolution": [W, H],
            "contact_rendering": "Exactly three toe disks and one ball/pad disk per foot; disks preserve supplied area.",
            "kinematics_rendering": "Fixed oblique linear projection of supplied hip/knee/ankle/foot_anchor coordinates, equal scale.",
            "persian_shaping": {"libraqm": features.check("raqm"), "font": FA_FONT},
            "min_capture_margin_mm": float(self.margin.min()*1000),
            "max_pressure_kpa": float(self.pressure.max()),
            "max_com_speed_mm_s": float(np.linalg.norm(self.velocity, axis=1).max()*1000),
            "failed_source_states": sum(not f["passed"] for f in self.frames),
            "rendered_video": not preview_only,
        }
        if not preview_only and shutil.which("ffprobe"):
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,pix_fmt,width,height,avg_frame_rate,nb_frames:format=duration", "-of", "json", str(video)],
                                    check=True, capture_output=True, text=True)
            report["ffprobe"] = json.loads(result.stdout)
            actual_duration = float(report["ffprobe"]["format"]["duration"])
            if not math.isclose(actual_duration, self.duration, abs_tol=.001):
                raise RuntimeError("Encoded duration does not match simulation duration")
            streams = report["ffprobe"]["streams"]
            if len(streams) != 1:
                raise RuntimeError("Replay must have exactly one video stream and no audio")
            stream = streams[0]
            expected_stream = {"codec_name": "h264", "pix_fmt": "yuv420p", "width": W, "height": H,
                               "avg_frame_rate": "10/1", "nb_frames": str(n_video)}
            if any(stream.get(k) != v for k, v in expected_stream.items()):
                raise RuntimeError(f"Encoded stream properties do not match the replay contract: {stream}")
        (out/"render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--preview-only", action="store_true", help="Make real-data stills and a report, without encoding MP4")
    args = p.parse_args()
    if not features.check("raqm"):
        raise RuntimeError("libraqm is required for correctly shaped Persian text")
    raw = args.trace.read_bytes()
    Renderer(json.loads(raw), raw).write(args.output, preview_only=args.preview_only)


if __name__ == "__main__":
    main()
