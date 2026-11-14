#!/usr/bin/env bash
# Resume only the existing simulated workshop, or retain its completed state.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Run as root'; exit 1; }
cd /opt/zohraya
id nasuraya >/dev/null
for p in /var/lib/nasuraya /var/lib/nasuraya/workloads /usr/local/lib/nasuraya \
    /usr/local/lib/nasuraya/linux_ingress.py /usr/local/lib/nasuraya/bridge.py \
    /etc/systemd/system/nasuraya-ingress.service /etc/systemd/system/nasuraya-ingress.timer; do
    [[ ! -L "$p" ]] || { echo 'INGRESS_INSTALL=BLOCKED;CAUSE=SYMLINK'; exit 2; }
done
for p in workload_sources.py workload_import.py workload_catalog.json; do
    [[ -f "/usr/local/lib/nasuraya/$p" && ! -L "/usr/local/lib/nasuraya/$p" ]]
done
NASU_INGRESS_SOURCES=/var/lib/nasuraya/workloads python3 -B -m unittest discover -s tests -p test_nasu_linux_ingress.py -v
systemctl stop nasuraya-ingress.timer 2>/dev/null || true
systemctl stop nasuraya-ingress.service 2>/dev/null || true
install -o root -g root -m 755 tools/nasu_linux_ingress.py /usr/local/lib/nasuraya/linux_ingress.py
runuser -u nasuraya -- env -i PATH=/usr/bin:/bin HOME=/var/lib/nasuraya LANG=C.UTF-8 \
    python3 -I -B /usr/local/lib/nasuraya/linux_ingress.py prepare
cat > /etc/systemd/system/nasuraya-ingress.service <<'UNIT'
[Unit]
Description=Continue retained Nasuraya simulated workshop on Ubuntu
After=local-fs.target

[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya
ExecStart=/usr/bin/python3 -I -B /usr/local/lib/nasuraya/linux_ingress.py run
Environment=HOME=/var/lib/nasuraya LANG=C.UTF-8
UMask=0077
TimeoutStartSec=120
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/nasuraya/workloads/ingress-live /var/lib/nasuraya/workloads/ingress-backups /var/lib/nasuraya/migration/working
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
CapabilityBoundingSet=
MemoryMax=512M
CPUQuota=25%
UNIT
cat > /etc/systemd/system/nasuraya-ingress.timer <<'UNIT'
[Unit]
Description=Hourly retained Nasuraya workshop continuation

[Timer]
OnCalendar=*-*-* *:20:00
Persistent=true
AccuracySec=60
Unit=nasuraya-ingress.service

[Install]
WantedBy=timers.target
UNIT
chmod 644 /etc/systemd/system/nasuraya-ingress.service /etc/systemd/system/nasuraya-ingress.timer
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/nasuraya-ingress.service /etc/systemd/system/nasuraya-ingress.timer
systemctl start nasuraya-ingress.service
# A completed original goal does not need an idle repeating timer. It remains
# resumable only through an explicitly designed new-goal migration later.
if runuser -u nasuraya -- python3 -c 'import json,sys; v=json.load(open("/var/lib/nasuraya/workloads/ingress-live/last-linux.json")); sys.exit(0 if v["goal"]["goal_reached"] else 1)'; then
    systemctl disable nasuraya-ingress.timer 2>/dev/null || true
    echo 'INGRESS=COMPLETED_RETAINED;TIMER=OFF;NEW_GOAL=REQUIRED'
else
    systemctl enable --now nasuraya-ingress.timer
    echo 'INGRESS=CONTINUING;TIMER=ENABLED'
fi
bridge_backup=$(mktemp /usr/local/lib/nasuraya/bridge.before-ingress.XXXXXX)
cp -p /usr/local/lib/nasuraya/bridge.py "$bridge_backup"
install -o root -g root -m 755 tools/nasuraya_linux_bridge.py /usr/local/lib/nasuraya/bridge.py
if ! systemctl restart nasuraya-bridge.service || ! systemctl is-active --quiet nasuraya-bridge.service; then
    install -o root -g root -m 755 "$bridge_backup" /usr/local/lib/nasuraya/bridge.py
    systemctl restart nasuraya-bridge.service
    echo 'INGRESS_BRIDGE=RESTORED;STATUS_COMMAND=UNAVAILABLE'
    exit 2
fi
runuser -u nasuraya -- python3 -I -B /usr/local/lib/nasuraya/linux_ingress.py status
echo 'AWAKE_DB=PRESERVED;WINDOWS=UNCHANGED;MODEL_CALLS=0;EXTERNAL_ACTIONS=0'
