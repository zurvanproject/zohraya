"""Offline, deterministic *symbolic* Persian setar motor/audio practice.

Simulates three short passes in a D Shur-inspired phrase. This models
finger gestures, timing corrections, microtonal targets and approximate
plucked-string audio; it does not represent live playing or measured skill.
No external Python packages, API, or network required.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 22050
# Conventional Do-Sol example, ordered from first/brightest to fourth/bass.
OPEN_HZ = (261.625565, 195.997718, 261.625565, 130.812783)
# Name, semitone offset from open first string (fractional for E koron), beats.
PHRASE = (
    ("D4", 2.0, 1.0), ("E4-koron", 3.5, 1.0),
    ("F4", 5.0, 1.0), ("G4", 7.0, 1.5),
    ("F4", 5.0, .5), ("E4-koron", 3.5, 1.0), ("D4", 2.0, 2.0),
    ("F4", 5.0, 1.0), ("G4", 7.0, 1.0),
    ("A4", 9.0, 1.0), ("G4", 7.0, 1.0),
    ("F4", 5.0, 1.0), ("E4-koron", 3.5, 1.0), ("D4", 2.0, 2.0),
)
BEAT_SECONDS = 0.36


def target_frequency(semitones: float, string: int = 1) -> float:
    """Virtual adjustable frets; do not assume chromatic fixed fret slots."""
    if string not in (1, 2, 3, 4):
        raise ValueError('string out of range')
    return OPEN_HZ[string - 1] * 2 ** (semitones / 12)


def plan_events() -> list[dict]:
    events = []
    beat = 0.0
    for idx, (label, semitones, length) in enumerate(PHRASE):
        events.append({
            'note': label,
            'string': 1,
            'left_virtual_fret_semitones': semitones,
            'right_index_stroke': 'rast' if idx % 2 == 0 else 'chap',
            'target_onset_s': round(beat * BEAT_SECONDS, 5),
            'target_duration_s': round(length * BEAT_SECONDS, 5),
            'target_hz': round(target_frequency(semitones), 4),
            'target_attack': 0.72,
        })
        beat += length
    return events


def one_pass(plan: list[dict], rng: random.Random, params: dict) -> tuple[list[dict], dict]:
    performed = []
    for item in plan:
        timing_error = params['timing_bias_s'] + rng.gauss(0, .009)
        tuning_error = params['pitch_bias_cents'] + rng.gauss(0, 2.5)
        attack_error = params['attack_bias'] + rng.gauss(0, .024)
        performed.append({
            **item,
            'sim_onset_s': round(item['target_onset_s'] + timing_error, 5),
            'sim_hz': round(item['target_hz'] * 2 ** (tuning_error / 1200), 4),
            'sim_attack': round(max(.1, min(1., item['target_attack'] + attack_error)), 4),
            'timing_error_ms': round(timing_error * 1000, 3),
            'intonation_error_cents': round(tuning_error, 3),
            'attack_error': round(attack_error, 4),
        })
    def avg(field: str) -> float:
        return sum(x[field] for x in performed) / len(performed)
    def mae(field: str) -> float:
        return sum(abs(x[field]) for x in performed) / len(performed)
    stats = {
        'n_notes': len(performed),
        'onset_mae_ms': round(mae('timing_error_ms'), 3),
        'intonation_mae_cents': round(mae('intonation_error_cents'), 3),
        'attack_mae': round(mae('attack_error'), 4),
        'signed_onset_mean_ms': round(avg('timing_error_ms'), 3),
        'signed_intonation_mean_cents': round(avg('intonation_error_cents'), 3),
        'signed_attack_mean': round(avg('attack_error'), 4),
    }
    return performed, stats


def practice(seed: int = 56) -> dict:
    """Three feedback passes correct *simulated controller bias*, not real muscles."""
    rng = random.Random(seed)
    plan = plan_events()
    params = {'timing_bias_s': .054, 'pitch_bias_cents': 18., 'attack_bias': .115}
    passes = []
    for n in range(1, 4):
        events, metrics = one_pass(plan, rng, params)
        passes.append({'pass': n, 'metrics': metrics, 'gestures': events})
        # Closed-loop adjustment from observed signed errors of synthetic output.
        params['timing_bias_s'] -= .88 * metrics['signed_onset_mean_ms'] / 1000
        params['pitch_bias_cents'] -= .88 * metrics['signed_intonation_mean_cents']
        params['attack_bias'] -= .88 * metrics['signed_attack_mean']
    return {
        'kind': 'offline_symbolic_setar_practice',
        'mode': 'D Shur-inspired; didactic phrase, not a radif transcription',
        'tuning_hz': OPEN_HZ,
        'limitation': 'Synthetic controller, approximate audio and virtual frets; no sensor, embodied hand, audition or human proficiency test.',
        'passes': passes,
    }


def add_pluck(buffer: list[float], start: float, frequency: float, attack: float, stroke: str) -> None:
    """A fast damped-harmonic approximation (not a calibrated setar body)."""
    i0 = max(0, round(start * SAMPLE_RATE))
    max_samples = min(len(buffer) - i0, round(SAMPLE_RATE * 1.18))
    direction_brightness = 1.0 if stroke == 'rast' else .88
    n_harmonics = min(7, int((SAMPLE_RATE / 2.2) / frequency))
    for i in range(max_samples):
        t = i / SAMPLE_RATE
        envelope = (1 - math.exp(-t * 280)) * math.exp(-3.7 * t)
        vibr = 0.0
        for h in range(1, n_harmonics + 1):
            strength = (1 / (h ** 1.3)) * math.exp(-t * .4 * h)
            vibr += strength * math.sin(2 * math.pi * frequency * h * t + .07 * h)
        transient = (math.sin(2 * math.pi * 1730 * t) * math.exp(-t * 125)) * .11
        buffer[i0 + i] += attack * direction_brightness * (.19 * envelope * vibr + .11 * transient)


def render_audio(session: dict, path: Path) -> list[float]:
    duration_one = max(e['target_onset_s'] + e['target_duration_s'] for e in session['passes'][0]['gestures'])
    section = duration_one + .65
    samples = [0.] * round((section * 3 + .4) * SAMPLE_RATE)
    for pi, pass_record in enumerate(session['passes']):
        origin = .15 + pi * section
        for event in pass_record['gestures']:
            add_pluck(samples, origin + max(0, event['sim_onset_s']), event['sim_hz'], event['sim_attack'], event['right_index_stroke'])
        # Occasional open low G string to indicate resonance / meter.
        for at in (0., duration_one / 2):
            add_pluck(samples, origin + at, OPEN_HZ[1], .28, 'rast')
    peak = max(abs(v) for v in samples) or 1
    pcm = b''.join(struct.pack('<h', int(max(-1., min(1., x * .89 / peak)) * 32767)) for x in samples)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)
    return [round(len(samples) / SAMPLE_RATE, 3), SAMPLE_RATE]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True, help='new empty output directory')
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise SystemExit('output directory already exists; use a fresh directory')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    session = practice()
    audio_stats = render_audio(session, args.output_dir / 'setar_shur_three_passes.wav')
    session['audio_duration_s'], session['audio_sample_rate_hz'] = audio_stats
    (args.output_dir / 'setar_gesture_log.json').write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding='utf-8')
    for p in session['passes']:
        print(f"pass {p['pass']}: onset MAE {p['metrics']['onset_mae_ms']} ms; intonation MAE {p['metrics']['intonation_mae_cents']} cents; attack MAE {p['metrics']['attack_mae']}")
    print('audio:', args.output_dir / 'setar_shur_three_passes.wav')


if __name__ == '__main__':
    main()
