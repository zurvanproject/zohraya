"""Synthetic continuity fixture using the exact two public source archives.

No production state, credentials, remote actions or paid model calls.
"""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

runner=module('linux_ingress','tools/nasu_linux_ingress.py')
exporter=module('workshop_export','tools/bridge_jobs/nasu_workload_export.py')
importer=module('workshop_import','tools/nasu_workload_import.py')
sources=module('workshop_sources','tools/nasu_workload_sources.py')

class IngressUnitTests(unittest.TestCase):
    def test_missing_current_state_never_creates_database(self):
        with tempfile.TemporaryDirectory() as td, patch.object(runner,'BASE',Path(td)):
            with self.assertRaises((ValueError,FileNotFoundError)):runner.current_state()
            self.assertEqual(list(Path(td).rglob('*')),[])

    def test_missing_workshop_never_calls_session_constructor(self):
        with tempfile.TemporaryDirectory() as td, patch.object(runner,'LIVE',Path(td)):
            with patch('builtins.print'):
                with self.assertRaises((ValueError,FileNotFoundError)):runner.snapshot(lambda _:self.fail('must not create session'))

    def test_atomic_receipt_rejects_link(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);outside=root/'outside';outside.write_text('keep')
            path=root/'last.json';path.symlink_to(outside)
            with self.assertRaises(ValueError):runner.atomic(path,{'replace':True})
            self.assertEqual(outside.read_text(),'keep')

@unittest.skipUnless(os.environ.get('NASU_INGRESS_SOURCES'),'pinned public source integration is explicit')
class PinnedSourceContinuationTests(unittest.TestCase):
    def test_retained_revision_idempotence_recovery_backups_and_gates(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td).resolve();home=base/'workloads';home.mkdir()
            cache=Path(os.environ['NASU_INGRESS_SOURCES']).resolve()
            for part in ('sources','manifests'):
                shutil.copytree(cache/part,home/part)
            settings={'BASE':base,'HOME':home,'LIVE':home/'ingress-live',
                      'BACKUPS':home/'ingress-backups','CATALOG':ROOT/'tools/nasu_workload_catalog.json'}
            with patch.multiple(runner,**settings):
                paths=runner.verified_sources();live,Session=runner.modules(paths)
                from examples.nasuraya_runtime.__main__ import demo_frames
                now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
                windows=base/'synthetic-windows';windows.mkdir()
                old_state=windows/'state'
                live.core.set_paused(old_state,False,now=now-dt.timedelta(hours=12))
                with Session.create(windows/'workshop',session_id='awakevps',backend='workshop',max_actions=48,
                                    at_utc=(now-dt.timedelta(hours=12)).isoformat()) as session:
                    for revision in range(5):
                        session.step('awake'+str(revision+1),demo_frames(revision,.95 if revision%4==2 else 0.),expected_revision=revision)
                        snap=session.snapshot()
                        live.bridge.import_snapshot(old_state,snap,stream=live.STREAM,
                                                    observed_at=now-dt.timedelta(hours=11-revision))
                self.assertEqual(live.core.status(old_state)['counts']['evidence'],30)
                awake_id='a'*32;state=base/'migration'/'working'/awake_id;state.mkdir(parents=True)
                with sqlite3.connect(old_state/'awake.sqlite3') as original:
                    with sqlite3.connect(state/'awake.sqlite3') as dest:original.backup(dest)
                (base/'migration'/'latest-import.json').write_text(json.dumps({'id':awake_id,'working_db':str(state/'awake.sqlite3')}))
                gate={'schema':'nasuraya-awake-offline/1','enabled':True,'import_id':awake_id}
                (base/'awake-control.json').write_text(json.dumps(gate))
                live.core.ingest(state,[{'event_id':'linux-marker','topic':'server.load','source_ref':'tadash://server/telemetry',
                                        'value':1,'confidence':1,'observed_at':now.isoformat()}],now=now)
                raw,counts=exporter.snapshot(windows/'workshop','awake_workshop')
                self.assertEqual(counts['excluded'],0)
                archive_id='b'*32;version=home/'imports'/'awake_workshop'/archive_id
                files=version/'files';files.mkdir(parents=True)
                record=importer.unpack(raw,{'header':{'component':'awake_workshop',**counts}},files)
                (version/'manifest.json').write_bytes(importer.canonical(record))
                receipts=home/'data-receipts';receipts.mkdir()
                receipt={'component':'awake_workshop','id':archive_id,'state':'archived_verified',
                         'manifest_sha256':importer.digest(importer.canonical(record))}
                (receipts/'awake_workshop.json').write_text(json.dumps(receipt))
                self.assertEqual(runner.prepare()['revision'],5)
                self.assertEqual(runner.prepare()['revision'],5)
                first=runner.run(now=now)
                self.assertEqual((first['before_revision'],first['revision'],first['imported'],first['events']),(5,6,6,37))
                self.assertEqual(first['actions_remaining'],42)
                second=runner.run(now=now)
                self.assertEqual((second['status'],second['revision'],second['imported']),('deferred_hourly',6,0))
                self.assertEqual(len(list(runner.BACKUPS.iterdir())),2)
                for folder in runner.BACKUPS.iterdir():
                    for name in ('awake','workshop'):
                        with sqlite3.connect(folder/(name+'.sqlite3')) as db:
                            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                importer.verify(files,record)  # original archive did not change
                # Simulate committed source step followed by a crash before ingestion.
                with Session(runner.LIVE/'workshop') as session:
                    session.step('awake7',demo_frames(6,.95),expected_revision=6)
                recovered=runner.run(now=now+dt.timedelta(hours=1))
                self.assertEqual((recovered['status'],recovered['revision'],recovered['imported']),('recovered_uningested',7,6))
                self.assertEqual(recovered['events'],43)
                with sqlite3.connect(state/'awake.sqlite3') as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM evidence WHERE id='linux-marker'").fetchone()[0],1)
                # A source change and an activation mismatch fail without advancing.
                p=paths['runtime_78kg']/'examples'/'nasuraya_runtime'/'session.py'
                original=p.read_bytes();p.write_bytes(original+b'\n')
                with self.assertRaises(ValueError):runner.run(now=now+dt.timedelta(hours=2))
                p.write_bytes(original)
                gate['import_id']='c'*32;(base/'awake-control.json').write_text(json.dumps(gate))
                with self.assertRaises(ValueError):runner.run(now=now+dt.timedelta(hours=2))
                gate['import_id']=awake_id;(base/'awake-control.json').write_text(json.dumps(gate))
                self.assertEqual(runner.status()['revision'],7)
                # The original four synthetic jobs finish at revision 9. Do not
                # reset the session or invent jobs merely to keep a timer busy.
                for step in range(8,10):runner.run(now=now+dt.timedelta(hours=step-6))
                capped=runner.run(now=now+dt.timedelta(hours=40))
                self.assertEqual((capped['status'],capped['revision'],capped['actions_remaining'],capped['imported']),('completed_awaiting_new_goal',9,39,0))
                self.assertEqual(capped['goal'],{'goal_reached':True,'safe':True,'pending_jobs':0,'completed_jobs':4})
                self.assertEqual(runner.status()['revision'],9)
                importer.verify(files,record)

if __name__=='__main__':unittest.main()
