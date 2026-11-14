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


## 4. Staged independent research queue (NOT YET DEPLOYED)

The draft tools/nasu_offline_research_queue.py uses a local, verified Qwen3-1.7B GGUF and llama-cli only. It has 26 fixed questions (docs/nasuraya_offline_research_seeds_v1.json), processes at most one every six days, stores SQLite-durable notes tagged UNVERIFIED_DRAFT, and has a tamper-evident chain and bounded retries. It never writes to Awake, executes model text as commands, accesses an external network, invents physical observations, or escalates permissions. If no model is installed, the research queue records NO new note; Awake/continuity can continue independently. A root-run tools/install_nasu_offline_research.sh provisions an unprivileged, network-denied weekly systemd timer only after a real local model SHA and CPU smoke test have passed. This installer has not been run on the Iran host.

## 5. Complete protected backup and scheduled recovery (NOT YET DEPLOYED)

The expanded manual restic script backs up live Awake/continuity SQLite snapshots, the optional research SQLite journal, a Git bundle, verified inactive imported Windows workload archives, plus the exact official Qwen model file and llama.cpp CPU runtime binaries when installed. All bytes receive SHA-256 hashes in the private manifest. Secrets and private keys are NOT included.

The optional tools/install_nasu_offsite_backup_timer.sh accepts only a root:root mode-0600 /etc/nasuraya/offsite.env file with a real independent RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE (plus AWS S3 credential environment variables if using S3). It requires restic initialization and performs a full upload/restoration check before enabling two local timers: a lightweight encrypted daily snapshot and a weekly remote round-trip restore/hash test. It leaves timers disabled on failed initialization. An external Restic repository URL alone DOES NOT prove a different datacenter, administration or billing period.

One candidate for an independently operated Iranian S3 bucket is Sakoo Cloud, with its published S3 endpoint https://s3.abrstorage.ir and region ir-thr-1 (source: https://sakoocloud.ir/object-storage/). Before using it, independently establish datacenter separation from Mobinhost, domestic-only network reachability, provider availability and prepaid funding that covers the outage window. No bucket has been created or purchased by this PR.

**Fresh-machine recovery remains mandatory.** On a different machine, decrypt a selected snapshot with separately retained keys and run the zero-network tools/nasu_verify_restored_snapshot.py against the restored snapshot directory. It independently checks hashes, SQLite integrity, the Git bundle, archive paths and model/runtime pair. Store the actual recovery receipt outside both VPS systems. A successful CI synthetic fixture or same-machine round trip is NOT equivalent to this test.

Restoring data is also not proof that all runtime OS dependencies are present; test a real local inference cycle on the recovered host with international network disabled. Keep offline package bundles, model and binary dependencies before any outage.

## 6. Real outstanding gates and billing

The confirmed Mobinhost prepaid term is 2026-11-14 through 2027-05-13, with 3 TB total period traffic. It does not guarantee continued service or an extra six months starting on a future outage date. The backup-provider subscription must likewise be prepaid or funded for the necessary period.

Current claims: synthetic tests may be green; actual Ubuntu local-model installation, network-denied generation/reboot, independent storage provisioning, independent-host decrypt/restore, and multi-day staging outage drill are still pending. Do not close Issue #233 or turn this draft PR into a production deployment based solely on CI results.
