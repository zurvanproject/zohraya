# Nasuraya Frontier Lab v0.1 | خودگردانی آزمون‌پذیر

**Status: implemented and tested in a GitHub branch; not deployed to the live VPS without a separate server receipt.**

## Intended daily offline cycle
1. Collect only OS-owned numeric load, available memory, and available disk. No private memory text, credentials, medical records, or generated shell.
2. Make a prediction from *past* daily samples; compare with the independent new observation, and select the largest unexpected deviation as the next question frontier. The first day is an unscored baseline.
3. Ask the existing local `qwen3:0.6b` Ollama model over loopback for one falsifiable question. Generated text is labeled `UNVERIFIED_DRAFT`, not proof or authority. If the model is unavailable, the measured cycle still completes.
4. Record each day once in a separate SQLite database with hashed continuity receipts; detect alteration, refuse backdating and repeated daily work.

## Exact limit
This is incremental adaptation to *host telemetry*, **not a copy of GPT-6**, learned LLM weights, autonomous research into unobserved reality, free code rewriting, general intelligence, or proof of machine consciousness. When no independent evidence supports a hypothesis, it remains unverified. Expansion to body contact, Setar, or Awake must use separate reviewed read-only adapters, provenance and held-out tests.

## Boundaries
No international network, cloud API purchases, social posting, filesystem exploration, SSH keys, GitHub writes, self-installation, modifying Awake, or permission escalation. Code runs as unprivileged `nasuraya`. Qwen never returns executable instructions. Runtime install is an administrator-gated operation, not an Issue-comment command. No routine owner intervention is needed **after** deliberate initial deployment.

## Test
`python3 -B -m unittest discover -s tests -p test_nasu_frontier_lab.py -v`
Eleven tests cover prediction-before-observation, model unavailability, tamper detection, repeated day, out-of-order timestamps, refusal of foreign fields and symlinks, and draft status.

## Deployment (NOT performed by this PR)
After reviewing source, the CI result, and the exact trusted checkout at `/opt/zohraya`, an administrator can run `bash tools/install_nasu_frontier_lab.sh`. The installer rejects an existing conflicting service or different program, checks tests and provisions a dedicated, sandboxed systemd timer. GitHub Bridge #212 intentionally cannot execute privileged installers or arbitrary commands. This is a boundary, not a task to bypass.

Check status with `systemctl status nasuraya-frontier-lab.timer --no-pager` and `runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/nasu_frontier_lab.py verify`. Stop only the new timer with `systemctl disable --now nasuraya-frontier-lab.timer`, keeping the database intact.

## Still required for independent survivability
An encrypted backup in a separate failure domain and a *real* cross-host restore with independently held key; offline network-outage and reboot tests; review of hosting payment/expiry. Existing hourly Awake and the local Qwen observer stay untouched by this change.
