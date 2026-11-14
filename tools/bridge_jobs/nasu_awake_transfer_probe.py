"""Read-only migration readiness probe for Windows Tadash Awake. No secrets read."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

def probe():
    if os.name != "nt":
        return "EXPORT=BLOCKED;OS=NOT_WINDOWS"
    program = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    awake = program / "NasurayaAwake" / "state" / "awake.sqlite3"
    token = program / "NasurayaBridge" / "github_token.dpapi"
    if not awake.is_file() or awake.is_symlink():
        return "EXPORT=BLOCKED;STATE=ABSENT"
    if awake.stat().st_size > 16_000_000:
        return "EXPORT=BLOCKED;STATE=OVERSIZE"
    db = sqlite3.connect(awake.as_uri()+"?mode=ro", uri=True, timeout=4)
    try:
        integ = db.execute("PRAGMA quick_check").fetchone()[0]
        evidence = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        questions = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        ticks = db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        ledger = db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    finally:
        db.close()
    crypto = int(importlib.util.find_spec("cryptography") is not None)
    return "EXPORT=READY;DB="+str(awake.stat().st_size)+";INTEGRITY="+str(integ)+";EV="+str(evidence)+";Q="+str(questions)+";T="+str(ticks)+";L="+str(ledger)+";CRYPTO="+str(crypto)+";KEYPRESENT="+str(int(token.is_file()))

if __name__ == "__main__":
    try:
        result = probe()
    except BaseException:
        result = "EXPORT=ERROR;CAUSE=" + type(sys.exc_info()[1]).__name__
    print(json.dumps({"status":"ok","summary":result},separators=(",",":")))
