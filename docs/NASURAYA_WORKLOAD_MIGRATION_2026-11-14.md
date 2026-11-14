# Windows to Ubuntu workload migration — 2026-11-14

The Awake memory cutover is verified separately from this source-preservation
package. Copying public code does not migrate private databases, credentials,
scheduled tasks, installed dependencies, or completed experiment results.

## Verified operational evidence

- Windows Awake and Ingress freeze, 11:06:50 UTC:
  https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6876355304
- Encrypted final snapshot exported with 54 events, 6 questions, 25 ticks,
  24 ledger records. Export ID `e6f89362ebd54b1e80323e2b918049d7`:
  https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6876367751
- Ubuntu import:
  https://github.com/zurvanproject/zohraya/issues/212#issuecomment-6876377020
- Ubuntu repair and first successful active systemd run were observed locally
  at 11:37:50 UTC; a matched Bridge status at 11:39 confirms 57 events,
  7 questions, 26 ticks, 27 ledger records, gate enabled, timer active,
  boot enabled, last service result success:
  https://github.com/zurvanproject/zohraya/issues/212#issuecomment-6876709162
- The 12:01:25 UTC status advances to 57 events, 8 questions, 27 ticks,
  28 ledger records, with the same healthy scheduler/service flags:
  https://github.com/zurvanproject/zohraya/issues/212#issuecomment-6876955906
  This establishes a subsequent completed cycle. This receipt alone does not
  identify the trigger of that cycle.

Fresh Windows status and inventory requests have not returned receipts at
the time of this document. The last observed freeze is historical evidence,
not a fresh proof of the current Windows task states. Inventory request:
https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6876939706

## Components and next steps

| Component | This package | Still required before claiming transfer complete |
| --- | --- | --- |
| Shared 78 kg body / DIOS runtime | Preserve exact public source | Export/import original workshop session and validate continuity |
| Awake synthetic ingress | Preserve exact public source | Preserve source identity and session; then port scheduler without duplicating observations |
| Moltbook gateway | Preserve exact public source | Export local social history; provision a working Linux credential; validate read-only access |
| Public discussion memory | Preserve exact public source | Import original episode database and anchor |
| Whole-body atlas | Preserve exact public source | Transfer original results; physics remains unverified |
| Completed 96-cycle study | Preserve exact public source | Archive original results and state; do not replay completed study |
| Rolyel dependency | Preserve exact public source | Associate source with archived study results |
| Legacy 195 kg Tadash runtime | Historical source archive | Preserve old state as history; never substitute it for the current 78 kg model |
| Model worker | Preserve Windows bundle source | Export private job/state archive, port Windows-specific code and credential handling; do not replay completed goals |
| Windows Bridge v2 | Historical source archive | Preserve transport journal locally; Ubuntu already has a separate Bridge |

Windows DPAPI-encrypted key files do not become usable Linux credentials by
being copied. No keys, private memory text, inbox contents, or DB rows are
published by the inventory or source-staging commands. Windows binaries and
desktop URL shortcuts are not Linux model installations. FFmpeg must be
provisioned and tested separately if that workload is needed on Ubuntu.

## Ubuntu installation

Use a clean `/opt/zohraya` checkout, fast-forward to the reviewed exact commit
on `feature/ubuntu-workload-migration-20261114`, verify HEAD, then run as root:

```sh
bash tools/install_nasu_workloads.sh
```

This installs a root-owned source verifier/catalog, adds two fixed Bridge
commands, preserves a copy of the previous Bridge program, and restarts only
`nasuraya-bridge.service`. It stages public source under
`/var/lib/nasuraya/workloads/sources` as the unprivileged `nasuraya` user.
It leaves the working Awake state, gate, timer, and Windows tasks unchanged.
No new workload is activated. Every file must match its pinned Git blob and
tree; incomplete downloads and modified existing directories fail closed.

The ten immutable source snapshots total approximately 57.5 MB unpacked.
This is the repository content at each historical commit, including the
component's supporting files, rather than ten newly running applications.

After installation, the existing owner-only Ubuntu issue relay supports:

```text
nasu-linux: workload-status
nasu-linux: workload-stage
```

`workload-stage` verifies already preserved components and stages at most one
new component. `workload-status` rechecks the actual files. Neither starts a
model, a social action, or an experiment. Source receipt timestamps and
manifests remain local. Interrupted staging locks require inspection instead
of being silently removed.

## Windows reconnection

`tools/nasu_migration_bridge_recovery.ps1` defaults to inspection. With
`-RecoverIfSafe`, its only change is starting the existing `NasurayaBridge`
scheduled task when it is Ready and no Bridge process is alive. It checks the
original pinned agent, intact journal anchor, task wrapper, complete public
queue, and exact identities of the three pending migration read/inventory
requests. Unexpected unseen requests block recovery. It does not clear the
journal, replay a started job, edit code/tasks, or enable Awake/Ingress.

If the Bridge process is already alive or the task is not Ready, the script
reports the blocker for investigation; it does not kill processes. Running
this script still requires access to the Windows desktop. No direct remote
shell is available from the current workspace.

## Validation and limits

Unit tests cover metadata-only inventory, traversal/symlink rejection, exact
blob verification, partial download failure, existing-source preservation,
and distinct source/runtime statuses. CI also checks Bash/Python syntax and
parses the PowerShell recovery without executing it. These checks do not
prove production installation or Windows task recovery. Only subsequent
matched server receipts can establish those outcomes.
