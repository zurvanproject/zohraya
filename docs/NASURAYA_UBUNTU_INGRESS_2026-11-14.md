# Retained Windows workshop on Ubuntu

This installation preserves the authenticated `awake_workshop` archive and
creates a separate working copy. It links to the existing active Awake import;
it never replaces that database or discards Linux telemetry already recorded.

The original runtime and ingress sources are verified file-by-file against the
two pinned Git trees before every run. The exact session ID, 78 kg reference,
simulation backend, decoder, event chain, projections and 48-action budget must
match. The six evidence IDs for the retained revision must already exist in the
authoritative Awake database before preparation can succeed.

An original completed workshop is a completed goal, not a failed migration.
The public deterministic fixture finishes its four jobs at revision 9; a tenth
action raises `goal already reached`. The adapter recognizes that condition
from the retained state before calling the old loop. It records
`completed_awaiting_new_goal`, without replay, reset, artificial jobs or new
evidence. The installer leaves the timer off for an already completed goal.
Actual production completion still requires the live state receipt.

For an unfinished goal, one original offline step is permitted after the
original 3,300-second spacing. SQLite-consistent Awake/workshop backups are
made before and after. A committed source step interrupted before ingestion
recovers the same revision instead of performing another step. A process-death
safe SQLite lease serializes the adapter. This is local simulation continuity;
it does not establish physical sensing or activate the native body backend.

## Installation

From the reviewed pinned commit in `/opt/zohraya`, root runs
`bash tools/install_nasu_linux_ingress.sh`. The installer runs a synthetic
integration against the already staged public source trees, prepares as the
unprivileged service account, and runs one systemd invocation. Only unfinished
work enables the hourly timer. The systemd service denies network access,
model/API calls are absent, and old Windows tasks are unchanged.

`nasu-linux: ingress-status` reports counters, completion and last local run.
It does not expose private memory or accept shell commands. Existing
`nasu-linux: awake-status` remains the independent live Awake health check.

Rollback is `systemctl disable --now nasuraya-ingress.timer`; keep the original
archive, working copy and backups for review. Do not restore an older Awake DB
over the current one, re-enable the old Windows ingress, or rerun completed
96-cycle research as a rollback shortcut.

Moltbook credentials, social actions, paid model-worker activity and a new
research goal remain separate from this installation.
