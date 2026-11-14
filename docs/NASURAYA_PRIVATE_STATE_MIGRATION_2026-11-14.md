# Private workload archive migration — 2026-11-14

The live Awake cutover and ten public source snapshots are already verified
on Ubuntu. This change preserves the remaining original Windows workload
files as inactive, versioned archives. It does not activate those workloads,
port a paid model worker, replay old goals, or claim credential migration.

## Observed source state

After guarded recovery, Bridge v2 returned fresh receipts:

- Awake task Disabled, 54 events / 6 questions / 25 ticks:
  https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6877445249
- Ingress task Disabled, workshop revision 9:
  https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6877457414
- Complete metadata-only inventory, 12:46:49 UTC:
  https://github.com/zurvanproject/zohraya/issues/212#issuecomment-6877470061
  All eight scanned roots are present/readable. The Bridge transport root
  overlaps the atlas and study roots, so its file count must not be added to
  the other roots as a unique-file total.

## Data groups

Eight separate archives preserve the workshop, public-discussion memory,
body atlas, completed 96-cycle study, Moltbook history, legacy Tadash,
model-worker files, and the three Bridge journal/health/log files. The live
Awake database is not exported again or replaced. Legacy 195 kg body state
remains historical; source preservation does not make it the current body.

Source roots are fixed in the Windows job. Each database is copied using
SQLite's backup API and checked for integrity, including committed WAL
content. Non-database files must remain unchanged during copying. Symlinks,
junctions, excessive file sizes and unexpected structures block export.
Credentials, keys, caches, process locks and SQLite sidecars are excluded;
the encrypted manifest records every exclusion. Sidecar content is captured
through the corresponding database snapshot. These are point-in-time
archives, not an atomic multi-application runtime cutover. Other Windows
tasks remain unchanged until their individual cutovers are ready.

## Confidential transport

Only ciphertext is posted to the existing owner-controlled Issue #216.
Filenames, file hashes, database rows, model dialogues and the private file
manifest remain inside the encrypted ZIP. Public metadata contains only
component identity, aggregate counts, ciphertext identity and timestamp.

Each archive uses fresh random encryption material and a separate random
HMAC key. PBKDF2-HMAC-SHA256 derives the AES-256-CBC key/IV from the random
encryption material. Encrypt-then-MAC authenticates the canonical envelope
header and ciphertext before any AES decryption or ZIP processing. RSA-3072
OAEP-SHA256 wraps the key material independently for the existing verified
Iran and offsite recovery recipients. Windows uses .NET AES; Ubuntu uses
OpenSSL 3, passing the encryption material through a private file descriptor.
The recipient private key never leaves Ubuntu and is not passed in argv.

The Windows outbox stores only ciphertext and public envelope metadata.
Uploads resume in bounded batches. Identical duplicate parts after an
ambiguous HTTP result are accepted; conflicting duplicates or incomplete
completed archives are rejected. No private credential is printed or moved.
An offsite wrapper proves availability of a recovery path, not a fresh
offsite decryption test.

## Ubuntu import and review

From the reviewed exact commit in a clean `/opt/zohraya` checkout, root runs:

```sh
bash tools/install_nasu_workload_state.sh
```

This installs an unprivileged importer, adds two fixed Bridge commands, and
restarts only the Bridge. It checks the existing recipient key and imports
completed archives into `/var/lib/nasuraya/workloads/imports/<component>/<id>`.
Files are private and inactive. The importer verifies authentication, file
sets, hashes, sizes and database integrity before installing a new version.
Changed existing archives are preserved and reported invalid instead of
being overwritten. The live Awake state/gate/timer are outside its scope.

```text
nasu-linux: workload-import
nasu-linux: workload-data-status
```

`workload-import` imports at most one new completed archive.
`workload-data-status` rechecks installed archive contents and reports
`archived_verified`, `missing`, or `invalid_requires_review` separately from
activation. Credentials are explicitly `not_imported`. Further Linux runtime
ports, private credential provisioning, workshop continuation and individual
scheduler cutovers remain separate follow-up work after archive verification.

## Validation

Tests cover encrypted roundtrip, .NET AES to OpenSSL interoperability,
committed SQLite WAL preservation, no credential/plaintext publication,
authentication failures before AES decryption, missing/conflicting parts,
idempotent duplicate delivery, traversal/symlink rejection, modified existing
imports, and preserving the Bridge transport boundary. Tests use synthetic
private data and ephemeral test recipient keys only. Server receipts, not CI,
will establish actual export/import completion for each component.
