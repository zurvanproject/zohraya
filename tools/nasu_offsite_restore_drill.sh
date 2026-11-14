#!/usr/bin/env bash
# Manual encrypted backup and read-only restore test, with independent restic target.
set -Eeuo pipefail
umask 077
if [[ -z "$(printenv RESTIC_REPOSITORY || true)" || -z "$(printenv RESTIC_PASSWORD_FILE || true)" ]]; then
  echo 'Configure RESTIC_REPOSITORY + RESTIC_PASSWORD_FILE out of band.' >&2; exit 2
fi
case "$RESTIC_REPOSITORY" in
  sftp:*|s3:*|rest:*|rclone:*|azure:*|gs:*) ;;
  *) echo 'Refusing a same-host local restic repository' >&2; exit 2;;
esac
[[ -f "$RESTIC_PASSWORD_FILE" ]] || { echo 'Password file missing' >&2; exit 2; }
command -v restic >/dev/null || { echo 'Please install restic first' >&2; exit 2; }
command -v python3 >/dev/null
TMP=$(mktemp -d -t nasu-restore-drill.XXXXXXXX)
trap 'rm -rf -- "$TMP"' EXIT
STAGE="$TMP/snapshot"
mkdir -m 0700 "$STAGE"
export STAGE
python3 - <<'PY'
import json, os, sqlite3, hashlib
from pathlib import Path
base=Path('/var/lib/nasuraya')
ledger=base/'continuity'/'continuity.sqlite3'
state=base/'awake-stage'/'awake.sqlite3'
report=base/'migration'/'latest-import.json'
if report.is_file():
    work=json.loads(report.read_text()).get('working_db')
    if work:
        candidate=Path(work)
        allowed=(base/'migration'/'working').resolve()
        if candidate.resolve().parent.parent != allowed:
            raise SystemExit('Untrusted Awake DB path')
        state=candidate
files={'continuity.sqlite3':ledger,'awake.sqlite3':state}
stage=Path(os.environ['STAGE'])
manifest={}
for name,source in files.items():
    if not source.is_file() or source.is_symlink():
        raise SystemExit('Missing or symlinked source: '+name)
    dest=stage/name
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True,timeout=15) as db:
        with sqlite3.connect(dest) as copy:
            db.backup(copy)
            assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    manifest[name]=hashlib.sha256(dest.read_bytes()).hexdigest()
(stage/'manifest.json').write_text(json.dumps(manifest,sort_keys=True)+'\n')
print('SQLITE_SNAPSHOT=PASS;DB_COUNT=2')
PY
restic snapshots >/dev/null
restic backup --tag nasuraya-continuity --json "$STAGE" > "$TMP/backup.jsonl"
SNAP_ID=$(python3 - "$TMP/backup.jsonl" <<'PY'
import json,sys
sid=None
for line in open(sys.argv[1]):
    obj=json.loads(line)
    if obj.get('message_type')=='summary': sid=obj.get('snapshot_id')
if not sid: sys.exit('Missing restic snapshot ID')
print(sid)
PY
)
mkdir -m 0700 "$TMP/restore"
restic restore "$SNAP_ID" --target "$TMP/restore" >/dev/null
export RESTORED="$TMP/restore$STAGE"
python3 - <<'PY'
import hashlib,json,os,sqlite3
from pathlib import Path
p=Path(os.environ['RESTORED'])
m=json.loads((p/'manifest.json').read_text())
assert set(m)=={'awake.sqlite3','continuity.sqlite3'}
for name,sha in m.items():
    content=(p/name).read_bytes()
    assert hashlib.sha256(content).hexdigest()==sha
    with sqlite3.connect(f'file:{p/name}?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print('REMOTE_ENCRYPTED_RESTORE=PASS;SQLITE_INTEGRITY=ok;DB_COUNT=2')
PY
printf 'RESTIC_SNAPSHOT_ID=%s\n' "$SNAP_ID"
