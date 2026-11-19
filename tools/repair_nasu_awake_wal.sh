#!/usr/bin/env bash
# Root-only repair for an enabled Awake service whose telemetry WAL is read-only.
# Preserve the imported state, activation gate, and Windows scheduler freeze.
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Run as root'; exit 1; }
cd /opt/zohraya
python3 -m unittest discover -s tests -p test_nasu_awake_offline_runner.py -v
[[ "$(systemctl show nasuraya-awake.service -p User --value)" == nasuraya ]]
[[ "$(systemctl show nasuraya-awake.service -p ProtectSystem --value)" == strict ]]
[[ "$(systemctl show nasuraya-awake.service -p NoNewPrivileges --value)" == yes ]]

timer_was_active=$(systemctl is-active nasuraya-awake.timer || true)
systemctl stop nasuraya-awake.timer
restore_timer() {
    if [[ "$timer_was_active" == active ]]; then systemctl start nasuraya-awake.timer; fi
}
trap restore_timer EXIT
state=$(systemctl show nasuraya-awake.service -p ActiveState --value)
[[ "$state" == inactive || "$state" == failed ]] || { echo 'REPAIR=BLOCKED;CAUSE=SERVICE_BUSY'; exit 2; }

# Reproduce the read under the installed service's writable-path policy.
# This probe never calls run(), resumes memory, or emits private memory.
probe=$(cat <<'PY'
import datetime as dt, importlib.util, sqlite3
spec=importlib.util.spec_from_file_location('reader','/usr/local/lib/nasuraya/awake_runner.py')
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
try:
    reader.observations(dt.datetime.now(dt.timezone.utc))
except sqlite3.Error as exc:
    code=getattr(exc,'sqlite_errorcode',0)
    if (code & 255) in (sqlite3.SQLITE_READONLY,sqlite3.SQLITE_CANTOPEN):
        print('PROBE=SQLITE_ACCESS_ERROR;CODE='+str(code),flush=True)
        raise SystemExit(42)
    print('PROBE=OTHER_SQLITE_ERROR;CODE='+str(code),flush=True)
    raise SystemExit(2)
except Exception:
    print('PROBE=OTHER_ERROR',flush=True)
    raise SystemExit(2)
print('PROBE=OK',flush=True)
PY
)
writable=$(systemctl show nasuraya-awake.service -p ReadWritePaths --value)
run_probe() {
    set +e
    probe_output=$(systemd-run --quiet --wait --pipe --collect \
        --description=Nasuraya-telemetry-read-probe \
        --property=User=nasuraya --property=Group=nasuraya \
        --property=ProtectSystem=strict --property=ProtectHome=true \
        --property=NoNewPrivileges=true --property=PrivateTmp=true \
        --property=RestrictAddressFamilies=AF_UNIX --property=IPAddressDeny=any \
        --property="ReadWritePaths=$2" \
        /usr/bin/python3 -c "$probe" 2>&1)
    probe_status=$?
    set -e
    printf 'PROBE_%s_EXIT=%s\n' "$1" "$probe_status"
    # The probe prints only fixed labels and numeric SQLite codes. Also retain
    # bounded systemd launch errors instead of hiding failed diagnostics.
    printf '%s\n' "${probe_output:0:1600}"
}
run_probe RESTRICTED "$writable"
if [[ "$probe_status" -ne 42 ]] || ! [[ "$probe_output" =~ (^|$'\n')PROBE=SQLITE_ACCESS_ERROR\;CODE=[0-9]+($|$'\n') ]]; then
    echo 'REPAIR=BLOCKED;CAUSE=SQLITE_ACCESS_FAILURE_NOT_REPRODUCED'
    journalctl -u nasuraya-awake.service -n 12 --no-pager
    exit 2
fi
# A SQLite CANTOPEN result alone is not enough to change permissions. Prove
# that the SAME reader succeeds when ONLY its telemetry directory is writable.
run_probe TELEMETRY_WRITABLE "$writable /var/lib/nasuraya/continuity"
if [[ "$probe_status" -ne 0 ]] || ! [[ "$probe_output" =~ (^|$'\n')PROBE=OK($|$'\n') ]]; then
    echo 'REPAIR=BLOCKED;CAUSE=WRITABLE_TELEMETRY_DID_NOT_FIX_READ'
    exit 2
fi
echo 'PROBE=TELEMETRY_SIDECAR_ACCESS_CONFIRMED'

snapshot() {
    runuser -u nasuraya -- python3 - "$1" <<'PY'
import datetime as dt, hashlib, importlib.util, os, sqlite3, sys, time
from pathlib import Path
os.umask(0o077)
phase=sys.argv[1]
assert phase in ('before','after')
spec=importlib.util.spec_from_file_location('health','/usr/local/lib/nasuraya/awake_health.py')
health=importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
status=health.health()
if status['gate']!='ENABLED':
    raise SystemExit('REPAIR=BLOCKED;CAUSE=GATE_NOT_ENABLED')
path,_,_=health.current_state(health.HOME)
folder=health.HOME/'awake-backups'
if folder.resolve(strict=True)!=folder:
    raise SystemExit('REPAIR=BLOCKED;CAUSE=BACKUP_PATH')
name='awake-repair-'+phase+'-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(time.time_ns())+'.sqlite3'
target=folder/name
temporary=folder/(name+'.tmp')
with temporary.open('xb'):
    pass
source=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)
copy=sqlite3.connect(temporary,timeout=10)
try:
    source.execute('PRAGMA query_only=ON')
    source.backup(copy)
    if copy.execute('PRAGMA integrity_check').fetchone()!=('ok',):
        raise RuntimeError('backup integrity failed')
    counts=[copy.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('evidence','questions','ticks','ledger')]
finally:
    copy.close()
    source.close()
checksum=hashlib.sha256(temporary.read_bytes()).hexdigest()
temporary.replace(target)
with (folder/(name+'.sha256')).open('x',encoding='ascii') as marker:
    marker.write(checksum+'  '+name+'\n')
print('REPAIR_BACKUP=VERIFIED;PHASE='+phase+';EV=%d;Q=%d;T=%d;L=%d;SHA256=%s'%(*counts,checksum))
PY
}
snapshot before

dropin=/etc/systemd/system/nasuraya-awake.service.d/20-telemetry-wal.conf
expected=$'[Service]\n# mode=ro plus query_only protects ledger rows; SQLite needs WAL/SHM sidecars.\nReadWritePaths=/var/lib/nasuraya/continuity'
if [[ -e "$dropin" || -L "$dropin" ]]; then
    [[ ! -L "$dropin" ]] && cmp -s "$dropin" <(printf '%s\n' "$expected") || { echo 'REPAIR=BLOCKED;CAUSE=DROPIN_CONFLICT'; exit 2; }
else
    install -d -o root -g root -m 755 "$(dirname "$dropin")"
    printf '%s\n' "$expected" >"$dropin"
    chmod 644 "$dropin"
fi
install -o root -g root -m 755 tools/nasu_awake_offline_runner.py /usr/local/lib/nasuraya/awake_runner.py
python3 -m py_compile /usr/local/lib/nasuraya/awake_runner.py
systemctl daemon-reload
if systemctl start nasuraya-awake.service; then
    snapshot after
    restore_timer
    trap - EXIT
    runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/awake_health.py
    echo 'REPAIR=APPLIED;SERVICE=SUCCESS;VERIFY_TICK_AND_BACKUP_COUNTS'
else
    restore_timer
    trap - EXIT
    runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/awake_health.py || true
    echo 'REPAIR=APPLIED;SERVICE=FAILED;MIGRATION_NOT_CONFIRMED'
    journalctl -u nasuraya-awake.service -n 12 --no-pager
    exit 2
fi
journalctl -u nasuraya-awake.service -n 8 --no-pager
