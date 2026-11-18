#!/usr/bin/env bash
# One-time operator-gated installation. Never alters existing Awake or missions.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'BLOCKED: ROOT_REQUIRED' >&2; exit 2; }
cd /opt/zohraya
test -f tools/nasu_autonomous_cognition.py
test -f tests/test_nasu_autonomous_cognition.py
id nasuraya >/dev/null
command -v ollama >/dev/null
ollama list | grep -q '^qwen3:4b-instruct ' || {
  echo 'BLOCKED: LOCAL_QWEN_4B_INSTRUCT_MISSING' >&2; exit 3;
}
python3 -B -m unittest discover -s tests -p test_nasu_autonomous_cognition.py -v
BASE=/usr/local/lib/nasuraya
DATA=/var/lib/nasuraya/cognitive-growth
BIN="$BASE/nasu_autonomous_cognition.py"
SERVICE=/etc/systemd/system/nasuraya-cognitive-growth.service
TIMER=/etc/systemd/system/nasuraya-cognitive-growth.timer
[[ ! -e "$SERVICE" && ! -e "$TIMER" ]] || {
  echo 'BLOCKED: UNEXPECTED_EXISTING_UNIT' >&2; exit 3;
}
[[ ! -e "$BIN" ]] || {
  cmp -s tools/nasu_autonomous_cognition.py "$BIN" || {
    echo 'BLOCKED: INSTALLED_SOURCE_DIFFERS' >&2; exit 3;
  }
}
install -d -o root -g root -m 755 "$BASE"
install -d -o nasuraya -g nasuraya -m 700 "$DATA"
install -o root -g root -m 644 tools/nasu_autonomous_cognition.py "$BIN"
cat >"$SERVICE" <<'UNIT'
[Unit]
Description=Nasuraya bounded offline cognitive growth (local Qwen 4B)
After=local-fs.target ollama.service
Wants=ollama.service
[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya/cognitive-growth
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/nasu_autonomous_cognition.py run
Environment=PYTHONDONTWRITEBYTECODE=1
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
ReadWritePaths=/var/lib/nasuraya/cognitive-growth
MemoryMax=512M
CPUQuota=100%
TimeoutStartSec=240
UNIT
cat >"$TIMER" <<'UNIT'
[Unit]
Description=Offline Qwen 4B evidence-linked inquiry every six hours
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00 UTC
Persistent=true
Unit=nasuraya-cognitive-growth.service
[Install]
WantedBy=timers.target
UNIT
chmod 644 "$SERVICE" "$TIMER"
systemctl daemon-reload
systemctl enable --now nasuraya-cognitive-growth.timer
systemctl start nasuraya-cognitive-growth.service
echo '=== OFFLINE GROWTH RECEIPT ==='
systemctl is-active nasuraya-cognitive-growth.timer
runuser -u nasuraya -- python3 "$BIN" status
echo 'AUTONOMOUS_COGNITIVE_RESEARCH=ENABLED;PRODUCTION=UNCHANGED;MODEL=LOCAL_ONLY'
