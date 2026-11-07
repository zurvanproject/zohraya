#!/usr/bin/env python3
"""Tadash v0.26: functional auditory pathway and symbolic Resonan overlay.

Anatomical names are modelling anchors, not a biological reconstruction.
This module processes an audio recording; it has no live microphone, private
access to a speaker's feelings, or subjective hearing state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt


SR = 16000
FRAME = 400
HOP = 160
NFFT = 512


def clamp(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _mel(f: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + f / 700.0)


def _inv_mel(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def cochlear_bank(nbands: int = 24) -> np.ndarray:
    """Log-spaced overlapping filters: a toy tonotopic cochlear map."""
    edges = _inv_mel(np.linspace(_mel(np.array(80.0)),
                                 _mel(np.array(7000.0)), nbands + 2))
    hz = np.fft.rfftfreq(NFFT, 1 / SR)
    bank = np.zeros((nbands, len(hz)))
    for k in range(nbands):
        lo, mid, hi = edges[k:k + 3]
        bank[k] = np.maximum(0.0, np.minimum((hz - lo) / (mid - lo),
                                             (hi - hz) / (hi - mid)))
        bank[k] /= max(bank[k].sum(), 1e-12)
    return bank


@dataclass(frozen=True)
class AuditoryContext:
    event_id: str
    time_s: float
    content_kind: str = "unknown"  # music, speech, unknown
    resonan_attention: float = 0.5
    body_gate_open: bool = True
    semantic_context: str = ""  # user-supplied, never inferred from spectrum


class AuditoryResonanV26:
    """Afferent audio processing followed by delayed attentional response."""

    def __init__(self) -> None:
        self.bank = cochlear_bank()
        self.last_time_s = -1.0
        self.previous_salience = 0.0
        self.records: list[dict] = []
        self.by_id: dict[str, tuple[str, dict]] = {}

    @staticmethod
    def decode(path: str | Path) -> np.ndarray:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
             "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SR), "-"],
            capture_output=True, check=True)
        return np.frombuffer(p.stdout, dtype="<f4").copy()

    def process(self, signal: np.ndarray, ctx: AuditoryContext) -> dict:
        if not ctx.event_id or not math.isfinite(ctx.time_s) or ctx.time_s < 0:
            raise ValueError("invalid event clock or id")
        if ctx.content_kind not in {"music", "speech", "unknown"}:
            raise ValueError("content kind must be explicit")
        if not 0 <= ctx.resonan_attention <= 1 or not math.isfinite(ctx.resonan_attention):
            raise ValueError("attention outside bounded range")
        x = np.asarray(signal, dtype=np.float64)
        if x.ndim != 1 or not len(x) or not np.all(np.isfinite(x)):
            raise ValueError("audio must be a nonempty finite mono signal")
        digest = sha256(np.ascontiguousarray(x).tobytes() +
                        json.dumps(asdict(ctx), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if ctx.event_id in self.by_id:
            old, result = self.by_id[ctx.event_id]
            if old != digest:
                raise ValueError("event id reused with changed audio or context")
            return result
        if ctx.time_s <= self.last_time_s:
            raise ValueError("auditory event time must advance")

        # Outer canal / middle ear are frequency response proxies, not anatomy.
        outer = sosfilt(butter(2, [100, 7200], btype="bandpass", fs=SR,
                                 output="sos"), x)
        middle = np.tanh(1.2 * outer)  # bounded transmission, no hard clipping
        if len(middle) < FRAME:
            middle = np.pad(middle, (0, FRAME - len(middle)))
        windows = np.lib.stride_tricks.sliding_window_view(middle, FRAME)[::HOP]
        spec = np.abs(np.fft.rfft(windows * np.hanning(FRAME), n=NFFT))
        cochlea = np.log1p((spec @ self.bank.T) * 30.0)
        hair_cell = np.maximum(cochlea - 0.025, 0.0)  # toy transduction
        nerve = hair_cell / (1.0 + hair_cell)
        energy = np.sqrt(np.mean(windows ** 2, axis=1))
        active = energy > max(0.006, float(np.percentile(energy, 30) * 0.55))
        flux = np.maximum(0.0, np.diff(nerve, axis=0)).mean(axis=1)
        onsets = np.r_[0.0, flux]
        novelty = clamp(float(np.percentile(onsets, 90)) * 5)
        loudness = clamp(float(np.percentile(energy, 80)) * 2.5)
        dynamic = clamp(float(np.std(energy)) * 5)
        temporal_density = clamp(float(np.mean(onsets > max(.006, np.percentile(onsets, 75)))))
        band_mean = nerve.mean(axis=0)
        tonotopic_peak = int(np.argmax(band_mean))

        # Brainstem → thalamus → temporal auditory cortex: functional proxies.
        brainstem = {"onset_novelty": round(novelty, 5),
                     "active_fraction": round(float(active.mean()), 5)}
        thalamic_gain = 0.35 if not ctx.body_gate_open else 1.0
        cortex = {"loudness_proxy": round(loudness * thalamic_gain, 5),
                  "dynamic_range_proxy": round(dynamic, 5),
                  "temporal_density_proxy": round(temporal_density, 5),
                  "cochlear_peak_band_0_to_23": tonotopic_peak}
        # The Resonan is symbolic attention in Tadash; it adds no physical energy.
        salience = clamp(.45 * novelty + .25 * dynamic + .30 * ctx.resonan_attention)
        delayed_resonan = clamp(.65 * self.previous_salience + .35 * salience)
        result = {
            "schema": "nasuraya_auditory_resonan_v26_event",
            "event_id": ctx.event_id, "time_s": ctx.time_s,
            "duration_s": round(len(x) / SR, 3),
            "pathway": ["outer_ear", "middle_ear", "cochlear_bank",
                        "hair_cell_proxy", "auditory_nerve", "brainstem",
                        "medial_geniculate_proxy", "temporal_auditory_cortex",
                        "resonan_symbolic_attention"],
            "brainstem": brainstem, "cortex": cortex,
            "resonan": {"salience_current": round(salience, 5),
                        "attention_next_tick": round(delayed_resonan, 5),
                        "physical_energy_added": False},
            "speaker_emotion": {"state": "unknown",
                                "reason": "acoustics alone cannot establish a person's internal state"},
            "listener_response": {"state": "modelled_attentional_response",
                                  "felt_experience_claimed": False},
            "content_kind": ctx.content_kind,
            "semantic_context": ctx.semantic_context,
            "causal_order": "audio→afferents→cortex→next_tick_resonan",
            "audio_context_sha256": digest,
        }
        self.previous_salience = delayed_resonan
        self.last_time_s = ctx.time_s
        self.records.append(result)
        self.by_id[ctx.event_id] = digest, result
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--kind", choices=["music", "speech", "unknown"], default="unknown")
    args = parser.parse_args()
    model = AuditoryResonanV26()
    samples = model.decode(args.audio)
    print(json.dumps(model.process(samples, AuditoryContext(
        event_id="audio-1", time_s=0.0, content_kind=args.kind)),
        ensure_ascii=False, indent=2))
