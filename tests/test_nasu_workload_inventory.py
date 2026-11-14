import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('inventory',Path(__file__).resolve().parents[1]/'tools/bridge_jobs/nasu_migration_inventory.py')
inventory=importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

class InventoryTests(unittest.TestCase):
    def test_metadata_only_and_sensitive_files_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'session.sqlite').write_bytes(b'PRIVATE_MEMORY_CANARY')
            (root/'api-key.dpapi').write_text('DO_NOT_DISCLOSE')
            (root/'recipient-private.pem').write_text('DO_NOT_DISCLOSE')
            result=inventory.scan(root)
            self.assertEqual(result['files'],1)
            self.assertEqual(result['sqlite_files'],1)
            self.assertEqual(result['excluded_sensitive'],2)
            self.assertNotIn('CANARY',json.dumps(result))
            self.assertNotIn('DISCLOSE',json.dumps(result))

    def test_does_not_follow_link_or_claim_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            target=root/'target'
            target.mkdir()
            (target/'file').write_text('private')
            source=root/'source'
            source.mkdir()
            (source/'link').symlink_to(target,target_is_directory=True)
            result=inventory.scan(source)
            self.assertEqual(result['files'],0)
            self.assertEqual(result['skipped_links'],1)
            self.assertFalse(result['complete'])

    def test_missing_root_is_not_empty_successful_transfer(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(inventory.scan(Path(td)/'absent')['present'])

if __name__=='__main__':unittest.main()
