#!/usr/bin/env bash
# Admin-gated installation: NEVER reachable via unrestricted bridge commands.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'INSTALL_BLOCKED: ROOT_REQUIRED'; exit 2; }
cd /opt/zohraya
[[ -f tools/nasu_frontier_lab.py ]] || { echo 'INSTALL_BLOCKED: SOURCE_MISSING'; exit 2; }
id nasuraya >/dev/null
python3 -B -m unittest discover -s tests -p test_nasu_frontier_lab.py -q
install -d -o root -g root -m 755 /usr/local/lib/nasuraya
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/frontier-lab
TARGET=/usr/local/lib/nasuraya/nasu_frontier_lab.py
if [[ -e "$TARGET" ]]; then
  cmp -s tools/nasu_frontier_lab.py "$TARGET" || { echo 'INSTALL_BLOCKED: INSTALLED_VERSION_DIFFERS'; exit 3; }
else
  install -o root -g root -m 755 tools/nasu_frontier_lab.py "$TARGET"
fi
SERVICE=/etc/systemd/system/nasuraya-frontier-lab.service
TIMER=/etc/systemd/system/nasuraya-frontier-lab.timer
[[ ! -e "$SERVICE" && ! -e "$TIMER" ]] || { echo 'INSTALL_BLOCKED: UNIT_ALREADY_EXISTS'; exit 3; }
cat >"$SERVICE" <<'UNIT'
[Unit]
Description=Nasuraya bounded offline evidence frontier (not self-modifying)
After=local-fs.target ollama.service
[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya/frontier-lab
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/nasu_frontier_lab.py run
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET
IPAddressDeny=any
IPAddressAllow=localhost
ReadWritePaths=/var/lib/nasuraya/frontier-lab
MemoryMax=384M
CPUQuota=50%
TimeoutStartSec=90
UNIT
cat >"$TIMER" <<'UNIT'
[Unit]
Description=Once-daily budgeted frontier inquiry in hourly checks
[Timer]
OnCalendar=hourly
Persistent=true
Unit=nasuraya-frontier-lab.service
[Install]
WantedBy=timers.target
UNIT
chmod 644 "$SERVICE" "$TIMER"
systemctl daemon-reload
systemctl enable --now nasuraya-frontier-lab.timer
echo 'FRONTIER_TIMER=ENABLED;NO_AWAKE_WRITES;QWEN_LOCAL_ONLY;NO_NETWORK_EXTERNAL'
