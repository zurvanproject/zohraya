"""Read the private evening-watch aggregate; no writes to worker or native ledgers."""
import hashlib,importlib.util,json,os
from pathlib import Path
SHA="ae07581fb7a5ecafb9274199364ab836a8529e07823b70e2ee1bbd867ecb3058"
def main():
 root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker/monitoring/evening-20261107"
 p=root/"watch.py"
 if hashlib.sha256(p.read_bytes()).hexdigest()!=SHA:raise ValueError("pinned watch")
 s=importlib.util.spec_from_file_location("evening_watch",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 return m.report(root)
if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="WATCH=REPORT_FAILED;ERROR="+type(error).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
