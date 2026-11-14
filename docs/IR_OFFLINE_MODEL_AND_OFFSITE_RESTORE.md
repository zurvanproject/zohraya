# Iran VPS offline readiness: local model and independent restore (draft)

Status: **NOT DEPLOYED**. Manual tools only. This PR must not be equated with completion of the three resilience gates. No production Awake database, timer, or Windows process is altered by the scripts.

## 1. CPU-only offline model preflight

Target: Ubuntu 24.04, about 8 vCPU / 15 GiB RAM / 138 GiB disk available. Run as root in a reviewed console, while international networking still exists:

```bash
cd /opt/zohraya
bash tools/nasu_install_local_llm.sh
```

Installer builds `llama-cli` from ggml-org/llama.cpp and downloads **official** `Qwen/Qwen3-1.7B-GGUF` Q8_0 (Apache-2.0), then records model SHA-256, source SHA, and a smoke-test result under `/opt/nasuraya-local-llm/`. No persistent inference service is enabled; no model is connected to Awake. A model downloaded today is not yet an independent reasoning agent. Before claiming offline operation, pin versions, archive dependencies, benchmark a fixed test set, prevent network egress, reboot, and confirm text output with no external API.

Sources: https://huggingface.co/Qwen/Qwen3-1.7B-GGUF and https://github.com/ggml-org/llama.cpp.

## 2. Independent encrypted restore test

Prepare a restic repository on **independently administered storage**, ideally reachable during domestic-only connectivity, and provision the encryption password outside *both* VPS machines. Do **not** commit credentials, recovery keys or sensitive state to GitHub. Example environment variable names only:

```bash
export RESTIC_REPOSITORY='sftp:BACKUP_USER@INDEPENDENT_HOST:/nasu-repo'
export RESTIC_PASSWORD_FILE='/root/.config/nasuraya/restic-password'
# Authenticate with a narrowly scoped SSH key installed directly on the host.
restic init  # once, after the new remote repository has been configured
bash tools/nasu_offsite_restore_drill.sh
```

The drill creates SQLite-consistent copies of the current Awake and continuity databases, encrypts/uploads them with restic, restores the **specific** returned snapshot to an isolated temporary path, and checks byte-for-byte SHA-256 and SQLite integrity. Its success is a **same-machine remote round-trip**, not yet disaster recovery. Perform another restore on a fresh machine with only the independently stored password and backup-access key; document the successful receipt. The remote URI syntax check does **not** prove geographical or administrative independence.

Restic reference: https://restic.readthedocs.io/

## 3. Subscription

The user-visible Mobinhost payment receipt dated 2026-11-14 confirms a paid **six-month** MacroServer/IR/16GB Ubuntu 24.04 service through **2027-05-13** with a total-period allocation of **3 TB traffic**. No private invoice number, payment transaction details, password or server IP should be put in this public repository. There is no evidence of automatic renewal or guaranteed provider uptime. Plan the renewal before expiry.

## Acceptance gates

- PASS means model is installed on the **Iran Ubuntu**, actual CPU generation test succeeds under restricted external egress, and a restart can repeat the test without downloads.
- PASS means encrypted independent backup is created and successfully restored on a physically / administratively independent machine from out-of-band recovery credentials.
- PASS means Awake + fixed bounded local research queue + model fallback run across reboot without global DNS, GitHub, ChatGPT, or paid APIs. Preserve the sole-writer rule and do not replay already completed workshop tasks.

Until those are witnessed, Issue #233 remains **open/blocked**, regardless of CI unit-test success.
