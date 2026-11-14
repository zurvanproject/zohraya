#!/usr/bin/env bash
# Opt-in root installer after a provider-independent restic repository is provisioned.
# Fails closed: no timers are enabled unless the first remote backup+restore succeeds.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Root required' >&2; exit 2; }
cd /opt/zohraya
[[ -r tools/nasu_offsite_restore_drill.sh ]] || exit 2
for bin in restic flock python3; do command -v "$bin" >/dev/null || { echo "Missing $bin" >&2; exit 2; }; done
CONF=/etc/nasuraya/offsite.env
[[ -f "$CONF" && ! -L "$CONF" ]] || { echo "Create root-owned $CONF first" >&2; exit 3; }
[[ "$(stat -c %U:%G "$CONF")" == "root:root" && "$(stat -c %a "$CONF")" == "600" ]] ||
  { echo 'offsite.env must be root:root 0600' >&2; exit 3; }
install -d -o root -g root -m 755 /usr/local/lib/nasuraya
install -d -o root -g root -m 700 /var/lib/nasuraya/offsite /root/.cache/restic
install -o root -g root -m 700 tools/nasu_offsite_restore_drill.sh /usr/local/lib/nasuraya/offsite_restore_drill.sh
bash -n /usr/local/lib/nasuraya/offsite_restore_drill.sh
for name in backup restore; do
  if [[ "$name" == backup ]]; then MODE=1; else MODE=0; fi
  cat >"/etc/systemd/system/nasuraya-offsite-$name.service" <<UNIT
[Unit]
Description=Nasuraya independent encrypted offsite $name
After=local-fs.target network.target
[Service]
Type=oneshot
User=root
EnvironmentFile=/etc/nasuraya/offsite.env
ExecStart=/usr/bin/flock -n /var/lib/nasuraya/offsite/lock /usr/bin/env NASU_BACKUP_ONLY=$MODE /usr/bin/bash /usr/local/lib/nasuraya/offsite_restore_drill.sh
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
ReadWritePaths=/tmp /var/tmp /root/.cache/restic /var/lib/nasuraya/offsite
MemoryMax=2G
CPUQuota=150%
TimeoutStartSec=1800
UNIT
done
cat >/etc/systemd/system/nasuraya-offsite-backup.timer <<'UNIT'
[Unit]
Description=Daily encrypted remote restic backup
[Timer]
OnCalendar=*-*-* 02:00:00 UTC
Persistent=true
Unit=nasuraya-offsite-backup.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/nasuraya-offsite-restore.timer <<'UNIT'
[Unit]
Description=Weekly encrypted offsite round-trip restore verification
[Timer]
OnCalendar=Sun *-*-* 04:00:00 UTC
Persistent=true
Unit=nasuraya-offsite-restore.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
# Full test MUST pass before enabling anything unattended.
systemctl start nasuraya-offsite-restore.service
systemctl enable --now nasuraya-offsite-backup.timer nasuraya-offsite-restore.timer
echo 'OFFSITE_TIMERS=ENABLED;DAILY_BACKUP=ON;WEEKLY_RESTORE=ON;FRESH_MACHINE_RESTORE=NOT_VERIFIED'
