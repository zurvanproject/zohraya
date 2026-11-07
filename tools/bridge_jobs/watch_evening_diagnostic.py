"""Read-only installation diagnostics; safe aggregates, no key access."""
import hashlib,importlib.util,json,os,re,time
from pathlib import Path
SHA="e77d9b4abd809a7a87b9b5599c1d112192357c57250f21c50cbf01d5e679c98d"
def main():
 worker=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 cfg=json.loads((worker/"config.json").read_text(encoding="utf-8"))
 root=worker/"monitoring/evening-20261107"
 p=root/"watch.py"
 prefix=f"DIAG=CHECK;REM={int(1794076200-time.time())};DIR={int(root.exists())};SRC={int(p.is_file())};"
 if not p.is_file():return prefix
 if hashlib.sha256(p.read_bytes()).hexdigest()!=SHA:return prefix+"HASH=BAD"
 s=importlib.util.spec_from_file_location("watch",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 t=m.task_info()
 try:
  a=m.snapshot(worker,Path(cfg["tadash_root"]))
  return prefix+f"ISS={','.join(a['issues']) or 'none'};TASK={t['state']};EN={int(t['enabled'])};SYS={int(t['system'])};R={a['native_revision']};SIG={a['checkpoint'][:16]}"
 except Exception as e:
  code=str(e) if re.fullmatch(r"[A-Za-z0-9_]{1,40}",str(e)) else type(e).__name__
  return prefix+"CHECK="+code
if __name__=="__main__":
 try:summary=main()
 except Exception as e:summary="DIAG=FAILED;ERROR="+type(e).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
