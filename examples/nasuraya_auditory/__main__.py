"""Blind Persian ASR and the Tadash Resonan v0.26 auditory pathway."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .resonan import AuditoryContext, AuditoryResonanV26, SR

MODEL = "areffarhadi/Taraneh-WMedium"
REVISION = "09b6de55ecb64bb450360dbd30a7d3d88d08165b"
WEIGHTS_SHA256 = "a2344effe6b1b228f9052158965c3b4048ae176afbb485a09d0179d75adb9835"
WINDOW = 30 * SR
OVERLAP = 1400 * SR // 1000


def load_decoder(checkpoint):
    """Load the exact weights on CPU; no hub calls, lyric hints or prior text."""
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    folder = Path(checkpoint)
    with (folder / "model.safetensors").open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != WEIGHTS_SHA256:
        raise ValueError("Taraneh-WMedium weights differ from the pinned snapshot")
    small_files = json.loads(Path(__file__).with_name("hf_files.json").read_text())
    for name, oid in small_files.items():
        data = (folder / name).read_bytes()
        if hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != oid:
            raise ValueError(f"Taraneh-WMedium snapshot mismatch: {name}")
    processor = WhisperProcessor.from_pretrained(folder, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(
        folder, local_files_only=True, use_safetensors=True, dtype=torch.float32
    ).cpu().eval()

    def decode(pcm):
        features = processor.feature_extractor(
            pcm, sampling_rate=SR, return_tensors="pt", return_attention_mask=True
        )
        with torch.inference_mode():
            ids = model.generate(
                features.input_features, attention_mask=features.attention_mask,
                task="transcribe", language="fa", num_beams=1, do_sample=False,
                return_timestamps=False, max_new_tokens=225,
            )
        return processor.batch_decode(ids, skip_special_tokens=True)[0]
    return decode


def analyze(pcm, decode):
    """Use one PCM signal for both paths, preserving complete raw window hypotheses."""
    pcm = np.ascontiguousarray(pcm, dtype="<f4")
    if pcm.ndim != 1 or not len(pcm) or not np.isfinite(pcm).all():
        raise ValueError("Expected a nonempty finite mono waveform")
    pcm_hash = hashlib.sha256(pcm).hexdigest()
    ear = AuditoryResonanV26()
    for start in range(0, len(pcm), SR):
        ear.process(pcm[start:start + SR], AuditoryContext(
            event_id=f"{pcm_hash[:16]}-{start}", time_s=start / SR, content_kind="music"
        ))
    outputs = []
    for start in range(0, len(pcm), WINDOW - OVERLAP):
        stop = min(len(pcm), start + WINDOW)
        chunk = pcm[start:stop]
        text = decode(chunk)
        # At or below one unit of 16-bit PCM. Louder instrumental passages
        # cannot be identified by this gate and remain unverified.
        quiet = float(np.max(np.abs(chunk))) <= 1 / 32768
        status = "below_pcm16_floor" if quiet else ("unverified" if text.strip() else "empty")
        outputs.append({"start_sample": start, "end_sample": stop,
                        "start_s": start / SR, "end_s": stop / SR, "text": text,
                        "lexical_status": status,
                        "hypothesis": text.strip() if status == "unverified" else None})
        if stop == len(pcm):
            break
    return {"schema": "tadash-persian-auditory-v1", "sample_rate_hz": SR,
            "sample_count": len(pcm), "pcm_f32le_sha256": pcm_hash,
            "window_overlap_samples": OVERLAP, "windows": outputs,
            "resonan_events": ear.records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new local result file")
    pcm = AuditoryResonanV26.decode(args.audio)
    report = analyze(pcm, load_decoder(args.checkpoint))
    report["asr"] = {"model": MODEL, "revision": REVISION, "weights_sha256": WEIGHTS_SHA256,
                     "backend": "transformers-cpu-float32", "language": "fa",
                     "prompt": None, "previous_window_conditioning": False}
    with open(args.output, "x", encoding="utf-8",
              opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write("\n")


if __name__ == "__main__":
    main()
