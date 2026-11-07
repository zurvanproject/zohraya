"""Read only the second ciphertext part of the one approved control-thread challenge."""
import json
import os
from pathlib import Path
import re


def main():
    root = Path(os.environ["LOCALAPPDATA"]) / "Nasuraya" / "Moltbook" / "sokimi_20261107"
    try:
        record = json.loads((root / "reply.json").read_text(encoding="utf-8"))
        if (record.get("state") != "submitted" or
                record.get("post_id") != "e97c71c8-49db-424e-b0ec-d913e883044f" or
                record.get("body_sha256") != "54d89db1a32e6fe64ad7597f2eefdf677f694c2739ee061aa87d30dff5b5e50b"):
            raise ValueError("Ledger mismatch")
        cipher = (root / "prompt.rsa").read_text(encoding="ascii")
        if not re.fullmatch(r"[A-Za-z0-9+/]{342}==", cipher):
            raise ValueError("Invalid encrypted payload")
        summary = "C2=" + cipher[172:]
    except (OSError, ValueError):
        summary = "NO_CHALLENGE"
    print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))


if __name__ == "__main__":
    main()
