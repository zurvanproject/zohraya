#!/usr/bin/env bash
# Provision source preservation and fixed status/stage commands; no workload activation.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Run as root'; exit 1; }
cd /opt/zohraya
id nasuraya >/dev/null
python3 -m unittest discover -s tests -p 'test_nasu_workload*.py' -v
python3 -m py_compile tools/nasu_workload_sources.py tools/nasuraya_linux_bridge.py
for p in /var/lib/nasuraya /var/lib/nasuraya/workloads /usr/local/lib/nasuraya; do
    [[ ! -L "$p" ]] || { echo 'INSTALL=BLOCKED;CAUSE=SYMLINK'; exit 2; }
done
for p in /usr/local/lib/nasuraya/bridge.py /usr/local/lib/nasuraya/workload_sources.py /usr/local/lib/nasuraya/workload_catalog.json; do
    [[ ! -L "$p" ]] || { echo 'INSTALL=BLOCKED;CAUSE=SYMLINK'; exit 2; }
done
bridge_backup=$(mktemp /usr/local/lib/nasuraya/bridge.before-workloads.XXXXXX)
cp -p /usr/local/lib/nasuraya/bridge.py "$bridge_backup"
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/workloads
install -o root -g root -m 755 tools/nasu_workload_sources.py /usr/local/lib/nasuraya/workload_sources.py
install -o root -g root -m 644 tools/nasu_workload_catalog.json /usr/local/lib/nasuraya/workload_catalog.json
install -o root -g root -m 755 tools/nasuraya_linux_bridge.py /usr/local/lib/nasuraya/bridge.py
python3 -m py_compile /usr/local/lib/nasuraya/workload_sources.py /usr/local/lib/nasuraya/bridge.py
if ! systemctl restart nasuraya-bridge.service || ! systemctl is-active --quiet nasuraya-bridge.service; then
    install -o root -g root -m 755 "$bridge_backup" /usr/local/lib/nasuraya/bridge.py
    systemctl restart nasuraya-bridge.service
    echo 'WORKLOAD_BRIDGE=RESTORED;INSTALL=BLOCKED'
    exit 2
fi
echo 'WORKLOAD_TOOLS=INSTALLED;AWAKE=UNCHANGED;AUTOSTART=OFF'
result=0
runuser -u nasuraya -- env -i PATH=/usr/bin:/bin HOME=/var/lib/nasuraya LANG=C.UTF-8 \
    python3 /usr/local/lib/nasuraya/workload_sources.py stage-all || result=$?
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/workload_sources.py status
exit "$result"
