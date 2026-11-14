#!/usr/bin/env bash
# Stage the pinned Tadash Awake source on Ubuntu without changing the Windows host.
# Requires a previously provisioned 'nasuraya' service account.
set -Eeuo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run this installer as root"; exit 1
fi
id nasuraya >/dev/null
PIN="90692bde9f1e4b5b7f311162b7c83127715df710"
BRANCH="feature/tadash-awake-continuity-v01-20261113"
SRC="/var/lib/nasuraya/awake-src"
STATE="/var/lib/nasuraya/awake-stage"

if [[ -e "$SRC" && ! -d "$SRC/.git" ]]; then
  echo "Refusing to overwrite existing non-git source $SRC"; exit 1
fi
if [[ ! -d "$SRC/.git" ]]; then
  runuser -u nasuraya -- git clone --depth 1 --single-branch --branch "$BRANCH" https://github.com/zurvanproject/zohraya.git "$SRC"
fi
ACTUAL="$(runuser -u nasuraya -- git -C "$SRC" rev-parse HEAD)"
if [[ "$ACTUAL" != "$PIN" ]]; then
  echo "Unexpected source version: $ACTUAL. Expected $PIN. Not installing."; exit 1
fi

runuser -u nasuraya -- bash -c 'cd "$1"; exec python3 -m unittest tadash_awake.test_wake tadash_awake.test_bridge -v' bash "$SRC"

if [[ ! -d "$STATE" ]]; then
  install -d -o nasuraya -g nasuraya -m 700 "$STATE"
  runuser -u nasuraya -- bash -c 'cd "$1"; exec python3 -m tadash_awake init --root "$2"' bash "$SRC" "$STATE"
fi
runuser -u nasuraya -- bash -c 'cd "$1"; exec python3 -m tadash_awake status --root "$2"' bash "$SRC" "$STATE"
echo "AWAKE_STAGED: code pinned and tests passed. Staging state is separate and paused."
echo "WINDOWS_STATE: NOT_TRANSFERRED. Windows host remains authoritative."
echo "Next step: export original Awake SQLite safely, import and verify counts/checkpoint, then cut over scheduler."
