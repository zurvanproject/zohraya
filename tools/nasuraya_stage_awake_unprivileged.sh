#!/usr/bin/env bash
# Offline Tadash Awake stage; runs as unprivileged nasuraya account.
# Does NOT overwrite or replace Windows state or enable duplicate schedulers.
set -Eeuo pipefail
[[ "$(id -un)" == nasuraya ]] || { echo 'Requires nasuraya service user'; exit 1; }
pin=90692bde9f1e4b5b7f311162b7c83127715df710
src=/var/lib/nasuraya/awake-src
state=/var/lib/nasuraya/awake-stage
if [[ -e "$src" && ! -d "$src/.git" ]]; then echo 'Source path occupied'; exit 1; fi
if [[ ! -d "$src/.git" ]]; then
    git clone --depth 1 --single-branch --branch feature/tadash-awake-continuity-v01-20261113 \
      https://github.com/zurvanproject/zohraya.git "$src"
fi
current=$(git -C "$src" rev-parse HEAD)
if [[ "$current" != "$pin" ]]; then
    git -C "$src" fetch --depth 1 origin "$pin"
    git -C "$src" checkout --detach "$pin"
fi
actual=$(git -C "$src" rev-parse HEAD)
[[ "$actual" == "$pin" ]] || { echo "Pinned source mismatch: $actual"; exit 1; }
cd "$src"
python3 -m unittest tadash_awake.test_wake tadash_awake.test_bridge -q
if [[ ! -e "$state/awake.sqlite3" ]]; then
    python3 -m tadash_awake init --root "$state"
fi
python3 -m tadash_awake status --root "$state"
echo 'AWAKE_STAGE_READY; ORIGINAL_WINDOWS_STATE_NOT_MIGRATED; NO_DUPLICATE_TICKS'

# One-time migration recipient key; never prints or uploads private key.
python3 /var/lib/nasuraya/zohraya/tools/nasu_migration_recipient_key.py
