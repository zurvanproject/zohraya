# Setar v0.3.1: repository integration and durable skill memory

The original v0.1 files are retained unchanged. The optional package entry point
now exposes the supplied v0.3 waveform-feedback controller as `SetarSkill`.
It inherits all 18 calibration nodes, both timing offsets and attack gains,
and **2,860 earlier updates**. Imported state is never trained in place.
This is repository/package integration, not integration into the body loop or VPS.

## Run from repository root

Python 3.11+, NumPy and SciPy are required for the new skill only. The v0.1
standalone script remains standard-library-only. Installation is explicit:

```sh
python -m pip install -r examples/setar_practice/requirements.txt
python -m examples.setar_practice status
python -m examples.setar_practice evaluate
python -m unittest examples.setar_practice.test_integration -v
```

A bounded accelerated smoke test, **not ten minutes of elapsed practice**:

```sh
python -m examples.setar_practice practice --accelerated --episodes 2 --output-dir /tmp/setar-smoke-001
python -m examples.setar_practice status --checkpoint /tmp/setar-smoke-001/checkpoint.json
```

An explicitly paced 600-second session, only when requested:

```sh
python -m examples.setar_practice practice --realtime --episodes 60 --output-dir /tmp/setar-session-001
```

Continue in a fresh directory from the previous run's saved calibration:

```sh
python -m examples.setar_practice practice --checkpoint /tmp/setar-session-001/checkpoint.json --realtime --episodes 60 --output-dir /tmp/setar-session-002
```

Every output directory must be new. The input checkpoint is read-only. Outputs
are `checkpoint.json`, `events.jsonl`, `summary.json`, `status.json` and
`practice.wav`. A new process reloads counts and calibration without training
from zero or double-counting inherited updates. The in-memory `SetarSkill`
object continues to reference its original input; choose the output checkpoint
explicitly for the next run.

The checkpoint is atomically replaced after each completed episode. Interrupted
runs are labeled failed/interrupted, not completed, and never automatically
replayed. The event log may contain an unfinished episode beyond the last
checkpoint. This is not a claim of arbitrary mid-note crash recovery or
power-loss durability. The input hash is checked before and after a run.

## What was verified locally

- All 33 SHA-256 manifest entries in the supplied v0.3 archive matched.
- 21 integration tests passed, including a fresh-process checkpoint reload.
- Six parity checks passed against the original supplied Python modules:
  all 1,460 events, generated waveforms, sensor outputs and final controller
  state matched, as did the 120-note evaluation.
- The imported historical final calibration reproduced 1.6551 cents pitch MAE,
  3.0030 milliseconds onset MAE and 2.3977 percent amplitude MAE on the same
  finite synthetic holdout. These are reproducibility results, not new gains.
- A separate two-episode accelerated CLI run wrote 36 new updates, resulting
  in 2,896 total; this test checkpoint did NOT replace the 2,860-update seed.

See `data/provenance.json` and `evidence/integration_validation.json`. Kernel
functions were extracted from the supplied modules with helper names flattened.
Changes are limited to malformed/nonfinite audio rejection and zero inherited
updates for a new unseeded controller. The package adapter validates checkpoints,
separates old/new counts, bounds runs and refuses output overwrites.

## Boundaries

`skill.json` is a discoverable descriptor, **not** a claim that a global registry
or body scheduler loads it. Importing the package starts no work. No body-loop,
core memory, Bridge, timer, server, authentication or CI workflow was changed.
No API, network or paid service is used by execution. MP3 recordings and the full
historical archive are not uploaded to GitHub; their provenance hashes are kept.
The archive remains in the conversation. Full-repository regression, independent
review and server execution have not been performed. Keep this PR Draft until
review; do not infer deployment or activation from the presence of these files.

This controller models isolated synthetic plucks, not hand joints, nail contact,
physical setar playing or learning of language-model weights. Holdout gains are
interpolation inside a known artificial calibration field; outside-range pitch
correction remains explicitly unsupported. Composition and rhythm are authored.
No new 600-second real-time session was run during this integration.
