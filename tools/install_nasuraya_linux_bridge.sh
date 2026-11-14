#!/usr/bin/env bash
# One-time setup on Ubuntu 24.04. Run as root in Termius.
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then echo "Run as root"; exit 1; fi
SRC="/opt/zohraya/tools/nasuraya_linux_bridge.py"
if [[ ! -f "$SRC" ]]; then echo "Missing $SRC. First run: git -C /opt/zohraya pull --ff-only"; exit 1; fi
if ! id -u nasuraya >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/nasuraya --shell /usr/sbin/nologin nasuraya
fi
install -d -o nasuraya -g nasuraya -m 700 /var/lib/nasuraya
install -d -o root -g root -m 755 /usr/local/lib/nasuraya
install -o root -g root -m 755 "$SRC" /usr/local/lib/nasuraya/bridge.py
if [[ ! -d /var/lib/nasuraya/zohraya/.git ]]; then
  runuser -u nasuraya -- git clone --depth 1 https://github.com/zurvanproject/zohraya.git /var/lib/nasuraya/zohraya
fi
TOKEN_FILE="/var/lib/nasuraya/github-token"
if [[ ! -s "$TOKEN_FILE" ]]; then
  echo "A fine-grained GitHub PAT is needed: owner zurvanproject, repository zohraya, Issues Read/Write."
  echo "Create it in GitHub Settings > Developer settings > Personal access tokens > Fine-grained tokens."
  echo "Token is entered locally on the VPS; do NOT paste it in ChatGPT."
  IFS= read -r -s -p "Paste GitHub PAT (hidden, then Enter; leave empty to configure later): " GH_TOKEN < /dev/tty
  printf '\n'
  if [[ -n "$GH_TOKEN" ]]; then
    (umask 077; printf '%s' "$GH_TOKEN" > "$TOKEN_FILE")
    chown nasuraya:nasuraya "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    unset GH_TOKEN
  fi
fi
cat > /etc/systemd/system/nasuraya-bridge.service <<'SERVICE'
[Unit]
Description=Nasuraya Ubuntu GitHub Issue Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nasuraya
Group=nasuraya
WorkingDirectory=/var/lib/nasuraya
ExecStart=/usr/bin/python3 /usr/local/lib/nasuraya/bridge.py
Restart=on-failure
RestartSec=20
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=/var/lib/nasuraya
CapabilityBoundingSet=
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
SERVICE
chmod 644 /etc/systemd/system/nasuraya-bridge.service
systemctl daemon-reload
if [[ -s "$TOKEN_FILE" ]]; then
  systemctl enable --now nasuraya-bridge.service
  echo "Bridge service enabled. Check: systemctl status nasuraya-bridge --no-pager"
  echo "Logs: journalctl -u nasuraya-bridge -n 20 --no-pager"
else
  echo "Files installed but no token entered; bridge NOT started."
  echo "To finish later: run this installer again, then check service."
fi
echo "GitHub command queue: https://github.com/zurvanproject/zohraya/issues/212"
