# Proposed PR #234 extension: active Ollama Qwen3 4B recovery

**REVIEW ONLY. NOT APPLIED TO GITHUB, NOT DEPLOYED, NO VPS CONTACT.**

The existing restic v2 snapshot verifies three SQLite journals and a Git bundle, but
its model flag refers to an optional Qwen3 1.7B llama.cpp GGUF, not the active
`qwen3:4b-instruct` served by Ollama. This addendum proposes an **opt-in** v3
payload. Old v2 snapshots remain readable.

## What gets archived

* The **exact installed tag manifest** `manifests/registry.ollama.ai/library/qwen3/4b-instruct`
  and only its **transitively referenced** `blobs/sha256-*` layers (including config).
  Every blob size and SHA-256 is validated against the OCI descriptor before packaging.
* The installed `ollama` executable and *all regular files* under its `lib/ollama`
  directory. In-tree library symlinks are resolved to regular files; escaping links
  are rejected. This is more reliable than backing up only a single executable.
* Three private artifacts: `ollama-qwen3-4b-models.tar.gz`,
  `ollama-qwen3-4b-runtime.tar.gz`, and `ollama-qwen3-4b-info.json`.
  The metadata contains SHA-256 for **every** payload file and both tar files,
  source manifest digest, installed Ollama `--version` output, architecture,
  Ubuntu/Debian ID and VERSION_ID, and the local `ldd` dependency inventory.
  The parent restic manifest also SHA-256 hashes these three files.
* Existing SQLite backups, cognitive receipt-chain checks, old 1.7B optional
  model path and Git bundle are unchanged. No credentials, production systemd
  config, API tokens, or arbitrary `~/.ollama` files are included.

## Preconditions before any operator-approved deployment

Source is the PR #234 head revision agreed during review. The Ubuntu service
may use `OLLAMA_MODELS` instead of the default
`/usr/share/ollama/.ollama/models`; inspect the **service's** effective model
store and set `NASU_OLLAMA_MODELS_DIR` explicitly if it differs. Confirm the
installed binary and Ollama runtime library directory, commonly `/usr/bin/ollama`
and `/usr/lib/ollama`. Some installations use `/usr/local/...`.

The **proposed**, not-yet-run opt-in for the existing backup script is:

```bash
export NASU_BUNDLE_OLLAMA_QWEN3_4B=1
# Only if the actual service is customized:
# export NASU_OLLAMA_MODELS_DIR=/the/verified/model/store
# export NASU_OLLAMA_BIN=/the/installed/ollama
# export NASU_OLLAMA_LIB_DIR=/the/installed/lib/ollama
# After separate approval and approved independent RESTIC_* credentials:
# bash tools/nasu_offsite_restore_drill.sh
```

If any configured file is missing, linked out of bounds or hash-inconsistent,
**the backup fails before `restic backup`**. The opt-in defaults to `0` for
backwards compatibility, and never silently downgrades an attempted v3 backup.
The new backup manifest schema is `nasuraya-restic-offsite/3` only if the
4B assets were staged and verified. Its `ollama_qwen3_4b_recoverable=true`
means **verified bytes included**, **not** a witnessed model inference pass.
`ollama_qwen3_4b_independent_smoke_pass` stays false. A fresh-host proof is a
separate external operator receipt, never set by the backup producer.

## Fresh-host cold recovery, no downloads

Before a planned outage prepare an **independently administered** host image
with a matching CPU architecture and Linux distribution VERSION_ID. Required
base-image packages include Python 3.12+, `iproute2` (`ip`), `util-linux`
(`unshare`), `git`, a compatible `libc`/`libstdc++` runtime, and `restic` if
the host itself decrypts backup snapshots. This proposed patch archives the
installed Ollama binary and its private libraries **but not the whole Ubuntu
OS image or every apt `.deb`**. If those packages are missing, this is NOT a
self-contained bare-metal rescue kit and must be reported as a blocker.
A future vetted offline recovery image/package-cache with its own hashes
would close that additional gate.

On that independent host, using **out-of-band** restic and SFTP/S3 credentials,
restore the selected encrypted snapshot to a new temporary directory. Never
restore over `/var/lib/nasuraya` or an existing running Ollama store. Get the
matching source code from the verified `zohraya.bundle` (or a separately held
copy) without fetching from GitHub. Then run:

```bash
python3 tools/nasu_verify_restored_snapshot.py /path/to/restored/snapshot
python3 tools/nasu_ollama_4b_recovery.py verify /path/to/restored/snapshot
python3 tools/nasu_ollama_4b_recovery.py smoke /path/to/restored/snapshot
```

`smoke` refuses absent `ip`/`unshare`, validates hashes and architecture, then
launches a **new Linux network namespace** (fails closed if unavailable),
extracts the verified model and runtime under a disposable temporary directory,
starts **only a temporary loopback-bound Ollama server** with
`OLLAMA_NO_CLOUD=1`, issues a bounded real `/api/generate` prompt with
`model=qwen3:4b-instruct`, checks completion and nonempty output, and terminates
the temporary server. The only returned model result is an output hash.
It neither installs nor enables any service. The external network cannot be
reached from the namespace; if namespace creation or cold start fails, no PASS.

Do not mark the end-to-end gate PASS without an operator witness identifying
a truly **independent machine**, successful out-of-band decryption, an actual
restored Qwen3 4B inference result, a controlled reboot test, and evidence that
all essential packages were present *without any network download*.

## Space and resource limits

According to the Ollama model registry, the standard `qwen3:4b-instruct`
quantization is approximately **2.5 GB** (tag digest prefix `0edcdef34593`).
The actual on-host manifest, hashes, layer count, quantization and size take
precedence: do **not** assume the public tag has stayed identical. The helper
rejects more than 64 model files or more than 20 GiB uncompressed model bytes;
more than 4096 runtime files or more than 8 GiB uncompressed runtime bytes.
A full temporary staging snapshot, restic repository and fresh-host extraction
require additional free disk. A safe planning allowance is **at least 3x the
measured model+runtime payload**, plus the independent encrypted repository,
existing SQLite/archive sizes and safety margin. Before enabling a periodic
backup, measure staging/runtime disk peaks and timing on a staging host.

CPU-only Q4 4B typically needs multiple GB RAM. The source report had about
15 GiB. This is a capacity estimate, not a measured peak. The smoke caps
parallel model loads to 1, uses two inference threads, 1024 tokens of context,
and 80 predicted tokens; it does **not** prove a 6-month unattended workload.

## Security and rollback

The recovery helper permits only known relative tar paths, regular files,
bounded entries/bytes and SHA-256-verified payloads; it rejects symlink escape,
archive traversal, truncated/missing layers, modified archives and mismatched
architecture. `tarfile` data filtering is required at extraction time.
Run recovered executables **only** from an authenticated, trusted restic
snapshot; SHA-256 checks inside an attacker-replaced manifest do not establish
upstream authenticity. Protect restic credentials outside both VPS systems.

Rollback is simply to **leave** `NASU_BUNDLE_OLLAMA_QWEN3_4B=0`, or stop using
v3 snapshots. The helper does not modify systemd, Ollama's model directory,
original SQLite files, existing Git branches or production settings. No v2
snapshot is overwritten. Do not run production enabling commands until the
owner separately approves the displayed exact diff and deployment plan.

## Evidence split

* **Synthetic**: the accompanying Python unit tests use fake manifest/blobs,
  fake runtime libraries and mock `unshare` outcomes. No live inference.
* **Same VPS**: restic upload, integrity checks and restore on the source
  server, only after explicit deployment approval. Not independent recovery.
* **Independent recovery**: encrypted offsite copy restored to a new machine,
  no internet, actual Qwen4B generation and reboot witnessed. Not yet done.
