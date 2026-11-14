"""Offline encrypted archive reconstruction and import parser tests."""
import base64
import importlib.util
import json
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
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


class RefreshTests(unittest.TestCase):
    def make_db(self,path,extra=False,alter=False):
        with sqlite3.connect(path) as db:
            db.executescript("""
            CREATE TABLE control(name TEXT PRIMARY KEY,value TEXT);
            INSERT INTO control VALUES('schema','tadash-awake/1');
            INSERT INTO control VALUES('paused','1');
            CREATE TABLE evidence(id TEXT PRIMARY KEY,topic TEXT,payload TEXT);
            CREATE TABLE questions(topic TEXT PRIMARY KEY,id TEXT,kind TEXT,question TEXT,
                evidence_hash TEXT,revision INTEGER,created_at TEXT,updated_at TEXT);
            CREATE TABLE ticks(seq INTEGER PRIMARY KEY,at TEXT,status TEXT,topic TEXT);
            CREATE TABLE ledger(seq INTEGER PRIMARY KEY,at TEXT,action TEXT,detail TEXT);
            INSERT INTO evidence VALUES('ev1','topic1','{"score":1}');
            INSERT INTO ticks VALUES(1,'t','tick','topic1');
            INSERT INTO ledger VALUES(1,'t','ingest','ok');
            INSERT INTO questions VALUES('topic1','qid1','check','why','hash',1,'t','t');
            """)
            if alter: db.execute("UPDATE evidence SET payload='wrong' WHERE id='ev1'")
            if extra:
                db.execute("INSERT INTO evidence VALUES('ev2','topic1','second')")
                db.execute("INSERT INTO ticks VALUES(2,'t2','tick','topic1')")
                db.execute("INSERT INTO ledger VALUES(2,'t2','ingest','ok')")
                db.execute("UPDATE questions SET revision=2,updated_at='t2'")

    def test_idle_sqlite_wal_checkpoint_before_swap(self):
        with tempfile.TemporaryDirectory() as td:
            dbfile=Path(td)/"stage.sqlite3"
            self.make_db(dbfile)
            db=sqlite3.connect(dbfile)
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("UPDATE control SET value='1' WHERE name='paused'")
                db.commit()
            finally:
                db.close()
            reader.checkpoint_idle_stage(dbfile)
            with sqlite3.connect(dbfile) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0],"delete")
            self.assertFalse(Path(str(dbfile)+"-wal").exists())
            self.assertFalse(Path(str(dbfile)+"-shm").exists())

    def test_history_forward_only(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path(td)/"old.sqlite3"
            new=Path(td)/"new.sqlite3"
            self.make_db(old)
            self.make_db(new,extra=True)
            reader.verify_superset(old,new,[1,1,1,1],[2,1,2,2])


    def test_two_successive_archive_imports_preserve_previous_state(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            stage=home/"awake-stage"/"awake.sqlite3"
            original=home/"migration"
            initial=home/"initial.sqlite3"
            newer=home/"newer.sqlite3"
            self.make_db(initial)
            self.make_db(newer,extra=True)
            rows=[("1"*32,initial,[1,1,1,1]),("2"*32,newer,[2,1,2,2])]
            def fake_archive(comments):
                ident,source,counts=rows.pop(0)
                raw=source.read_bytes()
                packed=zlib.compress(raw,9)
                meta={"RAW":reader.digest(raw),"ZLIB":reader.digest(packed),
                      "EV":str(counts[0]),"Q":str(counts[1]),
                      "T":str(counts[2]),"L":str(counts[3]),
                      "ENC":"0"*64}
                return ident,{"iran":(meta,packed),"offsite":(dict(meta),b"offsite-opaque")}
            with patch.object(reader,"ROOT",home), patch.object(reader,"ORIGINAL",original), \
                 patch.object(reader,"STAGE",stage), patch.object(reader.os,"geteuid",return_value=1001), \
                 patch.object(reader,"fetch",return_value=[]), \
                 patch.object(reader,"decrypt",side_effect=lambda x:x), \
                 patch.object(reader,"archive",side_effect=fake_archive):
                first=reader.run()
                second=reader.run()
            self.assertIn("IMPORT=OK",first)
            self.assertIn("IMPORT=OK",second)
            self.assertFalse(stage.exists())
            old_version=original/"working"/("1"*32)/"awake.sqlite3"
            report=json.loads((original/"latest-import.json").read_text())
            self.assertEqual(reader.inspect_db(old_version),[1,1,1,1])
            self.assertEqual(reader.inspect_db(Path(report["working_db"])),[2,1,2,2])
            self.assertEqual(report["id"],"2"*32)

    def test_history_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path(td)/"old.sqlite3"
            new=Path(td)/"new.sqlite3"
            self.make_db(old)
            self.make_db(new,extra=True,alter=True)
            with self.assertRaisesRegex(ValueError,"history changed"):
                reader.verify_superset(old,new,[1,1,1,1],[2,1,2,2])

if __name__=="__main__":
    unittest.main()
