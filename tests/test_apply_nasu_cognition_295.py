"""No Ubuntu mutations; real snapshots in a temporary directory, mocked systemd."""
from functools import partial
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from tools import apply_nasu_cognition_295 as pilot
from tools import install_nasu_server_agent as support

class PilotTests(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        self.old=pilot.BEFORE
        installed=root/"nasu_autonomous_cognition.py"
        # Tests use exact target digest for the preflight via mocked digest.
        installed.write_bytes(b"old_source")
        dropin=root/"unit.d"/"90-nasuraya-qwen-timeout.conf"
        backup=root/"backup"
        timer={"active": True, "enabled": True}
        self.system_calls=[]
        self.timer=timer
        self.active=False
        new=b"new_source"
        self.new=new
        original_digest=support.digest
        def digest(raw):
            return pilot.BEFORE if raw==b"old_source" else original_digest(raw)
        dep=types.SimpleNamespace(
            COGNITION=installed, BACKUPS=root, SYSTEM=root,
            COGNITIVE_SERVICE=support.COGNITIVE_SERVICE,
            COGNITIVE_TIMER=support.COGNITIVE_TIMER,
            BRIDGE_SERVICE=support.BRIDGE_SERVICE,
            digest=digest, read_file=lambda p: support.read_file(p,owner=os.geteuid()),
            guarded=lambda p,**kw:support.guarded(p,owner=os.geteuid(),**{k:v for k,v in kw.items() if k!="owner"}),
            require=support.require,DeployError=support.DeployError,
            Snapshot=partial(support.Snapshot,owner=os.geteuid(),group=os.getegid()))
        def unit_state(name):
            if name==dep.BRIDGE_SERVICE:return {"ActiveState":"active"}
            return {"LoadState":"loaded","User":"nasuraya",
                    "FragmentPath":str(root/dep.COGNITIVE_SERVICE),
                    "ExecStart":"{ argv[]=/usr/bin/python3 "+str(installed)+" run; }",
                    "Environment":"","ActiveState":"active" if self.active else "inactive"}
        dep.unit_state=unit_state
        dep.timer_state=lambda name:dict(timer)
        def restore(name,original):
            timer.update(original)
        dep.restore_timer=restore
        def quiesce(state,reason):
            timer["active"]=False
            if self.active:
                restore(None,state)
                raise support.DeployError(reason)
        dep.quiesce_cognition=quiesce
        dep.systemctl=lambda command,*args:self.system_calls.append((command,args))
        def effective():
            return {"TimeoutStartUSec":"7min",
                    "Environment":"NASU_COGNITION_HTTP_TIMEOUT_SECONDS=300"}
        return dep,installed,dropin,backup,new,effective

    def test_source_only_requires_expected_before_hash_and_no_existing_dropin(self):
        dep,installed,dropin,backup,new,effective=self.fixture()
        with mock.patch.object(pilot,"dep",dep),mock.patch.object(pilot,"DROPIN",dropin),mock.patch.object(pilot,"BACKUP",backup):
            with mock.patch.object(pilot,"get_effective",side_effect=effective):
                self.assertEqual(pilot.preflight(new),self.timer)
                installed.write_bytes(b"unknown")
                with self.assertRaisesRegex(support.DeployError,"UNKNOWN_INSTALLED"):
                    pilot.preflight(new)
                installed.write_bytes(b"old_source")
                dropin.parent.mkdir(parents=True)
                dropin.write_bytes(b"other")
                with self.assertRaisesRegex(support.DeployError,"EXISTING_QWEN"):
                    pilot.preflight(new)

    def test_atomic_install_and_explicit_rollback(self):
        dep,installed,dropin,backup,new,effective=self.fixture()
        with mock.patch.object(pilot,"dep",dep),mock.patch.object(pilot,"DROPIN",dropin),mock.patch.object(pilot,"BACKUP",backup):
            with mock.patch.object(pilot,"get_effective",side_effect=effective),mock.patch.object(pilot.os,"geteuid",return_value=0):
                result=pilot.apply(new)
                self.assertEqual(result["state"],"installed_pilot")
                self.assertEqual(installed.read_bytes(),new)
                self.assertEqual(dropin.read_bytes(),pilot.DROPIN_BYTES)
                self.assertEqual(self.timer,{"active":True,"enabled":True})
                self.assertEqual(pilot.rollback()["state"],"rolled_back")
                self.assertEqual(installed.read_bytes(),b"old_source")
                self.assertFalse(dropin.exists())
                self.assertEqual(self.timer,{"active":True,"enabled":True})

    def test_unready_unit_causes_rollback(self):
        dep,installed,dropin,backup,new,effective=self.fixture()
        with mock.patch.object(pilot,"dep",dep),mock.patch.object(pilot,"DROPIN",dropin),mock.patch.object(pilot,"BACKUP",backup):
            with mock.patch.object(pilot,"get_effective",return_value={"TimeoutStartUSec":"4min","Environment":""}):
                with mock.patch.object(pilot.os,"geteuid",return_value=0):
                    with self.assertRaisesRegex(support.DeployError,"PILOT_FAILED_ROLLED_BACK"):
                        pilot.apply(new)
        self.assertEqual(installed.read_bytes(),b"old_source")
        self.assertFalse(dropin.exists())
        self.assertEqual(self.timer,{"active":True,"enabled":True})

    def test_running_cognition_refuses_without_changes(self):
        dep,installed,dropin,backup,new,effective=self.fixture()
        self.active=True
        with mock.patch.object(pilot,"dep",dep),mock.patch.object(pilot,"DROPIN",dropin),mock.patch.object(pilot,"BACKUP",backup):
            with self.assertRaisesRegex(support.DeployError,"COGNITION_RUNNING"):
                pilot.preflight(new)
        self.assertEqual(installed.read_bytes(),b"old_source")
        self.assertEqual(self.system_calls,[])

if __name__=="__main__":
    unittest.main()
