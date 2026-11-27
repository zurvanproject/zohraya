"""Synthetic ONLY: opt-in Qwen4B whole-shell / fake-restic contract tests.

A disposable copy of the PR #234 shell is executed with temporary source roots,
fake Ollama blobs, fake executable and fake local restic (NOT encrypted).
No production server, network, patient data, real model or actual cloud storage.
"""
import hashlib
import json
import os
import signal
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
BACKUP = PROJECT / 'tools' / 'nasu_offsite_restore_drill.sh'
BUNDLE = PROJECT / 'tools' / 'nasu_ollama_4b_recovery.py'

FAKE_RESTIC = r'''#!/usr/bin/env python3
import json,os,shutil,sys
from pathlib import Path
args=sys.argv[1:]
op=args[0] if args else ''
with open(os.environ['MOCK_CALL_LOG'],'a') as f: f.write(op+'\n')
repo=Path(os.environ['MOCK_RESTIC_REPO'])
if op=='snapshots':
    print('[]')
elif op=='backup':
    shutil.copytree(Path(args[-1]),repo/'snapshot')
    (repo/'original-path').write_text(args[-1])
    print(json.dumps({'message_type':'summary','snapshot_id':'a'*64}))
elif op=='restore':
    target=Path(args[args.index('--target')+1])
    origin=(repo/'original-path').read_text()
    final=target/origin.lstrip('/')
    final.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(repo/'snapshot',final)
    if os.environ.get('MOCK_TAMPER')=='model':
        with (final/'ollama-qwen3-4b-models.tar.gz').open('ab') as out:
            out.write(b'forged outer archive suffix')
else:
    sys.exit(61)
'''


def sha(b):
    return hashlib.sha256(b).hexdigest()


class CompleteShellContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nasu-synthetic-qwen4-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.nasu = self.root/'nasuraya'
        self.repo = self.root/'source-checkout'
        self.remote = self.root/'fake-restic'
        self.models = self.root/'models'
        self.libs = self.root/'ollama-lib'
        self.binary = self.root/'ollama'
        self.remote.mkdir()
        self.models.mkdir()
        self.libs.mkdir()
        self.repo.mkdir()
        subprocess.run(['git','init','-q',str(self.repo)],check=True)
        (self.repo/'README.md').write_text('fake checkout fixture\n')
        (self.repo/'tools').mkdir()
        shutil.copy2(BUNDLE,self.repo/'tools'/'nasu_ollama_4b_recovery.py')
        subprocess.run(['git','-C',str(self.repo),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=Synthetic',
                        '-c','user.email=fixture@example.invalid',
                        'commit','-qm','Fixture'],check=True)
        for name, marker in [('awake-stage/awake.sqlite3','awake'),
                              ('continuity/continuity.sqlite3','continuity')]:
            path = self.nasu/name
            path.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE evidence(text TEXT)')
                db.execute('INSERT INTO evidence VALUES (?)',(marker,))
            db.close()
        tag = self.models/'manifests/registry.ollama.ai/library/qwen3/4b-instruct'
        tag.parent.mkdir(parents=True)
        blobdir=self.models/'blobs'
        blobdir.mkdir()
        layer=b'NOT REAL QWEN WEIGHTS, synthetic fixture'
        config=b'{"test":"fixture"}'
        for data in (layer,config):
            (blobdir/('sha256-'+sha(data))).write_bytes(data)
        tag.write_text(json.dumps({'schemaVersion':2,
            'config':{'digest':'sha256:'+sha(config),'size':len(config)},
            'layers':[{'digest':'sha256:'+sha(layer),'size':len(layer)}]}))
        self.binary.write_text('#!/bin/sh\necho "ollama version is SYNTHETIC"\n')
        self.binary.chmod(0o755)
        (self.libs/'libcpu.so').write_bytes(b'fake runtime library')
        source=BACKUP.read_text(encoding='utf-8')
        # Substitute ONLY the source roots and the on-source helper path.
        source=source.replace("Path('/var/lib/nasuraya')",f'Path({str(self.nasu)!r})')
        source=source.replace("Path('/opt/zohraya')",f'Path({str(self.repo)!r})')
        source=source.replace("'/opt/zohraya/tools/nasu_ollama_4b_recovery.py'",
                              repr(str(self.repo/'tools'/'nasu_ollama_4b_recovery.py')))
        self.script=self.root/'backup.sh'
        self.script.write_text(source)
        fakebin=self.root/'fakebin'
        fakebin.mkdir()
        (fakebin/'restic').write_text(FAKE_RESTIC)
        (fakebin/'restic').chmod(0o755)
        pw=self.root/'password-fixture'
        pw.write_text('FAKE ONLY')
        self.calllog=self.root/'calls'
        self.calllog.touch()
        self.env=dict(os.environ,PATH=str(fakebin)+os.pathsep+os.environ['PATH'],
            RESTIC_REPOSITORY='sftp:fake@remote.invalid:/never',
            RESTIC_PASSWORD_FILE=str(pw),MOCK_CALL_LOG=str(self.calllog),
            MOCK_RESTIC_REPO=str(self.remote),
            NASU_OLLAMA_MODELS_DIR=str(self.models),NASU_OLLAMA_BIN=str(self.binary),
            NASU_OLLAMA_LIB_DIR=str(self.libs))

    def run_script(self, **kw):
        env=self.env.copy()
        env.update(kw)
        proc = subprocess.Popen(['bash',str(self.script)],env=env,text=True,
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            stdout,stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=5)
            raise
        return subprocess.CompletedProcess(proc.args,proc.returncode,stdout,stderr)

    def called(self):
        return self.calllog.read_text().splitlines()

    def test_old_v2_path_remains_opt_out_default(self):
        r=self.run_script()
        self.assertEqual(r.returncode,0,r.stderr)
        manifest=json.loads((self.remote/'snapshot'/'manifest.json').read_text())
        self.assertEqual(manifest['schema'],'nasuraya-restic-offsite/2')
        self.assertFalse(manifest['ollama_qwen3_4b_recoverable'])
        verify=subprocess.run(['python3',str(PROJECT/'tools'/'nasu_verify_restored_snapshot.py'),
                               str(self.remote/'snapshot')],capture_output=True,text=True,timeout=20)
        self.assertEqual(verify.returncode,0,verify.stderr)
        self.assertFalse(json.loads(verify.stdout)['ollama_qwen3_4b_recoverable'])
        self.assertEqual(self.called(),['snapshots','backup','restore'])

    def test_opt_in_v3_packages_and_verifies_real_structure(self):
        r=self.run_script(NASU_BUNDLE_OLLAMA_QWEN3_4B='1')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('OLLAMA_QWEN3_4B_ASSETS_ARCHIVED=true',r.stdout)
        self.assertIn('INDEPENDENT_OFFLINE_SMOKE=NOT_TESTED',r.stdout)
        manifest=json.loads((self.remote/'snapshot'/'manifest.json').read_text())
        self.assertEqual(manifest['schema'],'nasuraya-restic-offsite/3')
        self.assertTrue(manifest['ollama_qwen3_4b_recoverable'])
        self.assertFalse(manifest['ollama_qwen3_4b_independent_smoke_pass'])
        for name in ('ollama-qwen3-4b-models.tar.gz',
                     'ollama-qwen3-4b-runtime.tar.gz','ollama-qwen3-4b-info.json'):
            self.assertIn(name,manifest['files_sha256'])
        verify=subprocess.run(['python3',str(PROJECT/'tools'/'nasu_verify_restored_snapshot.py'),
                               str(self.remote/'snapshot')],capture_output=True,text=True,timeout=20)
        self.assertEqual(verify.returncode,0,verify.stderr)
        witness=json.loads(verify.stdout)
        self.assertTrue(witness['ollama_qwen3_4b_recoverable'])
        self.assertFalse(witness['independent_offline_smoke_pass'])
        self.assertEqual(self.called(),['snapshots','backup','restore'])

    def test_missing_4b_model_prevents_any_restic_command(self):
        (self.models/'manifests/registry.ollama.ai/library/qwen3/4b-instruct').unlink()
        r=self.run_script(NASU_BUNDLE_OLLAMA_QWEN3_4B='1')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.called(),[])
        self.assertNotIn('REMOTE_ENCRYPTED_RESTORE=PASS',r.stdout)

    def test_corrupt_4b_blob_prevents_any_restic_command(self):
        first_blob=next((self.models/'blobs').iterdir())
        first_blob.write_bytes(b'changed synthetic weights')
        r=self.run_script(NASU_BUNDLE_OLLAMA_QWEN3_4B='1')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.called(),[])

    def test_tamper_after_fake_restore_fails_closed(self):
        r=self.run_script(NASU_BUNDLE_OLLAMA_QWEN3_4B='1', MOCK_TAMPER='model')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('REMOTE_ENCRYPTED_RESTORE=PASS',r.stdout)
        self.assertEqual(self.called(),['snapshots','backup','restore'])

    def test_missing_ollama_runtime_prevents_any_restic_command(self):
        (self.libs/'libcpu.so').unlink()
        r=self.run_script(NASU_BUNDLE_OLLAMA_QWEN3_4B='1')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.called(),[])


if __name__=='__main__':
    unittest.main()
