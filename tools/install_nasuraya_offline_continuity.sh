#!/usr/bin/env bash
# One-time installation on the Ubuntu VPS as root.
# Offline heartbeat works without internet, GitHub, or paid APIs.
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then echo 'Run as root'; exit 1; fi
src=/opt/zohraya/tools/nasuraya_offline_continuity.py
bridge=/opt/zohraya/tools/nasuraya_linux_bridge.py
[[ -f "$src" && -f "$bridge" ]] || { echo 'Update /opt/zohraya first'; exit 1; }
id nasuraya >/dev/null
cd /opt/zohraya
python3 -m unittest discover -s tests -p test_nasuraya_offline_continuity.py -v
install -d -o root -g root -m 755 /usr/local/lib/nasuraya
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/continuity
install -o root -g root -m 755 "$src" /usr/local/lib/nasuraya/continuity.py
install -o root -g root -m 755 "$bridge" /usr/local/lib/nasuraya/bridge.py
python3 -m py_compile /usr/local/lib/nasuraya/continuity.py /usr/local/lib/nasuraya/bridge.py
cat > /etc/systemd/system/nasuraya-continuity.service <<'UNIT'
[Unit]
Description=Nasuraya offline continuity ledger and daily backup
After=local-fs.target

[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/continuity.py tick
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
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ReadWritePaths=/var/lib/nasuraya/continuity
MemoryMax=256M
CPUQuota=25%
UNIT
cat > /etc/systemd/system/nasuraya-continuity.timer <<'TIMER'
[Unit]
Description=Hourly offline Nasuraya continuity cycle
[Timer]
OnCalendar=hourly
Persistent=true
AccuracySec=60s
Unit=nasuraya-continuity.service
[Install]
WantedBy=timers.target
TIMER
systemctl daemon-reload
systemctl enable --now nasuraya-continuity.timer
systemctl start nasuraya-continuity.service
systemctl restart nasuraya-bridge.service
echo OFFLINE_CONTINUITY_INSTALLED
systemctl is-enabled nasuraya-continuity.timer
systemctl is-active nasuraya-continuity.timer
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/continuity.py verify
