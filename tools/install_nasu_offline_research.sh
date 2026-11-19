#!/usr/bin/env bash
# Explicit root-only installer. No connection to Awake state. No network or paid APIs.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Root required for systemd installation' >&2; exit 2; }
cd /opt/zohraya
[[ -r docs/nasuraya_offline_research_seeds_v1.json && -r tools/nasu_offline_research_queue.py ]] || exit 2
id nasuraya >/dev/null
MODEL=/var/lib/nasuraya/models/Qwen3-1.7B-Q8_0.gguf
BIN=/opt/nasuraya-local-llm/llama.cpp/build/bin/llama-cli
EXPECTED=061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a
[[ -f "$MODEL" && ! -L "$MODEL" && -x "$BIN" && ! -L "$BIN" ]] ||
  { echo 'Install and validate CPU-only local model first' >&2; exit 3; }
printf '%s  %s\n' "$EXPECTED" "$MODEL" | sha256sum -c -
python3 -m unittest discover -s tests -p test_nasu_offline_research_queue.py -v
install -d -o root -g root -m 755 /usr/local/lib/nasuraya
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya/local-research
install -o root -g root -m 755 tools/nasu_offline_research_queue.py /usr/local/lib/nasuraya/local_research.py
install -o root -g root -m 644 docs/nasuraya_offline_research_seeds_v1.json /usr/local/lib/nasuraya/local_research_seeds.json
runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/local_research.py init
cat >/etc/systemd/system/nasuraya-local-research.service <<'UNIT'
[Unit]
Description=Nasuraya bounded CPU research draft generation, independently of Awake
After=local-fs.target
[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya/local-research
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/local_research.py run
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=/var/lib/nasuraya/local-research
MemoryMax=8G
CPUQuota=250%
TimeoutStartSec=480
UNIT
cat >/etc/systemd/system/nasuraya-local-research.timer <<'UNIT'
[Unit]
Description=Weekly bounded offline-only research, never replays completed goals
[Timer]
OnCalendar=Mon *-*-* 03:00:00 UTC
Persistent=true
Unit=nasuraya-local-research.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now nasuraya-local-research.timer
systemctl is-active nasuraya-local-research.timer
echo 'RESEARCH_TIMER=ENABLED;AWAKE_UNCHANGED;INTERNET_NOT_REQUIRED;MODEL_LOCAL_ONLY'
