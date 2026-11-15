"""Waveform-feedback setar kernel, extracted from supplied v0.2/v0.3.
Synthetic isolated-note audio only. No physical hand or validated acoustics.
The 350-cent E-koron is an exercise convention, not a universal tuning.
See data/provenance.json for source hashes and integration evidence.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate
from scipy.interpolate import PchipInterpolator

SR = 22050
OPEN_HZ = {1: 261.625565, 2: 195.997718}
DIRECTIONS = ('rast', 'chap')
NOTE_S = .82
TARGET_LOCAL = .12
TRAIN_FRETS = (0., 1.5, 2., 3.5, 5., 6., 7., 8., 9.)
HOLDOUT_FRETS = (1., 2.75, 4.25, 6.5, 7.5, 8.5)
EVAL_SEEDS = (91011, 92122, 93233, 94344, 95455)
STAGES = ('retention', 'new_calibration_nodes', 'string_switches',
          'five_short_phrases', 'alternating_tremolo', 'mixed_consolidation')
REFERENCE = {}


def key(s,f): return f'{s}:{f:g}'


def hz(s,f): return OPEN_HZ[s]*2**(f/12)


def modal_pluck(frequency,onset,amplitude,stroke,duration=NOTE_S):
    sample=np.arange(round(duration*SR),dtype=np.float64)/SR
    t=np.maximum(sample-onset,0); active=sample>=onset
    attack=-np.expm1(-t*1800); out=np.zeros_like(sample)
    brightness=1.12 if stroke=='rast' else 1.32
    for h in range(1,10):
        if frequency*h>=SR/2: break
        out+=np.sin(2*np.pi*frequency*h*t+.16*h)*np.exp(-t*(3.7+.58*h))/h**brightness
    out*=.15*amplitude*attack*active
    out+=active*amplitude*.009*np.sin(2*np.pi*1910*t)*np.exp(-t*165)
    return out


def audio_sensor(recording):
    """Waveform-only sensor; no access to latent plant error or target pitch."""
    peak=float(np.max(np.abs(recording)))
    if peak<.002: return {'valid':False,'reason':'no_detectable_note'}
    indices=np.flatnonzero(np.abs(recording)>=max(.0015,.025*peak))
    if not len(indices): return {'valid':False,'reason':'onset_not_found'}
    onset_i=int(indices[0]); start=onset_i+round(.035*SR); end=onset_i+round(.26*SR)
    if end>len(recording): return {'valid':False,'reason':'insufficient_audio'}
    signal=recording[start:end]; signal=(signal-signal.mean())*np.hanning(len(signal))
    nfft=65536; spectrum=np.abs(np.fft.rfft(signal,nfft)); freqs=np.fft.rfftfreq(nfft,1/SR)
    valid=np.flatnonzero((freqs>=90)&(freqs<=850)); p=int(valid[np.argmax(spectrum[valid])])
    logs=np.log(spectrum[p-1:p+2]+1e-20); denom=logs[0]-2*logs[1]+logs[2]
    shift=.5*(logs[0]-logs[2])/denom if abs(denom)>1e-15 else 0.
    frequency=(p+float(np.clip(shift,-.5,.5)))*SR/nfft
    amp_slice=recording[onset_i+round(.02*SR):onset_i+round(.10*SR)]
    return {'valid':True,'onset_s':onset_i/SR,'frequency_hz':frequency,
            'rms':float(np.sqrt(np.mean(amp_slice**2)))}


def metrics(rows):
    good=[r for r in rows if r.get('valid')]
    result={'notes':len(rows),'valid_notes':len(good),'missing_notes':len(rows)-len(good)}
    for source,label in [('pitch_error_cents','pitch_cents'),('onset_error_ms','onset_ms'),('attack_error_percent','attack_percent')]:
        a=np.array([abs(r[source]) for r in good])
        result[label+'_mae']=float(a.mean()) if len(a) else None
        result[label+'_p95']=float(np.percentile(a,95)) if len(a) else None
    return result


def write_audio(path,samples):
    peak=float(np.max(np.abs(samples))); attenuation=min(1.,.97/max(peak,1e-12))
    wavfile.write(path,SR,np.round(np.clip(samples*attenuation,-.999,.999)*32767).astype(np.int16))
    return {'duration_s':len(samples)/SR,'peak_before_encoding':peak,'attenuation':attenuation,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def periodicity_frequency(frame):
    """YIN-inspired normalized lag difference, not an exact reference YIN port."""
    x = np.asarray(frame, np.float64)
    x = x - x.mean()
    n = len(x)
    minimum = math.floor(SR / 850)
    maximum = math.ceil(SR / 90)
    ac = correlate(x, x, mode='full', method='fft')[n-1:n+maximum]
    square = np.r_[0., np.cumsum(x*x)]
    lag = np.arange(maximum+1)
    difference = np.maximum(square[n-lag]+square[n]-square[lag]-2*ac, 0.)
    normalized = np.ones(maximum+1)
    normalized[1:] = difference[1:]*np.arange(1, maximum+1) / np.maximum(np.cumsum(difference[1:]), 1e-30)
    tau = None
    for i in range(max(2, minimum), maximum-1):
        if normalized[i] < .14:
            while i+1 < maximum and normalized[i+1] < normalized[i]:
                i += 1
            tau = i
            break
    if tau is None:
        tau = minimum + int(np.argmin(normalized[minimum:maximum]))
        if normalized[tau] > .35:
            return None, float(1-normalized[tau])
    a, b, c = normalized[tau-1:tau+2]
    denominator = a-2*b+c
    delta = .5*(a-c)/denominator if abs(denominator) > 1e-18 else 0.
    return SR/(tau+float(np.clip(delta, -.5, .5))), float(1-normalized[tau])


def sensor(recording):
    """No expected note/frequency input. Refuse nonperiodic/ambiguous signals."""
    recording = np.asarray(recording, dtype=np.float64)
    if recording.ndim != 1 or len(recording) < round(.3*SR) or not np.all(np.isfinite(recording)):
        return {'valid': False, 'reason': 'invalid_audio'}
    spectral = audio_sensor(recording)
    if not spectral.get('valid'):
        return spectral
    onset_i = round(spectral['onset_s']*SR)
    frame = recording[onset_i+round(.035*SR):onset_i+round(.26*SR)]
    periodic, confidence = periodicity_frequency(frame)
    if periodic is None:
        return {'valid': False, 'reason': 'weak_periodicity', 'periodicity_score': confidence}
    discrepancy = 1200*math.log2(spectral['frequency_hz']/periodic)
    harmonic_gap = min(abs(discrepancy-1200*math.log2(k)) for k in (2, 3, 4))
    result = dict(spectral)
    result.update(periodicity_score=confidence, estimator_disagreement_cents=discrepancy,
                  pitch_estimator='spectral_periodicity_agreement')
    if harmonic_gap < 25 and confidence > .85:
        result['frequency_hz'] = periodic
        result['pitch_estimator'] = 'periodicity_harmonic_correction'
    elif abs(discrepancy) > 25:
        return {'valid': False, 'reason': 'pitch_estimators_disagree',
                'estimator_disagreement_cents': discrepancy, 'periodicity_score': confidence}
    return result


@dataclass
class Controller:
    pitch_cents: dict = field(default_factory=dict)
    timing_s: dict = field(default_factory=lambda: {'rast': 0., 'chap': 0.})
    attack_gain: dict = field(default_factory=lambda: {'rast': 1., 'chap': 1.})
    updates: int = 0
    rejected_observations: int = 0
    node_updates: dict = field(default_factory=dict)
    interpolate: bool = True
    inherited_updates: int = 0

    def correction(self, string, fret):
        k = key(string, fret)
        if k in self.pitch_cents:
            return self.pitch_cents[k], 'measured_node'
        if not self.interpolate:
            return 0., 'untrained_exact_lookup'
        nodes = sorted((float(k.split(':')[1]), v) for k, v in self.pitch_cents.items()
                       if k.split(':')[0] == str(string))
        if len(nodes) < 2 or fret < nodes[0][0] or fret > nodes[-1][0]:
            return 0., 'outside_calibrated_range'
        x, y = zip(*nodes)
        return float(PchipInterpolator(x, y, extrapolate=False)(fret)), 'interpolated_unmeasured_target'

    def observe(self, event, measured):
        if not measured.get('valid'):
            self.rejected_observations += 1
            return
        if event['semitones'] not in TRAIN_FRETS:
            raise ValueError('held-out/non-training pitch cannot update this controller')
        k = key(event['string'], event['semitones'])
        value, _ = self.correction(event['string'], event['semitones'])
        count = self.node_updates.get(k, 0)
        alpha = .14 if count < 15 else .055
        self.pitch_cents[k] = float(np.clip(value-alpha*measured['pitch_error_cents'], -100, 100))
        self.node_updates[k] = count+1
        stroke = event['stroke']
        self.timing_s[stroke] = float(np.clip(self.timing_s[stroke]-.06*measured['onset_error_ms']/1000, -.085, .035))
        self.attack_gain[stroke] = float(np.clip(self.attack_gain[stroke]*measured['rms_ratio']**(-.06), .4, 1.8))
        self.updates += 1


def render_observe(event, controller, rng):
    """Same latent disturbances as v0.2, with measured-waveform-only feedback."""
    s, f, stroke = event['string'], event['semitones'], event['stroke']
    correction, correction_kind = controller.correction(s, f)
    detune = (17. if s == 1 else -14.)+4.5*math.sin(1.18*f)+.28*f+rng.normal(0, 1.9)
    latency = (.043 if stroke == 'rast' else .066)+rng.normal(0, .0035)
    gain = (1.17 if stroke == 'rast' else .79)*math.exp(rng.normal(0, .028))
    frequency = hz(s, f)*2**((detune+correction)/1200)
    onset = TARGET_LOCAL+latency+controller.timing_s[stroke]
    amplitude = event['attack']*gain*controller.attack_gain[stroke]
    recording = modal_pluck(frequency, onset, amplitude, stroke)
    recording += rng.normal(0, .000008, len(recording))
    result = sensor(recording)
    if result.get('valid'):
        k = (s, f, stroke, event['attack'])
        if k not in REFERENCE:
            REFERENCE[k] = sensor(modal_pluck(hz(s, f), TARGET_LOCAL, event['attack'], stroke))
        target = REFERENCE[k]
        result.update(pitch_error_cents=1200*math.log2(result['frequency_hz']/hz(s, f)),
                      onset_error_ms=1000*(result['onset_s']-target['onset_s']),
                      rms_ratio=result['rms']/target['rms'],
                      attack_error_percent=100*(result['rms']/target['rms']-1))
    return recording, result, {'pitch_correction_cents': correction, 'correction_kind': correction_kind}


def make_event(index, string, fret, onset=.2, attack=.62):
    return dict(index=int(index), string=int(string), semitones=float(fret), onset_s=float(onset),
                attack=float(attack), stroke=DIRECTIONS[index % 2])


def exercise(index):
    stage = index//10
    rng = np.random.default_rng(351500+index)
    if stage == 0:
        frets = (2., 3.5, 5., 7., 9.)
        notes = [(1+i % 2, frets[(i//2+index) % len(frets)]) for i in range(18)]
    elif stage == 1:
        frets = (0., 1.5, 2., 3.5, 5., 6., 7., 8., 9., 6., 8.)
        notes = [(1+i % 2, frets[(i//2+index) % len(frets)]) for i in range(22)]
    elif stage == 2:
        notes = [(1+i % 2, TRAIN_FRETS[(i//2+index) % len(TRAIN_FRETS)]) for i in range(24)]
    elif stage == 3:
        phrases = ((2, 3.5, 5, 3.5, 2, 2), (2, 5, 7, 5, 3.5, 2),
                   (5, 7, 5, 3.5, 5, 2), (7, 7, 5, 3.5, 2, 3.5), (5, 3.5, 2, 3.5, 2, 2))
        line = phrases[index % 5]
        notes = [(1, line[i % len(line)]) for i in range(18)]
    elif stage == 4:
        notes = [(1, TRAIN_FRETS[(i//10+index) % len(TRAIN_FRETS)]) for i in range(40)]
    else:
        notes = [(1 if i % 4 else 2, float(rng.choice(TRAIN_FRETS))) for i in range(24)]
    if stage == 4:
        times = [.18+block*2.42+j*.165 for block in range(4) for j in range(10)]
    else:
        durations = rng.choice([.7, 1., 1.4], len(notes)) if stage in (3, 5) else np.ones(len(notes))
        times = .15+np.r_[0., np.cumsum(durations[:-1])]/durations.sum()*9.3
    events = [make_event(i, s, f, t, .52+.14*(.5+.5*math.sin(i*.73)))
              for i, ((s, f), t) in enumerate(zip(notes, times))]
    return STAGES[stage], events


def evaluate(controller, frets, seeds=EVAL_SEEDS):
    state = json.dumps(asdict(controller), sort_keys=True)
    rows = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        index = 0
        for s in (1, 2):
            for f in frets:
                for direction in range(2):
                    event = make_event(index+direction, s, f, attack=.55+.05*(index % 3))
                    _, result, correction = render_observe(event, controller, rng)
                    rows.append(dict(seed=seed, event=event, measurement=result, command=correction))
                index += 2
    if json.dumps(asdict(controller), sort_keys=True) != state:
        raise AssertionError('Evaluation modified controller')
    summary = metrics([r['measurement'] for r in rows])
    summary['by_fret'] = {str(f): metrics([r['measurement'] for r in rows if r['event']['semitones'] == f]) for f in frets}
    return summary, rows


def mix_stem(signal, stem, at):
    pos = round(at*SR)
    n = min(len(stem), len(signal)-pos)
    if n > 0:
        signal[pos:pos+n] += stem[:n]
