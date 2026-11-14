import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
exporter=module('workload_export','tools/bridge_jobs/nasu_workload_export.py')
importer=module('workload_import','tools/nasu_workload_import.py')
recipient=module('recipient','tools/nasu_migration_recipient_key.py')

def aes(raw,key,iv):
    # Ephemeral synthetic test keys only. Production keys use a private fd.
    result=subprocess.run(['openssl','enc','-aes-256-cbc','-K',key.hex(),'-iv',iv.hex()],input=raw,capture_output=True,check=True)
    return result.stdout

class StateMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.key=Path(cls.tmp.name)/'recipient.pem'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(cls.key)],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        der=subprocess.check_output(['openssl','rsa','-in',str(cls.key),'-RSAPublicKey_out','-outform','DER'],stderr=subprocess.DEVNULL)
        cls.keys={role:recipient.public_xml(der) for role in ('iran','offsite')}

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.home=self.root/'destination';self.home.mkdir()
        (self.source/'result.json').write_text('{"private_note":"PRIVATE_CANARY"}')
        (self.source/'run_me.py').write_text('raise RuntimeError("ARCHIVED_CODE_MUST_NOT_RUN")')
        (self.source/'api-key.dpapi').write_bytes(b'KEY_MUST_REMAIN_ON_WINDOWS')

    def packed(self):
        raw,counts=exporter.snapshot(self.source,'awake_workshop')
        meta,cipher=exporter.seal(raw,'awake_workshop',counts,encrypt=aes,keys=self.keys)
        return raw,meta,cipher

    def test_authenticated_roundtrip_never_executes_or_exports_credentials(self):
        raw,meta,cipher=self.packed()
        public='\n'.join(exporter.messages(meta,cipher))
        self.assertNotIn('PRIVATE_CANARY',public)
        self.assertNotIn('KEY_MUST_REMAIN_ON_WINDOWS',public)
        self.assertNotIn('result.json',public)
        self.assertEqual(importer.unwrap(meta,cipher,self.key),raw)
        result=importer.install(meta,cipher,self.home,self.key)
        self.assertEqual(result['activation'],'not_started')
        self.assertEqual(result['credentials'],'not_imported')
        files=self.home/'imports'/'awake_workshop'/meta['header']['id']/'files'
        self.assertEqual((files/'result.json').read_text(),(self.source/'result.json').read_text())
        self.assertFalse((files/'api-key.dpapi').exists())
        self.assertEqual(importer.status(self.home)[0]['state'],'archived_verified')

    def test_sqlite_backup_includes_live_wal_without_mutating_source(self):
        db=sqlite3.connect(self.source/'session.sqlite')
        try:
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE evidence(value TEXT)')
            db.execute("INSERT INTO evidence VALUES('private row in WAL')");db.commit()
            before=db.execute('SELECT * FROM evidence').fetchall()
            raw,meta,cipher=self.packed()
            self.assertEqual(meta['header']['sqlite_snapshots'],1)
            importer.install(meta,cipher,self.home,self.key)
            imported=self.home/'imports'/'awake_workshop'/meta['header']['id']/'files'/'session.sqlite'
            checked=sqlite3.connect(imported.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:self.assertEqual(checked.execute('SELECT * FROM evidence').fetchall(),before)
            finally:checked.close()
            self.assertEqual(db.execute('SELECT * FROM evidence').fetchall(),before)
            self.assertFalse(imported.with_name('session.sqlite-wal').exists())
        finally:db.close()

    def test_cipher_tampering_rejected_before_aes(self):
        _,meta,cipher=self.packed();cipher=bytes([cipher[0]^1])+cipher[1:]
        meta['header']['cipher_sha256']=importer.digest(cipher)
        with patch.object(importer.subprocess,'run',wraps=subprocess.run) as calls:
            with self.assertRaisesRegex(ValueError,'authentication'):importer.unwrap(meta,cipher,self.key)
        self.assertEqual(len(calls.call_args_list),1)

    def test_public_header_tampering_rejected(self):
        _,meta,cipher=self.packed();meta['header']['component']='body_atlas'
        with self.assertRaisesRegex(ValueError,'authentication'):importer.unwrap(meta,cipher,self.key)

    def test_missing_or_conflicting_parts_fail_closed(self):
        _,meta,cipher=self.packed();messages=exporter.messages(meta,cipher)
        with self.assertRaises(ValueError):importer.archives([messages[0],messages[-1]])
        broken=messages[1][:-4]+'AAAA'
        with self.assertRaises(ValueError):importer.archives(messages+[broken])
        got=importer.archives(messages+messages)
        self.assertEqual(got['awake_workshop'][1],cipher)

    def test_changed_existing_import_is_preserved_and_reported_invalid(self):
        _,meta,cipher=self.packed();importer.install(meta,cipher,self.home,self.key)
        p=self.home/'imports'/'awake_workshop'/meta['header']['id']/'files'/'result.json'
        p.write_text('local change')
        with self.assertRaises(ValueError):importer.install(meta,cipher,self.home,self.key)
        self.assertEqual(p.read_text(),'local change')
        self.assertEqual(importer.status(self.home)[0]['state'],'invalid_requires_review')

    def test_changed_manifest_is_not_trusted_on_reimport(self):
        _,meta,cipher=self.packed();importer.install(meta,cipher,self.home,self.key)
        p=self.home/'imports'/'awake_workshop'/meta['header']['id']/'manifest.json'
        record=json.loads(p.read_text());record['files']=[];p.write_text(json.dumps(record))
        with self.assertRaises(ValueError):importer.install(meta,cipher,self.home,self.key)
        self.assertEqual(importer.status(self.home)[0]['state'],'invalid_requires_review')

    def test_source_symlink_is_rejected(self):
        (self.source/'outside').symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):exporter.snapshot(self.source,'awake_workshop')

    def test_archive_traversal_is_rejected(self):
        record={'schema':'nasuraya-workload-files/1','component':'awake_workshop','total_bytes':1,'excluded':[],
                'files':[{'path':'../outside','bytes':1,'sha256':importer.digest(b'x'),'method':'copy'}]}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as z:z.writestr('manifest.json',json.dumps(record));z.writestr('files/../outside',b'x')
        meta={'header':{'component':'awake_workshop','files':1,'excluded':0,'sqlite_snapshots':0}}
        with self.assertRaises(ValueError):importer.unpack(output.getvalue(),meta,self.home)
        self.assertFalse((self.root/'outside').exists())

    def test_bridge_archive_excludes_unrelated_workloads_and_credentials(self):
        (self.source/'v2_journal.json').write_text('{}')
        raw,counts=exporter.snapshot(self.source,'bridge_journal')
        self.assertEqual(counts['files'],1)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertEqual(set(z.namelist()),{'manifest.json','files/v2_journal.json'})

    @unittest.skipUnless(os.environ.get('NASU_TEST_POWERSHELL'),'PowerShell integration runs in CI')
    def test_dotnet_aes_roundtrip_against_openssl(self):
        raw,counts=exporter.snapshot(self.source,'awake_workshop')
        encrypt=lambda value,key,iv:exporter.encrypt_aes(value,key,iv,os.environ['NASU_TEST_POWERSHELL'])
        meta,cipher=exporter.seal(raw,'awake_workshop',counts,encrypt=encrypt,keys=self.keys)
        self.assertEqual(importer.unwrap(meta,cipher,self.key),raw)

    @unittest.skipUnless(os.environ.get('NASU_TEST_POWERSHELL'),'PowerShell integration runs in CI')
    def test_large_payload_bypasses_legacy_powershell_json_limit(self):
        raw=os.urandom(3*1024*1024)
        counts={'files':1,'sqlite_snapshots':0,'excluded':0}
        encrypt=lambda value,key,iv:exporter.encrypt_aes(value,key,iv,os.environ['NASU_TEST_POWERSHELL'])
        meta,cipher=exporter.seal(raw,'model_worker',counts,encrypt=encrypt,keys=self.keys)
        self.assertEqual(importer.unwrap(meta,cipher,self.key),raw)

if __name__=='__main__':unittest.main()
