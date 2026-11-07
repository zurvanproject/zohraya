"""Read-only worker model receipt evidence; no dialogue, key or raw API IDs."""
from contextlib import closing
import hashlib,json,os,re,sqlite3
from pathlib import Path

def main():
 root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 with closing(sqlite3.connect((root/"state/worker.sqlite").resolve().as_uri()+"?mode=ro",uri=True)) as db:
  row=db.execute("SELECT id,record FROM goals ORDER BY admitted DESC LIMIT 1").fetchone()
  if row is None:return "EVIDENCE=NO_GOAL"
  goal_id,raw=row;record=json.loads(raw)
  calls=[json.loads(r[0]) for r in db.execute("SELECT record FROM calls WHERE goal_id=?",(goal_id,))]
 result=record.get("result") or {};native=result.get("native") or {}
 final=any(m.get("phase")=="final_answer" for m in result.get("messages",[]))
 state=record.get("status","none").upper()
 if not re.fullmatch(r"[A-Z_]{1,20}",state):state="UNKNOWN"
 session=record.get("session") or ""
 return (f"EVIDENCE={state};MODEL=G6ASTRA;TURN={result.get('turn_status','none').upper()};TOOLS={len(calls)};HTTP={record.get('api_requests',0)};FINAL={int(final)};N={native.get('completed_cycles',0)};R={native.get('revision',0)};SID={hashlib.sha256(session.encode()).hexdigest()[:12]};RSA_GONE={int(not (root/'recipient-private.dpapi').exists())};ACT=0")

if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="EVIDENCE=FAILED;ERROR="+type(error).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
