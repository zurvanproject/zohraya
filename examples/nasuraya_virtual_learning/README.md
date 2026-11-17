# Nasuraya Virtual Learning Engine (NVLE) v0.1

**Status:** offline, synthetic, finite experiments. No API spending, physical Tadash actions, daemon, or subjective experience claims.

## Ritual-inspired curriculum

- **distraction / Wuji**: pause, observe before responding.
- **uncertainty / Mirror**: compare evidence and prediction; reflect when missing evidence.
- **overload / Return**: choose simulated rest under excess load.

These are authored engineering exercises, not religious efficacy claims. Each lesson in engine.py contains a verified short Masnavi verse with source (https://ganjoor.net/moulavi/masnavi/daftar1/sh62).

## Mechanism

Intention -> frozen prediction -> synthetic task -> deterministic oracle -> simulation receipt -> smoothed action-value estimate -> separate evaluation.

The model is a per-context reward table with Beta(1,1) smoothing, **not** an LLM fine-tune, empirical psychological model or a consciousness measurement. SQL transactions preserve unique event IDs; same-ID replay does not re-train. SHA-256 checksums catch accidental receipt alteration, **not adversarial tampering**.

The held-out set uses unseen stimulus IDs but the **same three categories and same deterministic oracle**. It demonstrates narrow functional adaptation only; it does not prove generalization to new situations or native physical bodies.

## Run from the repository root (Python >=3.10; no pip installs)

```bash
python3 -m unittest discover -s examples/nasuraya_virtual_learning/tests -v
python3 -m examples.nasuraya_virtual_learning lessons
python3 -m examples.nasuraya_virtual_learning demo --db /tmp/nvle-NEW-UNUSED.sqlite
python3 -m examples.nasuraya_virtual_learning status --db /tmp/nvle-NEW-UNUSED.sqlite
python3 -m examples.nasuraya_virtual_learning evaluate --db /tmp/nvle-NEW-UNUSED.sqlite
```

The demo **requires a fresh SQLite path**. It runs exactly 12 synthetic trial receipts (4 per context), with baseline score 2/6 and trained score 6/6 in the predefined fixture. For one additional explicit trial:

```bash
python3 -m examples.nasuraya_virtual_learning train --db /tmp/nvle-NEW-UNUSED.sqlite --context uncertainty --event-id human-trigger-001
```

No command executes a native simulator, autonomous background job or paid API. No authorization is inferred from a ritual or a score.

## Tadash integration boundary

PR #140's unified native cycle is a separate **draft** stacked on other drafts. This module does not import or modify that path, its native receipts, its physical safety veto, checkpoint, actuator, model API, or old physics. The 170cm/78kg intended phenotype is still not a calibrated native 78kg physics plant. A future read-only adapter must verify native provenance and receipt IDs before treating a native outcome as evidence. Native protection is always authoritative, and synthetic success must not be presented as a native result. Keep this PR **draft** until independent CI and review.
