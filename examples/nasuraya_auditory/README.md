# Local Persian auditory readout

One decoded waveform drives the original Tadash Resonan v0.26 auditory model and an independent Persian ASR pass. Resonan receives consecutive one-second events, plus the final partial second, in order. The ASR pass uses only audio, the Persian language setting and the transcription task. It restarts the decoder for each window, preserves the raw hypotheses and labels them unverified. It never feeds text back into Resonan or writes to the body ledger.

## Run

Use Python 3.11–3.12, CPU PyTorch and an ffmpeg executable on PATH. Install in a separate environment.

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install transformers==4.57.1 numpy==2.2.6 scipy==1.15.3
python -c "from huggingface_hub import snapshot_download; snapshot_download('areffarhadi/Taraneh-WMedium', revision='09b6de55ecb64bb450360dbd30a7d3d88d08165b', local_dir='/private/models/taraneh-medium')"
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 python -m examples.nasuraya_auditory /private/input.wav --checkpoint /private/models/taraneh-medium --output /private/receipt.json
```

Only provisioning the model needs the network. The command loads local weights and tokenizer files after checking their digests against the pinned snapshot. Provisioning requires about 3.1 GB for the weights, plus the environment. Keep input and output outside the repository. The output includes unredacted hypotheses and a PCM fingerprint.

## Read the receipt

- `windows[].text` contains exactly what the decoder returned. Times bound audio windows, not individual words. Windows are at most 30 seconds with 1.4 seconds of overlap. Repeated text crossing a window boundary is retained for review.
- `lexical_status` is `unverified` for nonempty hypotheses on audible input. If a window never exceeds one 16-bit PCM unit, its raw text is still preserved, but `hypothesis` is null. An empty hypothesis on audible input also stays null. Instrument-only passages need an independently labeled control to evaluate hallucinations.
- `resonan_events` is a separate non-overlapping event stream with actual v0.26 acoustic measurements, shared source time and next-tick modeled attention.
- `asr` records the checkpoint revision, backend, language and lack of text prompting. The join key for local comparisons is `pcm_f32le_sha256`. No global transcript or lexical accuracy is inferred by the adapter.

## Verification

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest examples.nasuraya_auditory.test_auditory -v
```

The contract tests use a deterministic stub only for the lexical decoder and run the real Resonan signal path. The independent CPU smoke in CI acquires the pinned checkpoint and uses a generated one-second silent WAV. Its success verifies real loading, generation, receipt shape and the silence rule. Singing accuracy needs a separate blind evaluation.

The acoustic module in `resonan.py` is the original project auditory v0.26 source (SHA-256 `7f069ea1264531a785c8f22530948c61cece2b6f8f0031de5f23ff8378e3e850`). The Persian model and decoding recipe are from [Taraneh-ASR](https://github.com/areffarhadi/persian-asr) and its [pinned WMedium checkpoint](https://huggingface.co/areffarhadi/Taraneh-WMedium/tree/09b6de55ecb64bb450360dbd30a7d3d88d08165b).
