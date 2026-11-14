"""Portable Windows-exporter RSA-OAEP interoperability regression."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
export=load("awake_export",BASE/"tools/bridge_jobs/nasu_awake_encrypted_export.py")
keygen=load("recipient_key",BASE/"tools/nasu_migration_recipient_key.py")
class EncryptionTests(unittest.TestCase):
    def test_rsa_oaep_sha256_compatible_with_openssl(self):
        with tempfile.TemporaryDirectory() as t:
            private=Path(t)/"priv.pem"
            public_der=Path(t)/"pub.der"
            cipher=Path(t)/"cipher.bin"
            subprocess.run(["openssl","genpkey","-algorithm","RSA","-pkeyopt",
                "rsa_keygen_bits:3072","-out",str(private)],check=True,
                capture_output=True,timeout=30)
            subprocess.run(["openssl","rsa","-in",str(private),"-RSAPublicKey_out",
                "-outform","DER","-out",str(public_der)],check=True,
                capture_output=True,timeout=10)
            xml=keygen.public_xml(public_der.read_bytes())
            for msg in [b"one",b"\0"*256,b"a"*318]:
                cipher.write_bytes(export.rsa_oaep(msg,xml))
                result=subprocess.run(["openssl","pkeyutl","-decrypt","-inkey",str(private),
                    "-pkeyopt","rsa_padding_mode:oaep","-pkeyopt","rsa_oaep_md:sha256",
                    "-pkeyopt","rsa_mgf1_md:sha256","-in",str(cipher)],
                    check=True,capture_output=True,timeout=10)
                self.assertEqual(result.stdout,msg)
    def test_key_rejects_oversized_block(self):
        with self.assertRaises(ValueError):
            export.rsa_oaep(b"X"*320,export.PUBLIC_KEYS["iran"])

if __name__=="__main__":
    unittest.main()
