# Nasuraya autonomous offline missions, v1 (opt-in)

This is **actual scheduled work** on the owner's Ubuntu VPS after one explicit installation. It is not a copy of ChatGPT, cannot modify its own code, and does not execute Qwen-generated shell commands.

## What runs once each UTC day (05:17)
1. Read local scalar server telemetry and **only counts** in the existing Awake SQLite database. Do not read the text of questions, patients, tokens or private files.
2. Verify the already-installed pinned, source-checked Setar v0.5 checkout. Run its short offline regression suite. Evaluate the inherited synthetic skill checkpoint, run **three accelerated 10-second practice episodes**, evaluate again, verify WAV/checkpoint hashes and retain the learned checkpoint for the next day. This is simulated audio practice and **not** physical finger/body control or 30 seconds of wall-clock practice.
3. Ask the locally installed `qwen3:4b` via the existing private Ollama and Persian structured reporter for a three-stage reflection about measurable facts. The text is stored as data, not followed as commands. A missing or malformed Qwen answer does not discard a completed audio lesson.
4. Make a **SQLite-consistent local copy** of the Qwen report journal and verify its integrity. This is a same-VPS convenience backup, **not** independent disaster recovery.

The runner writes solely under `/var/lib/nasuraya/autonomous-lab/`, with a daily SQLite ledger, WAV, checkpoint and JSON report. The original Awake, the previous focus exercise, the primary Qwen journal, Linux Bridge, and every existing timer remain unchanged. A day is reserved before effects; duplicate invocation on the same day does not repeat training. If a practice run is interrupted, its progress is not claimed as completed and is not inherited. Running without a new day does not automatically retry failed work.

It accepts only the preexisting reviewed source SHA `ecf003bbce8805a1a20d0b4502f2c04d7cdbbd5e` from the owner's existing `focus-*/repo` checkout, with `venv/bin/python`, plus the prior completed focus checkpoint. If the source isn't present or is dirty, that day's practice fails rather than installing unknown dependencies or fetching code. No new network traffic is needed after initial provisioning except the **localhost** Ollama API.

## Root install after verifying the pinned SHA-256
This script creates a new, distinct rootless systemd service/timer, schedules it daily at 05:17 UTC and starts one job immediately. Run in tmux and wait for `MISSIONS_INSTALL=OK`.

```sh
cd /tmp
curl -fL --retry 3 -o nasu_offline_missions.py https://raw.githubusercontent.com/zurvanproject/zohraya/b5297ad9e82ce8f344d4852da7c0cb547a6b6a2b/tools/nasu_offline_missions.py
echo "4dc38346ec79aaadd793ce83e3db41012b4cf1b52b94b553a5bae17f9300c9ea  nasu_offline_missions.py" | sha256sum -c - && python3 nasu_offline_missions.py install
```

Inspect with:
```sh
systemctl is-active nasuraya-offline-missions.timer
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/nasu_offline_missions.py status
systemctl status nasuraya-offline-missions.service --no-pager
```

A completed day appears as `completed` or `completed_without_qwen`; a failed or interrupted day is distinguishable. Logs live at `/var/lib/nasuraya/autonomous-lab/YYYY-MM-DD/result.json`. No Slack, email or ChatGPT message is generated when international internet is down.

To stop **only this new routine**, use:
```sh
systemctl disable --now nasuraya-offline-missions.timer
```
Do not delete historical mission output or alter Awake cutover flags. The existing six-hour local Qwen reporting timer continues independently.

## Verification
`python3 -m unittest discover -s tests -p test_nasu_offline_missions.py -v` exercises 9 contracts with mocks and a real temporary SQLite database. It is not proof the real VPS ran; the post-install service receipt and stored output must be checked separately. No claim of model-weight training, genuine musical skill or historical Daoist ritual mastery.
