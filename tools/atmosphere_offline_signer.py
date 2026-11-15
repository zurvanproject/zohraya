"""Opt-in OFFLINE signing utility. Never generates keys or contacts any network.

Operator must inspect the unsigned receipt/manifest before signing and keep
private key material physically separate from the running Awake/VPS host.
"""
import argparse
import json
import os
from pathlib import Path
import stat
from atmosphere_attestation import MANIFEST_SCHEMA, canonical
from atmosphere_recovery import SCHEMA as BACKUP_SCHEMA


def sign_existing_key(unsigned, *, pem_path):
    if type(unsigned) is not dict or "signature_ed25519" in unsigned:
        raise ValueError("expected-unsigned-object")
    if unsigned.get("schema") == MANIFEST_SCHEMA:
        if set(unsigned) != {"schema", "issued_at", "expires_at", "commitments"}:
            raise ValueError("unsigned-evidence-manifest-shape")
    elif unsigned.get("schema") == BACKUP_SCHEMA:
        if set(unsigned) != {"schema", "created_at", "files"}:
            raise ValueError("unsigned-backup-receipt-shape")
    else:
        raise ValueError("schema-not-signable")
    keypath = Path(pem_path)
    info = keypath.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 32768:
        raise ValueError("private-key-file-permissions")
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = load_pem_private_key(keypath.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("requires-ed25519-private-key")
    return {**unsigned, "signature_ed25519": key.sign(canonical(unsigned)).hex()}


def main(argv=None):
    p = argparse.ArgumentParser(description="OFFLINE review-and-sign only: no keygen, no network")
    p.add_argument("--unsigned", type=Path, required=True)
    p.add_argument("--existing-private-key", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    if args.unsigned.is_symlink() or args.unsigned.stat().st_size > 65536:
        p.error("invalid-unsigned-input")
    unsigned = json.loads(args.unsigned.read_text(encoding="utf-8"))
    signed = sign_existing_key(unsigned, pem_path=args.existing_private_key)
    # Fail if output already exists, enforce owner-only permissions.
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(canonical(signed))
    print("SIGNED_OFFLINE: output written; keep private key off runtime host")

if __name__ == "__main__":
    main()
