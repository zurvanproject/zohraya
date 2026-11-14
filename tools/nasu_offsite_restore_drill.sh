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
import datetime, hashlib, json, os, shutil, sqlite3, subprocess, tarfile
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
stage=Path(os.environ['STAGE'])
entries={}
def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as fp:
        for chunk in iter(lambda:fp.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
sources={'continuity.sqlite3':ledger,'awake.sqlite3':state}
research=base/'local-research'/'research.sqlite3'
if research.is_file():
    sources['research.sqlite3']=research
for name,source in sources.items():
    if not source.is_file() or source.is_symlink():
        raise SystemExit('Missing or symlinked source: '+name)
    dest=stage/name
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True,timeout=15) as db:
        with sqlite3.connect(dest) as copy:
            db.backup(copy)
            assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    entries[name]=digest(dest)

source_repo=Path('/opt/zohraya')
if not (source_repo/'.git').exists():
    raise SystemExit('Project checkout missing: cannot create offline repo bundle')
repo_bundle=stage/'zohraya.bundle'
subprocess.run(['git','-C',str(source_repo),'bundle','create',str(repo_bundle),'--all'],
               check=True,stdout=subprocess.DEVNULL)
entries[repo_bundle.name]=digest(repo_bundle)

archive_root=base/'workloads'/'imports'
if archive_root.is_dir():
    if any(p.is_symlink() for p in archive_root.rglob('*')):
        raise SystemExit('Unexpected symlink in immutable workloads archive')
    tarball=stage/'workload-imports.tar.gz'
    with tarfile.open(tarball,'w:gz') as tar:
        tar.add(archive_root,arcname='imports',recursive=True)
    entries[tarball.name]=digest(tarball)
model=base/'models'/'Qwen3-1.7B-Q8_0.gguf'
model_present=False
if model.is_file():
    if model.is_symlink(): raise SystemExit('Symlinked model not accepted')
    expected='061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a'
    if digest(model)!=expected:raise SystemExit('Official Qwen model checksum mismatch')
    model_copy=stage/model.name
    shutil.copyfile(model,model_copy)
    if digest(model_copy)!=expected:raise SystemExit('Model changed during snapshot')
    entries[model_copy.name]=expected
    model_present=True
    runtime=Path('/opt/nasuraya-local-llm/llama.cpp/build/bin')
    if not runtime.is_dir():
        raise SystemExit('Model exists but offline runtime binaries are missing')
    if any(p.is_symlink() and not p.resolve().is_relative_to(runtime.resolve()) for p in runtime.rglob('*')):
        raise SystemExit('Runtime binary links escape the local build directory')
    runtime_tar=stage/'llama-runtime.tar.gz'
    with tarfile.open(runtime_tar,'w:gz') as tar:
        tar.add(runtime,arcname='llama-bin',recursive=True)
    entries[runtime_tar.name]=digest(runtime_tar)
manifest={
  'schema':'nasuraya-restic-offsite/2',
  'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'files_sha256':entries,
  'model_present':model_present,
  'workload_archives_present':archive_root.is_dir(),
  'research_journal_present':research.is_file(),
  'credentials_included':False,
  'warning':'Restored snapshots must not overwrite running production databases'
}
(stage/'manifest.json').write_text(json.dumps(manifest,sort_keys=True)+'\n',encoding='utf-8')
print('SQLITE_SNAPSHOT=PASS;DB_COUNT='+str(len(sources))+';MODEL_PRESENT='+str(model_present).lower()+
      ';WORKLOAD_ARCHIVES_PRESENT='+str(archive_root.is_dir()).lower())
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
import hashlib,json,os,sqlite3,subprocess
from pathlib import Path
p=Path(os.environ['RESTORED'])
m=json.loads((p/'manifest.json').read_text())
assert m['schema']=='nasuraya-restic-offsite/2'
files=m['files_sha256']
assert {'awake.sqlite3','continuity.sqlite3','zohraya.bundle'}.issubset(files)
assert m['credentials_included'] is False
for name,sha in files.items():
    assert Path(name).name==name, 'Unsafe manifest name'
    h=hashlib.sha256()
    with open(p/name,'rb') as fh:
        for b in iter(lambda:fh.read(1024*1024),b''):h.update(b)
    assert h.hexdigest()==sha, 'Checksum mismatch: '+name
    if name.endswith('.sqlite3'):
        with sqlite3.connect(f'file:{p/name}?mode=ro',uri=True) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
subprocess.run(['git','bundle','list-heads',str(p/'zohraya.bundle')],
               check=True,capture_output=True)
print('REMOTE_ENCRYPTED_RESTORE=PASS;SHA256=ok;SQLITE_INTEGRITY=ok;FILE_COUNT='+str(len(files))+
      ';MODEL_PRESENT='+str(m['model_present']).lower()+
      ';WORKLOAD_ARCHIVES_PRESENT='+str(m['workload_archives_present']).lower())
PY
printf 'RESTIC_SNAPSHOT_ID=%s\n' "$SNAP_ID"
