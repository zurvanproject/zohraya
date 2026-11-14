import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('sources',Path(__file__).resolve().parents[1]/'tools/nasu_workload_sources.py')
sources=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)

class SourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.code=b'raise RuntimeError("MUST_NOT_EXECUTE")\n'
        self.item={'id':'example','commit':'a'*40,'tree':'b'*40,'blob_count':1,
                   'total_bytes':len(self.code),'readiness':'awaiting_original_state'}
        self.tree={'sha':'b'*40,'truncated':False,'tree':[
            {'path':'program.py','type':'blob','mode':'100644','size':len(self.code),'sha':sources.blob_sha(self.code)}]}

    def archive(self,entries=None):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as z:
            for name,body,mode in entries or [('program.py',self.code,0o100644)]:
                item=zipfile.ZipInfo('zohraya-'+self.item['commit']+'/'+name)
                item.external_attr=mode<<16
                z.writestr(item,body)
        return output.getvalue()

    def fetch(self,url,limit):
        return json.dumps(self.tree).encode() if '/git/trees/' in url else self.archive()

    def test_stage_is_verified_idempotent_and_never_executes_code(self):
        first=sources.stage(self.item,self.home,self.fetch)
        again=sources.stage(self.item,self.home,lambda *_:self.fail('unexpected network'))
        self.assertEqual(first['verified_files'],1)
        self.assertEqual(first['execution'],'not_started')
        self.assertEqual(first['private_state'],'not_imported')
        self.assertEqual(again['source'],'verified_existing')
        self.assertEqual(sources.status([self.item],self.home)[0]['source'],'verified')

    def test_changed_source_is_not_overwritten_or_reported_verified(self):
        sources.stage(self.item,self.home,self.fetch)
        p=self.home/'sources'/'example'/'program.py'
        p.write_text('local change')
        with self.assertRaises(ValueError):sources.stage(self.item,self.home,self.fetch)
        self.assertEqual(p.read_text(),'local change')
        self.assertEqual(sources.status([self.item],self.home)[0]['source'],'invalid_requires_review')

    def reject(self,archive):
        dest=self.home/'extract'
        dest.mkdir()
        with self.assertRaises(ValueError):
            sources.unpack(archive,self.item,sources.expected_files(self.item,self.tree),dest)

    def test_path_traversal_rejected(self):
        self.reject(self.archive([('../outside',b'bad',0o100644)]))
        self.assertFalse((self.home/'outside').exists())

    def test_symlink_rejected(self):
        self.reject(self.archive([('program.py',self.code,0o120777)]))

    def test_codeload_archive_without_unix_type_uses_verified_git_mode(self):
        # Real codeload response on 2026-11-14 had external_attr == 0 for
        # every file. ZipFile.writestr supplies a default mode if passed zero,
        # so rewrite the central directory fields to reproduce those bytes.
        raw=bytearray(self.archive())
        offset=raw.index(b'PK\x01\x02')
        raw[offset+38:offset+42]=b'\0'*4
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertEqual(z.infolist()[0].external_attr,0)
        dest=self.home/'zero_mode'
        dest.mkdir()
        sources.unpack(bytes(raw),self.item,sources.expected_files(self.item,self.tree),dest)
        sources.verify(dest,sources.expected_files(self.item,self.tree))
        self.assertEqual((dest/'program.py').stat().st_mode&0o777,0o600)

    def test_permissions_only_archive_metadata_is_accepted(self):
        dest=self.home/'permissions_only'
        dest.mkdir()
        sources.unpack(self.archive([('program.py',self.code,0o600)]),self.item,
                       sources.expected_files(self.item,self.tree),dest)
        sources.verify(dest,sources.expected_files(self.item,self.tree))

    def test_special_file_type_rejected(self):
        self.reject(self.archive([('program.py',self.code,0o020600)]))

    def test_dos_directory_flag_on_expected_file_is_rejected(self):
        raw=bytearray(self.archive())
        offset=raw.index(b'PK\x01\x02')
        raw[offset+38:offset+42]=(0x10).to_bytes(4,'little')
        self.reject(bytes(raw))

    def test_safe_failure_label_does_not_leak_exception_text(self):
        self.assertTrue(sources.failure_summary(ValueError('Git blob mismatch')).endswith('CHECK=BLOB_HASH'))
        self.assertNotIn('private',sources.failure_summary(ValueError('private secret/path')))
        self.assertNotIn('private',sources.failure_summary(OSError('private secret/path')))

    def test_metadata_symlink_cannot_be_verified_or_overwritten(self):
        sources.stage(self.item,self.home,self.fetch)
        receipt=self.home/'receipts'/'example.json'
        external=self.home/'external.json'
        receipt.rename(external)
        receipt.symlink_to(external)
        before=external.read_bytes()
        with self.assertRaises(ValueError):sources.stage(self.item,self.home,self.fetch)
        self.assertEqual(sources.status([self.item],self.home)[0]['source'],'invalid_requires_review')
        self.assertEqual(external.read_bytes(),before)

    def test_blob_corruption_rejected(self):
        corrupt=b'X'+self.code[1:]
        self.reject(self.archive([('program.py',corrupt,0o100644)]))

    def test_extra_file_rejected(self):
        self.reject(self.archive([('unexpected',b'bad',0o100644)]))

    def test_incomplete_or_wrong_tree_rejected(self):
        for update in ({'truncated':True},{'sha':'c'*40}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                sources.expected_files(self.item,{**self.tree,**update})

    def test_failed_download_cannot_replace_other_work_or_create_receipt(self):
        existing=self.home/'live-awake.sqlite3'
        existing.write_bytes(b'existing live data')
        def failed(*args):raise OSError('network unavailable')
        with self.assertRaises(OSError):sources.stage(self.item,self.home,failed)
        self.assertEqual(existing.read_bytes(),b'existing live data')
        self.assertFalse((self.home/'receipts'/'example.json').exists())

    def test_git_symlink_and_declared_size_mismatch_rejected(self):
        for change in ({'mode':'120000'},{'size':len(self.code)+1}):
            tree={**self.tree,'tree':[{**self.tree['tree'][0],**change}]}
            with self.subTest(change=change),self.assertRaises(ValueError):
                sources.expected_files(self.item,tree)

if __name__=='__main__':unittest.main()
