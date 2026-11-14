#!/usr/bin/env bash
# Root-only one-time provisioning; routine Awake runs unprivileged and offline.
# This installs a gated hourly timer, without activating the imported memory.
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then echo "Run as root"; exit 1; fi
cd /opt/zohraya
[[ -f tools/nasu_awake_offline_runner.py && -f tools/nasu_awake_activate.py && -f tools/nasu_awake_health.py ]] || { echo 'Missing files; update reviewed source first'; exit 1; }
id nasuraya >/dev/null
python3 -m unittest discover -s tests -p test_nasu_awake_offline_runner.py -v
python3 -m unittest discover -s tests -p test_nasu_awake_health.py -v
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/var/lib/nasuraya/awake-control.json')
if p.is_symlink():
    raise SystemExit('INSTALL=BLOCKED;CAUSE=CONTROL_SYMLINK')
if p.exists() and json.loads(p.read_text()).get('enabled') is not False:
    raise SystemExit('INSTALL=BLOCKED;CAUSE=ACTIVE_OR_INVALID_GATE')
PY
install -d -o root -g root -m 755 /usr/local/lib/nasuraya
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/awake-backups
install -o root -g root -m 755 tools/nasu_awake_offline_runner.py /usr/local/lib/nasuraya/awake_runner.py
install -o root -g root -m 755 tools/nasu_awake_activate.py /usr/local/lib/nasuraya/awake_activate.py
install -o root -g root -m 755 tools/nasu_awake_health.py /usr/local/lib/nasuraya/awake_health.py
install -o root -g root -m 755 tools/nasuraya_linux_bridge.py /usr/local/lib/nasuraya/bridge.py
python3 -m py_compile /usr/local/lib/nasuraya/awake_runner.py /usr/local/lib/nasuraya/awake_activate.py /usr/local/lib/nasuraya/awake_health.py /usr/local/lib/nasuraya/bridge.py
cat >/etc/systemd/system/nasuraya-awake.service <<'UNIT'
[Unit]
Description=Nasuraya offline Tadash evidence/revision and hourly SQLite backup
After=local-fs.target nasuraya-continuity.service
Wants=nasuraya-continuity.service

[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/awake_runner.py
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
# SQLite mode=ro still needs WAL/SHM sidecars. The reader also sets query_only.
ReadWritePaths=/var/lib/nasuraya/awake-stage /var/lib/nasuraya/awake-backups /var/lib/nasuraya/migration/working /var/lib/nasuraya/continuity
MemoryMax=256M
CPUQuota=25%
TimeoutStartSec=120
UNIT
cat >/etc/systemd/system/nasuraya-awake.timer <<'UNIT'
[Unit]
Description=Hourly off-grid Tadash Awake continuity
[Timer]
OnCalendar=hourly
Persistent=true
AccuracySec=60s
Unit=nasuraya-awake.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now nasuraya-awake.timer
systemctl start nasuraya-awake.service
systemctl restart nasuraya-bridge.service
echo "OFFLINE_AWAKE_INSTALLED;GATE=STANDBY;WINDOWS_UNCHANGED"
systemctl is-active nasuraya-awake.timer
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/awake_runner.py
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/awake_health.py

