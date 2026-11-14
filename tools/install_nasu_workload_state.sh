#!/usr/bin/env bash
# Install private archive import only; no runtime activation or credential reset.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Run as root'; exit 1; }
cd /opt/zohraya
id nasuraya >/dev/null
openssl version | python3 -c 'import sys; s=sys.stdin.read(); sys.exit(0 if s.startswith("OpenSSL 3.") else 1)'
python3 -m unittest discover -s tests -p test_nasu_workload_state.py -v
python3 -m unittest discover -s tests -p test_nasu_awake_health.py -v
python3 -m py_compile tools/nasu_workload_import.py tools/nasuraya_linux_bridge.py
for p in /var/lib/nasuraya /var/lib/nasuraya/workloads /var/lib/nasuraya/migration /var/lib/nasuraya/migration/recipient-private.pem /usr/local/lib/nasuraya /usr/local/lib/nasuraya/bridge.py /usr/local/lib/nasuraya/workload_import.py; do
    [[ ! -L "$p" ]] || { echo 'IMPORT_INSTALL=BLOCKED;CAUSE=SYMLINK'; exit 2; }
done
runuser -u nasuraya -- test -r /var/lib/nasuraya/migration/recipient-private.pem
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/workloads
bridge_backup=$(mktemp /usr/local/lib/nasuraya/bridge.before-state-import.XXXXXX)
cp -p /usr/local/lib/nasuraya/bridge.py "$bridge_backup"
install -o root -g root -m 755 tools/nasu_workload_import.py /usr/local/lib/nasuraya/workload_import.py
install -o root -g root -m 755 tools/nasuraya_linux_bridge.py /usr/local/lib/nasuraya/bridge.py
if ! systemctl restart nasuraya-bridge.service || ! systemctl is-active --quiet nasuraya-bridge.service; then
    install -o root -g root -m 755 "$bridge_backup" /usr/local/lib/nasuraya/bridge.py
    systemctl restart nasuraya-bridge.service
    echo 'IMPORT_BRIDGE=RESTORED;INSTALL=BLOCKED'
    exit 2
fi
echo 'WORKLOAD_IMPORT_TOOLS=INSTALLED;AWAKE=UNCHANGED;ACTIVATION=OFF'
result=0
runuser -u nasuraya -- env -i PATH=/usr/bin:/bin HOME=/var/lib/nasuraya LANG=C.UTF-8 \
    python3 /usr/local/lib/nasuraya/workload_import.py import-all || result=$?
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/workload_import.py status
exit "$result"
