#!/usr/bin/env bash
# Owner-approved rollback of ONLY the root-owned Bridge service file.
set -Eeuo pipefail
[[ ${EUID} -eq 0 && $# -eq 1 ]] || { echo 'USAGE (root): rollback.sh /root/nasu-bridge-backups/bridge-TIMESTAMP-pre-v2.py'; exit 2; }
case "$1" in
  /root/nasu-bridge-backups/bridge-*-pre-v2.py) ;;
  *) echo 'BLOCKED: backup outside approved directory or naming'; exit 2 ;;
esac
BACKUP="$1"
BRIDGE=/usr/local/lib/nasuraya/bridge.py
[[ -f "$BACKUP" && ! -L "$BACKUP" && -f "$BRIDGE" && ! -L "$BRIDGE" ]] || { echo 'BLOCKED: backup/bridge missing or symlink'; exit 2; }
python3 -B - "$BACKUP" <<'PYCODE'
import ast, pathlib, sys
ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
PYCODE
install -o root -g root -m 755 "$BACKUP" "$BRIDGE"
systemctl restart nasuraya-bridge.service
systemctl is-active --quiet nasuraya-bridge.service
printf 'BRIDGE_V2_ROLLBACK_OK;SOURCE=%s;AWAKE_UNCHANGED=YES\n' "$BACKUP"
