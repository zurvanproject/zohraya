# ATMOSPHERE v0.4 research candidate | پوستهٔ شواهد، بازیابی و اتصال DIOS/Awake

**زمان توسعه:** ۱۵ نوامبر ۲۰۲۶ (UTC)  
**مبنا:** [ATMOSPHERE #237](https://github.com/zurvanproject/zohraya/pull/237) در `2ba8986782e9377d66b12bfb4777aa5f67351fe1` و [Tadash Awake #205](https://github.com/zurvanproject/zohraya/pull/205) در `90692bde9f1e4b5b7f311162b7c83127715df710`.  
**دامنه:** پیاده‌سازی جداگانهٔ Python، SQLite و tests؛ بدون اتصال به Bridge/VPS زنده و بدون merge.

## معماری

```
Snapshot مصنوعی DIOS + sensory (PR198)
    │  checked by source-pinned tadash_awake.bridge.extract
    ▼
۶ شاهد Awake با شناسهٔ پایدار
    │  canonical JSON digest + منبع / revision / timestamp
    ▼
Offline independent attester ── [Ed25519 signing key, never on VPS]
    │                        pinned verification public key + SHA256 from separate trust channel
    ▼
Evidence manifest signed for exactly the 6 committed payloads, TTL <=48h
    │ validate signature, identity, digest, freshness, capacity
    ▼
SQLite durable outbox: PENDING  ── crash/retry ──► revalidate signed manifest
    │  caller explicitly chooses scratch Awake root
    ▼
Awake.core.ingest(6 bounded scalar evidence)
    │ stable event ids -> duplicate safe
    ▼
SQLite durable outbox: DELIVERED
    │        no core.tick / core.resume, no DIOS or goal mutation
    ▼
Independent SQLite backup + hash + external ED25519 signed receipt
    │ restore only into NEW directory; independent external pin prevents rollback
    ▼
OFFLINE_REVIEW (never automatically activated)
```

## What is technically implemented

- `tools/atmosphere_attestation.py`: canonical bounded schema, independent pinned Ed25519 public key, signed manifest, 24-hour evidence age limit, reject self-hash forgery, TTL and replay constraints, persistent SQLite outbox with full signed manifest retention, revalidation on delivery, all-or-nothing batch staging; `authority=none`, `establishes_truth=False`.
- `tools/atmosphere_awake_adapter.py`: checks exact SHA256 of installed `tadash_awake/core.py` and `bridge.py` supplied via operator-trusted pins. Uses **original** `bridge.extract` to obtain six source-pinned synthetic sensor/DIOS/goal scalars, then `Awake.core.ingest` only. No `tick`, `set_paused`, outbound network, Bridge or DIOS write. Receipt proves only that six inputs were ingested.
- `tools/atmosphere_recovery.py`: consistent SQLite `.backup()` snapshots of Awake and outbox; actual `PRAGMA integrity_check`, expected table schemas and consistency of marked-delivered events. An external Ed25519 signature **and independently retained checkpoint SHA256** are both required to verify/restore. Restoration refuses existing targets.
- `tools/atmosphere_offline_signer.py`: optional **offline-only** signing with an already-existing operator-supplied private key. No key generation, no network, no persistent credential in the code or test artifacts. The operator must audit the original source before signing.
- `tests/test_atmosphere_*.py`: signature tampering, replays, stale and forged evidence, atomic bundles, DB tampering, backup corruption/rollback, non-destructive restoration, crash after Awake ingestion, and PR205 direct-source integration when the checkout is present.

## Strict trust requirements

1. The signing private key and the out-of-band verification key fingerprint must be stored separately from the runtime host and its SQLite directory. **Do not publish or place private keys on GitHub.** A digest signed by the same compromised machine is NOT independent attestation.
2. The verifier requires the operator-provided raw Ed25519 public key **and** an independent SHA256 pin. `PinnedRoot` refuses a mismatch. No pin is extracted from input data, a prompt, a model, or the SQLite file.
3. The `manifest` must describe only snapshots whose origin the offline signer independently checked. Simply signing whatever `prepare_unsigned()` printed is **not enough**. The PR198 snapshot self-hash is not proof of external provenance or physical sensing.
4. Each signed manifest has a limited validity window and each new observation must be fresh. If offline >24h, stalled pending events fail closed; manual review or re-attestation is required. A stopped clock/unsigned data should not be silently trusted.
5. A signed backup receipt and **independent receipt SHA pin** should be kept on a different device/account/media. Without a real external copy, the tested 'separate directory' is not a disaster-recovery backup. A signed and pinned old checkpoint cannot be used to replace a newer pinned checkpoint without an operator mistake.
6. Crypto support is `cryptography` (`Ed25519PublicKey`). If missing, verification refuses to run. Install from a trusted, pre-provisioned offline wheel before an isolation event; no network or paid API is needed at runtime.

## Safe local test

```bash
python -m unittest discover -s tests -p 'test_atmosphere_*.py' -v
```

For **direct** original-module contract testing, the checked-out source of PR205 must be on `PYTHONPATH`, with its immutable SHA pin verified against a trusted reference. Run that one test with only temporary directories; it does not contact any VPS or main branch. The original source must be checked out independently. All tests use synthetic data and temporary keys created in memory (and a temporary 0600 test PEM for file-permission testing); no production credential is produced.

## Controlled API usage (operator-run, isolated directories)

```python
from atmosphere_attestation import PinnedRoot
from atmosphere_awake_adapter import ControlledAwakeAdapter
from atmosphere_recovery import create_snapshot, restore_to_new_directory

root = PinnedRoot(operator_public_key_hex, operator_out_of_band_public_sha256)
adapter = ControlledAwakeAdapter(
    outbox_path="/safe-lab/outbox/evidence_outbox.sqlite3",
    awake_root="/safe-lab/awake",
    trusted_core_sha256=operator_pinned_awake_core_digest,
    trusted_bridge_sha256=operator_pinned_awake_bridge_digest,
)
envelopes, unsigned_status = adapter.prepare_unsigned(snapshot, stream="lab", observed_at=clock)
# Independent attester compares source and signs EXACT envelope commitments OFFLINE.
result = adapter.stage_signed(snapshot, stream="lab", observed_at=clock,
                              manifest=operator_signed_manifest, root=root, now=clock)
delivery = adapter.deliver_pending(root=root, now=clock)
# Awake remains paused; no DIOS action occurs. Backup only after quiescing writers.
unsigned_receipt = create_snapshot(
    awake_db="/safe-lab/awake/awake.sqlite3",
    outbox_db="/safe-lab/outbox/evidence_outbox.sqlite3",
    archive_dir="/other-volume/backup-001", now=clock,
)
# Offline signer seals unsigned_receipt, operator stores the receipt SHA256 separately.
restore_to_new_directory("/other-volume/backup-001", "/safe-lab/recovered-001",
                         signed_receipt, root=root,
                         expected_receipt_sha256=operator_pinned_receipt_sha256)
```

This is an *API example* using deliberately undefined operator inputs; it is not an autorun script, credential and server configuration, or claim that any operational key was provisioned.

## Not done / acceptance gates

- **Not deployed** to Windows, Ubuntu, original Bridge, live DIOS, or the real Awake memory. No network service, automatic scheduler, service activation, merge, or ongoing autonomous agent.
- No hardware provenance, TPM/secure element, witnessed physical sensor, or live external root of trust exists in this code; operator key provisioning and an independent signer are prerequisites.
- Backup copies have been tested on a single machine. Real second-machine/off-site recovery, incident response, loss of VPS and loss of entire internet are NOT verified.
- A signed record can still be false; this scheme protects bounded source commitments, not truth, awareness, or safety of an action. It issues no execution capability.
- The existing PR205 source is a research branch. CI direct-source tests and manual review are mandatory before any promotion; mode default remains paused.

**Acceptance criterion for future authorized deployment:** direct PR205 integration green, root fingerprint verified out of band, external signer independently trusted, external backup and restore tested, full fault-injection, old/runtime compatibility, permission audit, system rollback plan and explicit owner signoff. Otherwise fail closed.