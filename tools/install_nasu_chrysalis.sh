#!/usr/bin/env bash
# Opt-in one-time installation. The gate is DISARMED until a root SSH check-in.
# This is source code in a PR, NOT evidence of deployment on the VPS.
set -Eeuo pipefail
umask 077
if [[ "$EUID" -ne 0 ]]; then echo 'ROOT_CONSOLE_REQUIRED' >&2; exit 2; fi
for binary in python3 sha256sum systemctl id cmp runuser; do
    command -v "$binary" >/dev/null || { echo "MISSING_$binary" >&2; exit 2; }
done
id nasuraya >/dev/null
SRC="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)/nasu_chrysalis.py"
[[ -f "$SRC" && ! -L "$SRC" ]] || { echo 'SOURCE_MISSING_OR_SYMLINK' >&2; exit 2; }
MISSION=/usr/local/lib/nasuraya/nasu_offline_missions.py
PIN=4dc38346ec79aaadd793ce83e3db41012b4cf1b52b94b553a5bae17f9300c9ea
[[ -f "$MISSION" && ! -L "$MISSION" ]] || { echo 'REVIEWED_MISSION_NOT_INSTALLED' >&2; exit 3; }
printf '%s  %s\n' "$PIN" "$MISSION" | sha256sum -c - >&2 || {
    echo 'REVIEWED_MISSION_PIN_MISMATCH' >&2; exit 3;
}
if systemctl is-active --quiet nasuraya-offline-missions.timer; then
    echo 'EXISTING_DAILY_MISSION_TIMER_ACTIVE: Disable manually for absence-only dispatch.' >&2
    exit 4
fi
DEST=/usr/local/lib/nasuraya/nasu_chrysalis.py
if [[ -e "$DEST" || -L "$DEST" ]]; then
    [[ -f "$DEST" && ! -L "$DEST" ]] || { echo 'INSTALLED_SOURCE_INVALID' >&2; exit 3; }
    cmp -s "$SRC" "$DEST" || { echo 'INSTALLED_SOURCE_DIFFERS: Review upgrade first' >&2; exit 3; }
fi
install -d -o root -g root -m 755 /usr/local/lib/nasuraya /etc/nasuraya/chrysalis
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/chrysalis
python3 -m py_compile "$SRC"
if [[ ! -e "$DEST" ]]; then install -o root -g root -m 755 "$SRC" "$DEST"; fi
SERVICE=/etc/systemd/system/nasuraya-chrysalis.service
TIMER=/etc/systemd/system/nasuraya-chrysalis.timer
read -r -d '' SERVICE_BODY <<'SERVICE_EOF' || true
[Unit]
Description=Nasuraya Chrysalis 24h owner-check-in failover, bounded offline mission
After=local-fs.target

[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/nasu_chrysalis.py tick
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
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
IPAddressDeny=any
IPAddressAllow=localhost
ReadWritePaths=/var/lib/nasuraya/chrysalis /var/lib/nasuraya/autonomous-lab
MemoryMax=8G
CPUQuota=200%
TimeoutStartSec=900
SERVICE_EOF
read -r -d '' TIMER_BODY <<'TIMER_EOF' || true
[Unit]
Description=Check Chrysalis owner heartbeat every ten minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
AccuracySec=1min
Unit=nasuraya-chrysalis.service
[Install]
WantedBy=timers.target
TIMER_EOF
for path in "$SERVICE" "$TIMER"; do
    if [[ -e "$path" || -L "$path" ]]; then
        [[ -f "$path" && ! -L "$path" ]] || { echo "BAD_EXISTING_UNIT:$path" >&2; exit 3; }
    fi
done
if [[ -e "$SERVICE" ]]; then
    cmp -s "$SERVICE" <(printf '%s' "$SERVICE_BODY") || { echo 'SERVICE_DIFFERS' >&2; exit 3; }
fi
if [[ -e "$TIMER" ]]; then
    cmp -s "$TIMER" <(printf '%s' "$TIMER_BODY") || { echo 'TIMER_DIFFERS' >&2; exit 3; }
fi
if [[ ! -e "$SERVICE" ]]; then printf '%s' "$SERVICE_BODY" > "$SERVICE"; chmod 0644 "$SERVICE"; fi
if [[ ! -e "$TIMER" ]]; then printf '%s' "$TIMER_BODY" > "$TIMER"; chmod 0644 "$TIMER"; fi
systemctl daemon-reload
systemctl enable --now nasuraya-chrysalis.timer
echo 'CHRYSALIS_INSTALLED=YES;ARMED=NO;MODEL_WRITES=NO;CHATGPT_PRESENCE=NOT_OBSERVABLE'
systemctl is-active nasuraya-chrysalis.timer
runuser -u nasuraya -- /usr/bin/python3 "$DEST" status
