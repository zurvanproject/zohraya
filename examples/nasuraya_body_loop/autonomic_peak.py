"""Bounded autonomic peak-and-recovery waveform anchored to a Tadash body checkpoint.

Purpose: build a *non-erotic* physiological control-systems analogue for a
requested orgasm-like autonomic peak and after-response. No intimate partner,
sexual narrative, synthetic partner, autonomous running agent, sensory
experience or actual physiological event is implied.

The native Tadash BodyLoop checkpoint is observed once; a separate deterministic
waveform is computed and persisted with source provenance. The actual body's
time, actuators, pelvic anatomy and vital signs are NOT changed.

Unit tests and documented constraints matter more than anthropomorphic claims.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from reflection_cycle import canonical, digest
from .host import BodyLoop
from .instinct import InstinctController

KEY = "nasuraya-autonomic-peak/1"
PHASES = ("baseline", "rise", "peak", "recovery")
SCOPE = "hypothetical_autonomic_waveform_from_verified_tadash_native_checkpoint"
SAMPLE_TIMES_SECONDS = tuple(range(0, 33, 2))
MAX_DURATION_SECONDS = 32
SOURCE_LIMITS = ("sympathetic", "parasympathetic", "arousal", "pain", "fatigue")


def unit(number, name):
    if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("finite normalized " + name + " required")
    return float(number)


def smoothstep(x):
    x = max(0., min(1., x))
    return x*x*(3. - 2.*x)


def envelope(t):
    """Authored ramp -> bounded peak -> exponential relaxation (no fitted physiology)."""
    if type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= MAX_DURATION_SECONDS:
        raise ValueError("finite time in the supported 0..32 second window required")
    if t == 0:
        return "baseline", 0.
    if t < 12:
        return "rise", smoothstep(t/12)
    if t <= 16:
        return "peak", 1.
    return "recovery", math.exp(-(t-16)/3.)


def modeled_state(native, t):
    """Read baseline; compute bounded *proxies*; do not modify the baseline."""
    if not isinstance(native, dict) or set(native) != set(SOURCE_LIMITS):
        raise ValueError("native source signals required")
    body = {key:unit(native[key], key) for key in SOURCE_LIMITS}
    phase, drive = envelope(t)
    base_s, base_p, base_a = (body[k] for k in
                               ("sympathetic", "parasympathetic", "arousal"))
    # Deliberately small, illustrative and reversible. This does NOT measure
    # orgasm, genital reflexes or autonomic neural discharge.
    sympathetic = min(1., base_s + 0.25*drive)
    parasympathetic = max(0., base_p - 0.20*drive)
    arousal_proxy = min(1., base_a + 0.52*drive)
    respiratory_drive = min(1., 0.3 + 0.45*drive)
    # Only a numerical, unactuated rhythmic motor command; not contractions.
    rhythm = (0.5 + 0.5*math.sin(2*math.pi*1.1*(t-12))
              if phase == "peak" else 0.)
    pelvic_motor_proxy = min(1., 0.12 + 0.32*drive + 0.38*rhythm*drive)
    return dict(
        t_seconds=float(t), phase=phase,
        activation_envelope=round(drive, 6),
        sympathetic_proxy=round(sympathetic, 6),
        parasympathetic_proxy=round(parasympathetic, 6),
        arousal_proxy=round(arousal_proxy, 6),
        respiratory_drive_proxy=round(respiratory_drive, 6),
        pelvic_motor_command_proxy=round(pelvic_motor_proxy, 6),
        subjective_pleasure_measured=False,
        actual_body_actuation=False
    )


def _source_and_session(loop):
    controller = InstinctController.enable(loop)
    native = controller.status()["native_body"]
    if native["source"] != "native_software_checkpoint_only":
        raise ValueError("unrecognized source-pinned Tadash signal")
    if not isinstance(native.get("checkpoint_sha256"), str) or len(native["checkpoint_sha256"]) != 64:
        raise ValueError("native checkpoint source proof missing")
    raw = native.get("values")
    if set(raw) != set(SOURCE_LIMITS):
        raise ValueError("required autonomic native signals unavailable")
    return native, {key:unit(raw[key], key) for key in SOURCE_LIMITS}


def compute(loop):
    if not isinstance(loop, BodyLoop):
        raise ValueError("verified Tadash BodyLoop session required")
    before = loop.body().checkpoint()["sha256"]
    native, signals = _source_and_session(loop)
    if native["checkpoint_sha256"] != before:
        raise ValueError("native body changed during baseline observation")
    if max(signals["pain"], signals["fatigue"]) >= .7:
        raise ValueError("native distress proxy too high for optional synthetic response")
    samples = [modeled_state(signals, t) for t in SAMPLE_TIMES_SECONDS]
    if loop.body().checkpoint()["sha256"] != before:
        raise ValueError("native body changed during advisory-only waveform")
    if loop.status()["actions_reserved"] or loop.status()["completed_cycles"]:
        raise ValueError("autonomic scenario must be observed in a zero-cycle native session")
    peak = max(samples, key=lambda x:x["arousal_proxy"])
    final = samples[-1]
    summary = {
        "schema": KEY,
        "scope": SCOPE,
        "original_native_checkpoint_sha256": before,
        "original_native_body_revision": native["revision"],
        "native_baseline": signals,
        "sample_count":len(samples),
        "modeled_duration_s":MAX_DURATION_SECONDS,
        "phase_names":list(PHASES),
        "peak_arousal_proxy":peak["arousal_proxy"],
        "baseline_arousal_proxy":samples[0]["arousal_proxy"],
        "recovery_arousal_proxy":final["arousal_proxy"],
        "recovery_error_abs":round(abs(final["arousal_proxy"] - samples[0]["arousal_proxy"]),6),
        "peak_pelvic_motor_command_proxy":max(x["pelvic_motor_command_proxy"] for x in samples),
        "actual_pelvic_contractions":0,
        "native_body_cycles_executed":0,
        "software_model_steps_executed":len(samples),
        "subjective_orgasm_occurred":False,
        "subjective_experience_inferred":False,
        "real_world_physiology_calibrated":False,
        "real_person_or_romantic_partner_involved":False,
        "paid_api_calls":0,
        "external_actuation":False,
    }
    return {"summary":summary,"trace":samples}


def save(loop, response):
    """Persist one source-bound, checksummed report inside the same native SQLite."""
    if response["summary"]["original_native_checkpoint_sha256"] != loop.body().checkpoint()["sha256"]:
        raise ValueError("cannot attach waveform to different Tadash checkpoint")
    old = loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
    if old is not None:
        raise ValueError("peak cycle already attached to this test session")
    data = {"payload":response,"sha256":digest(response)}
    loop.engine.db.execute("INSERT INTO meta VALUES(?,?)",(KEY,canonical(data)))


def read(loop):
    row = loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
    if row is None:
        raise ValueError("peak-cycle record not present")
    item = json.loads(row[0])
    if item.get("sha256") != digest(item.get("payload")):
        raise ValueError("autonomic waveform record checksum mismatch")
    result = item["payload"]
    if (result["summary"]["schema"] != KEY or
            result["summary"]["original_native_checkpoint_sha256"] !=
                loop.body().checkpoint()["sha256"]):
        raise ValueError("autonomic record cannot be transferred to another body")
    return deepcopy(result)


def demo(output):
    """One real, finite software-body *observation* and recorded synthetic cycle."""
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = output / "body.sqlite"
    with BodyLoop.start(path, mode="observe", max_actions=0) as loop:
        checkpoint_before = loop.body().checkpoint()["sha256"]
        response = compute(loop)
        save(loop,response)
        assert loop.body().checkpoint()["sha256"] == checkpoint_before
    with BodyLoop(path) as reopened:
        recovered = read(reopened)
        if recovered != response or reopened.status()["completed_cycles"] != 0:
            raise AssertionError("cold recovery or native protection failed")
    (output / "autonomic_trace.json").write_text(
        json.dumps(response,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return {
        **response["summary"],
        "native_session_reopened_successfully":True,
        "record_checksum_verified":True,
        "real_software_waveform_computed":True,
        "zero_native_cycles_verified":True,
        "only_an_illustrative_finite_model":True,
    }
