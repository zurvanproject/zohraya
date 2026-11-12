# Video-engine readiness: live VPS probe, 2026-11-12

The owner asked to verify whether the existing Windows VPS can animate the supplied character image. A bounded, one-shot diagnostic ran through the existing Bridge; no generative model was installed or run.

- Source: `48853e5f966a8fb4d0f6be8874edee27d9f45308`, `tools/bridge_jobs/nasu_video_engine_probe.py`.
- Source SHA256: `deb42114f48140ce6f594ea5bc6c08855d12346f35b9fd5ecb420a3b326f8d57`.
- [Request](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6831981407).
- [Live receipt](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6831989041).

```text
VIDEO=ENC_DEC_OK;TORCH=0;DIFF=0;COMFY=NO_REPLY;WEIGHTS=0;PYALT=0;SCAN=OK;CUDA=NO_TORCH;GEN=NOT_READY
```

The SHA256-pinned FFmpeg encoded a one-second synthetic test pattern into H.264 MP4 in a pipe and decoded the resulting bytes successfully. This verifies encoding/decoding, not character animation.

The Bridge Python had neither torch nor diffusers. No model-weight candidates or alternate Python executables were found in the explicitly bounded model/application paths listed by `model_roots()`. That scan completed without hitting its limits. The fixed ComfyUI loopback status endpoint did not respond. These observations are scoped: they do not prove absence from arbitrary directories, other Windows accounts or other service ports. CUDA capability was not independently tested because torch was unavailable.

Conclusion: the inspected installation is ready for media assembly, but a working generative character-video engine is not present in the inspected runtime. No new character video was produced. No installation, paid API, permanent service change or merge occurred. The existing Bridge created its usual transient job and journal entry.

Six local checks passed, including rejection of an unverified executable, bounded-scan ambiguity, metadata-only weight detection, no torch child without the package, public-output constraints and an actual local pipe encode/decode. Windows VPS execution is separately evidenced by the live receipt above.
