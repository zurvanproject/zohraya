import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from atmosphere_offline_signer import sign_existing_key
from atmosphere_attestation import MANIFEST_SCHEMA
from test_atmosphere_attestation import keypair

class OfflineSignerTests(unittest.TestCase):
    def test_existing_private_key_signs_but_no_key_is_generated_by_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ephemeral-only-test-key.pem"
            private, root = keypair()
            path.write_bytes(private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            path.chmod(0o600)
            payload = {"schema": MANIFEST_SCHEMA, "issued_at": "2026-11-15T16:59:00Z",
                       "expires_at": "2026-11-15T18:00:00Z", "commitments": [
                {"event_id": "test-001", "source_id": "stage3-pr198", "source_revision": "a" * 64,
                 "payload_sha256": "b" * 64}]}
            result = sign_existing_key(payload, pem_path=path)
            from atmosphere_attestation import canonical
            self.assertTrue(root.verify(payload, result["signature_ed25519"]))

    def test_empty_manifest_does_not_receive_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "testkey.pem"
            private, _ = keypair()
            path.write_bytes(private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "unsigned-manifest-cardinality"):
                sign_existing_key({"schema": MANIFEST_SCHEMA, "issued_at": "2026-11-15T16:59:00Z",
                                   "expires_at": "2026-11-15T18:00:00Z", "commitments": []}, pem_path=path)

    def test_insecure_private_key_file_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "testkey.pem"
            private, root = keypair()
            path.write_bytes(private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private-key-file-permissions"):
                sign_existing_key({"schema": MANIFEST_SCHEMA, "issued_at": "2026-11-15T16:59:00Z",
                                   "expires_at": "2026-11-15T18:00:00Z", "commitments": [
                                       {"event_id": "test-001", "source_id": "stage3-pr198",
                                        "source_revision": "a" * 64, "payload_sha256": "b" * 64}]}, pem_path=path)

if __name__ == "__main__": unittest.main()
