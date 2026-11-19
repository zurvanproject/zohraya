#!/usr/bin/env bash
# One-time, explicit owner-console installation. Does not alter existing Awake,
# GitHub Bridge, Qwen weights, cognitive-growth, backup or production journals.
set -Eeuo pipefail
[[ "$(id -u)" -eq 0 ]] || { echo 'BLOCKED: ROOT_REQUIRED' >&2; exit 2; }
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo 'usage: sudo bash install_nasu_zurvan_world_lab.sh <40-hex-commit>' >&2; exit 2; }
PIN="$1"
REPO=/opt/zohraya
SRC=/usr/local/lib/nasuraya/nasu_zurvan_world_lab.py
DATA=/var/lib/nasuraya/zurvan-world-lab
SERVICE=/etc/systemd/system/nasuraya-zurvan-world-lab.service
TIMER=/etc/systemd/system/nasuraya-zurvan-world-lab.timer
command -v git >/dev/null
command -v python3 >/dev/null
command -v ollama >/dev/null
id nasuraya >/dev/null
[[ -d "$REPO/.git" ]] || { echo 'BLOCKED: REPO_MISSING' >&2; exit 3; }
git -C "$REPO" cat-file -e "$PIN^{commit}"
ollama list | grep -q '^qwen3:4b-instruct ' || { echo 'BLOCKED: PINNED_LOCAL_MODEL_MISSING' >&2; exit 3; }
for p in "$SRC" "$SERVICE" "$TIMER"; do
    [[ ! -e "$p" && ! -L "$p" ]] || { echo "BLOCKED: ALREADY_EXISTS: $p" >&2; exit 3; }
done
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tools" "$TMP/tests"
git -C "$REPO" show "$PIN:tools/nasu_zurvan_world_lab.py" >"$TMP/tools/nasu_zurvan_world_lab.py"
git -C "$REPO" show "$PIN:tests/test_nasu_zurvan_world_lab.py" >"$TMP/tests/test_nasu_zurvan_world_lab.py"
python3 -B -m py_compile "$TMP/tools/nasu_zurvan_world_lab.py" "$TMP/tests/test_nasu_zurvan_world_lab.py"
(cd "$TMP" && python3 -B -m unittest discover -s tests -p test_nasu_zurvan_world_lab.py -q)
install -d -o root -g root -m 0755 /usr/local/lib/nasuraya
install -d -o nasuraya -g nasuraya -m 0700 "$DATA"
install -o root -g root -m 0644 "$TMP/tools/nasu_zurvan_world_lab.py" "$SRC"
cat >"$SERVICE" <<'UNIT'
[Unit]
Description=Nasuraya Tadash Zurvan world reflection (isolated local Qwen)
After=local-fs.target ollama.service
Wants=ollama.service
[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya/zurvan-world-lab
Environment=NASU_ZURVAN_STATE=/var/lib/nasuraya/zurvan-world-lab/lab.sqlite3
Environment=HOME=/var/lib/nasuraya/zurvan-world-lab
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 -B /usr/local/lib/nasuraya/nasu_zurvan_world_lab.py run-local
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET
IPAddressDeny=any
IPAddressAllow=localhost
ReadWritePaths=/var/lib/nasuraya/zurvan-world-lab
MemoryMax=512M
CPUQuota=100%
TimeoutStartSec=540
UNIT
cat >"$TIMER" <<'UNIT'
[Unit]
Description=Daily bounded three-pass Zurvan reflection (UTC 03:15)
[Timer]
OnCalendar=*-*-* 03:15:00 UTC
Persistent=true
Unit=nasuraya-zurvan-world-lab.service
[Install]
WantedBy=timers.target
UNIT
chmod 0644 "$SERVICE" "$TIMER"
systemctl daemon-reload
systemctl enable --now nasuraya-zurvan-world-lab.timer
echo "ZURVAN_INSTALL=READY; TIMER=ENABLED; FIRST_RUN=MANUAL; MODEL=LOCAL_QWEN_4B; PIN=$PIN"
echo "To run once: systemctl start nasuraya-zurvan-world-lab.service"
