"""Offline encrypted archive reconstruction and import parser tests."""
import base64
import importlib.util
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
import zlib
BASE=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
reader=module("awake_importer",BASE/"tools/nasu_import_encrypted_awake.py")
writer=module("awake_exporter",BASE/"tools/bridge_jobs/nasu_awake_encrypted_export.py")
generator=module("key_pub",BASE/"tools/nasu_migration_recipient_key.py")
class TransferTests(unittest.TestCase):
    def test_full_public_manifest_and_decryption(self):
        with tempfile.TemporaryDirectory() as td:
            priv=Path(td)/"priv.pem"
            der=Path(td)/"public.der"
            subprocess.run(["openssl","genpkey","-algorithm","RSA","-pkeyopt",
                "rsa_keygen_bits:3072","-out",str(priv)],check=True,capture_output=True)
            subprocess.run(["openssl","rsa","-in",str(priv),"-RSAPublicKey_out",
                "-outform","DER","-out",str(der)],check=True,capture_output=True)
            xml=generator.public_xml(der.read_bytes())
            original=b"nasuraya dummy sqlite bytes for test only"*10
            packed=zlib.compress(original,9)
            ciphertext=b"".join(writer.rsa_oaep(packed[i:i+256],xml)
                               for i in range(0,len(packed),256))
            archive_id="f"*32
            headers=[]
            for role in ("iran","offsite"):
                headers.append("NSAB1 ID="+archive_id+" ROLE="+role+
                    " RAW="+reader.digest(original)+" ZLIB="+reader.digest(packed)+
                    " ENC="+reader.digest(ciphertext)+
                    " EV=54 Q=5 T=16 L=23 PART=1/1\n"+
                    base64.b64encode(ciphertext).decode())
            headers.append("NSAB1_DONE ID="+archive_id+" EV=54 Q=5 T=16 L=23")
            ident,data=reader.archive(headers)
            self.assertEqual(ident,archive_id)
            self.assertEqual(data["iran"][0]["RAW"],reader.digest(original))
            old=reader.PRIVATE
            reader.PRIVATE=priv
            try:
                compressed=reader.decrypt(data["iran"][1])
            finally:
                reader.PRIVATE=old
            self.assertEqual(zlib.decompress(compressed),original)
    def test_missing_offsite_copy_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"two-recipient"):
            reader.archive(["NSAB1_DONE ID="+"a"*32+" EV=1 Q=0 T=0 L=0"])

if __name__=="__main__":
    unittest.main()
