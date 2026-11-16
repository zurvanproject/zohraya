#!/usr/bin/env bash
# Explicitly reviewed human-operated installation; default action is DRY-RUN.
set -Eeuo pipefail
umask 077
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
BRIDGE=/usr/local/lib/nasuraya/bridge.py
DEST=/usr/local/lib/nasuraya/bridge_v2
UNIT=nasuraya-bridge.service
mode="${1:---dry-run}"
[[ "$mode" == '--dry-run' || "$mode" == '--apply' ]] || { echo 'USAGE: install.sh --dry-run|--apply'; exit 2; }
[[ -f "$BRIDGE" && ! -L "$BRIDGE" ]] || { echo 'BLOCKED: installed bridge absent/symlink'; exit 2; }
[[ ! -e "$DEST" && ! -L "$DEST" ]] || { echo 'BLOCKED: bridge_v2 already exists'; exit 2; }
[[ -f "$HERE/worker.py" && -f "$HERE/patch_bridge.py" ]] || { echo 'BLOCKED: source absent'; exit 2; }
[[ $(systemctl show -p User --value "$UNIT") == nasuraya ]] || { echo 'BLOCKED: unexpected service User'; exit 2; }
systemctl show -p ExecStart --value "$UNIT" | grep -F -q -- "$BRIDGE" || { echo 'BLOCKED: unexpected ExecStart'; exit 2; }
systemctl is-active --quiet "$UNIT" || { echo 'BLOCKED: bridge is not active'; exit 2; }
command -v python3 >/dev/null || exit 2
# Known SHA-256 of reviewed Bridge v2 source files, verified before touching service.
printf '%s  %s\n' \
  'c2daaa2a4a51af30ecccb5c66319ee6267d578904fde198071d1927af7cbf258' "$HERE/worker.py" \
  '9cd2ed56ca96dcef7ff18f0e40e38075ba7fd3dac930e4423058ff699c7ee86b' "$HERE/patch_bridge.py" | sha256sum -c -
# Only locally supplied and tested files, no URL fetch or pip during installation.
python3 -B -m py_compile "$HERE/worker.py" "$HERE/patch_bridge.py"
TMP="$(mktemp -d /tmp/nasu-bridge-v2-patch.XXXXXXXX)"
BACKUP=''
APPLIED=0
BUILT=0
cleanup() {
  rc=$?
  if [[ "$APPLIED" -eq 1 ]]; then
    echo 'V2_INSTALL_FAILED_RESTORING_BRIDGE'
    if [[ -n "$BACKUP" && -f "$BACKUP" ]]; then
      install -o root -g root -m 755 "$BACKUP" "$BRIDGE"
      systemctl restart "$UNIT" || true
    fi
  fi
  if [[ "$BUILT" -eq 1 ]]; then rm -rf -- "$DEST"; fi
  [[ "$TMP" == /tmp/nasu-bridge-v2-patch.* ]] && rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
python3 -B "$HERE/patch_bridge.py" "$BRIDGE" "$TMP/bridge-v2.py"
if [[ "$mode" == '--dry-run' ]]; then
  echo 'BRIDGE_V2_DRY_RUN_OK;BRIDGE_UNCHANGED=YES;RESTART=NO'
  exit 0
fi
[[ ${EUID} -eq 0 ]] || { echo 'BLOCKED: root required for one-time install'; exit 2; }
[[ -f "$HERE/../../tests/test_bridge_v2.py" ]] || { echo 'BLOCKED: offline tests not included'; exit 2; }
python3 -B -m unittest discover -s "$HERE/../../tests" -p test_bridge_v2.py -v
install -d -o root -g root -m 755 "$DEST"
BUILT=1
install -o root -g root -m 644 "$HERE/worker.py" "$DEST/worker.py"
install -d -o root -g root -m 700 /root/nasu-bridge-backups
BACKUP="/root/nasu-bridge-backups/bridge-$(date -u +%Y%m%dT%H%M%SZ)-pre-v2.py"
[[ ! -e "$BACKUP" ]] || { echo 'BLOCKED: backup collision'; exit 2; }
install -o root -g root -m 600 "$BRIDGE" "$BACKUP"
echo "BACKUP=$BACKUP"
sha256sum "$BACKUP"
APPLIED=1
install -o root -g root -m 755 "$TMP/bridge-v2.py" "$BRIDGE"
systemctl restart "$UNIT"
sleep 2
systemctl is-active --quiet "$UNIT" || { echo 'BRIDGE_V2_FAILED_TO_START'; exit 3; }
APPLIED=0
BUILT=0
printf 'BRIDGE_V2_INSTALLED=YES\nRESTARTED=nasuraya-bridge.service\nAWAKE_UNCHANGED=YES\nNO_V2_JOB_EXECUTED=YES\nBACKUP=%s\n' "$BACKUP"
