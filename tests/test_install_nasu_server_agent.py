"""Deployment contracts use disposable files and fake systemd; no host changes."""
import ast
import json
import os
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest import mock

from tools import install_nasu_server_agent as install


REV = "b" * 40
RELEASE = install.PREFIX / "releases" / REV
BRIDGE = b'''import re
COMMAND_RE = re.compile(r"(?m)^\\s*nasu-linux:\\s*(status|workload-accept|awake-status-v2|help)\\s*$", re.I)
def command(argv, timeout=30, cwd=None):
    return (argv, timeout, cwd)
def dispatch(action):
    if action == "status":
        return "old status"
    if action == "workload-accept":
        return "old locally installed workload code"
    if action == "awake-status-v2":
        return "old locally installed v2 code"
    return "Allowed: status, workload-accept, awake-status-v2, help. No arbitrary shell."
'''
STATES = {"cognitive_timer": {"active": True, "enabled": True}, "bridge_active": True}


class BridgePatchTests(unittest.TestCase):
    def patched(self, raw=BRIDGE):
        value = install.patch_bridge(raw, RELEASE, REV)
        namespace = {}
        exec(compile(value, "bounded_test_fixture", "exec"), namespace)
        return value, namespace

    def test_preserves_all_existing_extra_handlers_and_extends_allowlist(self):
        value, namespace = self.patched()
        for action, answer in (("status", "old status"),
                               ("workload-accept", "old locally installed workload code"),
                               ("awake-status-v2", "old locally installed v2 code")):
            self.assertEqual(namespace["dispatch"](action), answer)
            self.assertEqual(namespace["COMMAND_RE"].search("nasu-linux: " + action).group(1), action)
        self.assertIn(b'    if action == "workload-accept":\n        return "old locally installed workload code"', value)
        self.assertEqual(value.count(install.BEGIN.encode()), 1)
        self.assertEqual(value.count(install.END.encode()), 1)

    def test_new_handlers_are_fixed_argv_and_pinned_working_directory(self):
        _, namespace = self.patched()
        for action, mode, timeout in (("agent-status", "status", 60), ("agent-probe", "probe", 150)):
            argv, limit, cwd = namespace["dispatch"](action)
            self.assertEqual(argv, ["/usr/bin/python3", "-B", "-m", "tools.nasu_agent_diagnostics", mode])
            self.assertEqual(limit, timeout)
            self.assertEqual(cwd, str(RELEASE))
            self.assertEqual(namespace["COMMAND_RE"].search("nasu-linux: " + action).group(1), action)
        self.assertIsNone(namespace["COMMAND_RE"].search("nasu-linux: agent-probe; rm file"))
        self.assertIsNone(namespace["COMMAND_RE"].search("nasu-linux: agent-status /etc/passwd"))

    def test_help_preserves_old_text(self):
        _, namespace = self.patched()
        self.assertTrue(namespace["dispatch"]("help").startswith("Allowed: status, workload-accept, awake-status-v2, help. No arbitrary shell."))
        self.assertIn("agent-status, agent-probe", namespace["dispatch"]("help"))

    def test_unicode_source_offsets_preserve_previous_handlers(self):
        raw = BRIDGE.decode().replace('return "old status"', 'return "وضعیت پیشین"').encode()
        _, namespace = self.patched(raw)
        self.assertEqual(namespace["dispatch"]("status"), "وضعیت پیشین")

    def test_refuses_duplicate_or_modified_marker(self):
        value, _ = self.patched()
        for raw in (value, BRIDGE + b"\n# NASURAYA_AGENT_BRIDGE_BEGIN modified\n", BRIDGE + b"\n# agent-probe\n"):
            with self.subTest(raw=raw[-50:]):
                with self.assertRaises(install.DeployError):
                    self.patched(raw)

    def test_refuses_dynamic_unknown_or_inconsistent_dispatch(self):
        versions = (
            BRIDGE.replace(b'if action == "status":', b'if action in ("status",):'),
            BRIDGE.replace(b'def dispatch(action):', b'def dispatch(action, command=None):'),
            BRIDGE.replace(b'workload-accept|awake-status-v2', b'workload-accept'),
            BRIDGE.replace(b're.compile(r', b're.compile("" + r'),
            BRIDGE.replace(b'|help)', b'|help|help)'),
            BRIDGE.replace(b'(?m)^\\s*nasu-linux:', b'.*nasu-linux:'),
        )
        for raw in versions:
            with self.subTest(raw=raw[:120]):
                with self.assertRaises((install.DeployError, SyntaxError)):
                    self.patched(raw)

    def test_refuses_unpinned_release_path_and_revision(self):
        for release, revision in ((Path("/tmp/other"), REV), (RELEASE, "main"), (RELEASE, REV.upper())):
            with self.subTest(release=release, revision=revision):
                with self.assertRaises(install.DeployError):
                    install.patch_bridge(BRIDGE, release, revision)


class FileTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner, self.group = os.getuid(), os.getgid()
        self.old = self.root / "config" / "existing.py"
        self.new = self.root / "config" / "new.conf"
        self.old.parent.mkdir()
        self.old.write_bytes(b"original executable\n")
        self.old.chmod(0o640)
        self.user_data = self.root / "user.sqlite3"
        self.user_data.write_bytes(b"private persisted ledger")
        self.desired = {self.old: b"new executable\n", self.new: b"new configuration\n"}
        self.snapshot = install.Snapshot(self.root / "backups" / REV, (self.old, self.new), owner=self.owner, group=self.group)

    def create(self):
        self.snapshot.create(REV, self.desired, STATES)

    def test_snapshot_apply_restore_preserves_bytes_modes_and_user_state(self):
        self.create()
        self.snapshot.apply(self.desired)
        self.assertEqual(self.old.read_bytes(), self.desired[self.old])
        self.assertTrue(self.new.exists())
        self.snapshot.load()
        self.snapshot.restore_files()
        self.assertEqual(self.old.read_bytes(), b"original executable\n")
        self.assertEqual(self.old.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.user_data.read_bytes(), b"private persisted ledger")

    def test_injected_partial_write_failure_can_restore_all_targets(self):
        self.create()
        real = install.atomic_write
        def failing(path, *args, **kwargs):
            if path == self.new:
                raise OSError("injected failure")
            return real(path, *args, **kwargs)
        with mock.patch.object(install, "atomic_write", side_effect=failing):
            with self.assertRaises(OSError):
                self.snapshot.apply(self.desired)
        self.assertEqual(self.snapshot.data["phase"], "installing")
        self.assertEqual(self.old.read_bytes(), self.desired[self.old])
        self.snapshot.restore_files()
        self.assertEqual(self.old.read_bytes(), b"original executable\n")
        self.assertFalse(self.new.exists())

    def test_never_overwrites_backup_on_repeat(self):
        self.create()
        backup = (self.snapshot.directory / "0.bin").read_bytes()
        with self.assertRaisesRegex(install.DeployError, "BACKUP_ALREADY_EXISTS"):
            self.create()
        self.assertEqual((self.snapshot.directory / "0.bin").read_bytes(), backup)

    def test_refuses_target_changed_after_snapshot(self):
        self.create()
        self.old.write_bytes(b"third party edit")
        with self.assertRaisesRegex(install.DeployError, "TARGET_CHANGED_AFTER_SNAPSHOT"):
            self.snapshot.apply(self.desired)
        with self.assertRaisesRegex(install.DeployError, "TARGET_CHANGED_AFTER_SNAPSHOT"):
            self.snapshot.restore_files()
        self.assertEqual(self.old.read_bytes(), b"third party edit")

    def test_refuses_corrupt_backup(self):
        self.create()
        (self.snapshot.directory / "0.bin").write_bytes(b"altered backup")
        with self.assertRaisesRegex(install.DeployError, "BACKUP_DIGEST_MISMATCH"):
            self.snapshot.load()

    def test_refuses_extra_manifest_paths_and_invalid_states(self):
        self.create()
        original = self.snapshot.manifest.read_bytes()
        value = json.loads(original)
        value["files"]["/etc/passwd"] = dict(value["files"][str(self.old)])
        self.snapshot.manifest.write_bytes(install.canonical(value))
        with self.assertRaisesRegex(install.DeployError, "INVALID_BACKUP_MANIFEST"):
            self.snapshot.load()
        value = json.loads(original)
        value["states"]["cognitive_timer"]["active"] = "yes"
        self.snapshot.manifest.write_bytes(install.canonical(value))
        with self.assertRaisesRegex(install.DeployError, "INVALID_BACKUP_STATES"):
            self.snapshot.load()

    def test_refuses_symlink_target_and_symlink_ancestor(self):
        alias = self.root / "alias.py"
        alias.symlink_to(self.old)
        with self.assertRaisesRegex(install.DeployError, "SYMLINKED_SYSTEM_PATH"):
            install.guarded(alias, owner=self.owner)
        linked_dir = self.root / "linked"
        linked_dir.symlink_to(self.old.parent, target_is_directory=True)
        with self.assertRaisesRegex(install.DeployError, "SYMLINKED_SYSTEM_PATH"):
            install.guarded(linked_dir / "existing.py", owner=self.owner)

    def test_refuses_wrong_owner_and_group_writable_executable(self):
        with self.assertRaisesRegex(install.DeployError, "UNTRUSTED_FILE_OWNER_OR_MODE"):
            install.guarded(self.old, owner=self.owner + 1)
        self.old.chmod(0o660)
        with self.assertRaisesRegex(install.DeployError, "UNTRUSTED_FILE_OWNER_OR_MODE"):
            install.guarded(self.old, owner=self.owner)

    def test_symlink_added_after_snapshot_cannot_redirect_write(self):
        self.create()
        self.new.symlink_to(self.user_data)
        with self.assertRaisesRegex(install.DeployError, "SYMLINKED_SYSTEM_PATH"):
            self.snapshot.apply(self.desired)
        self.assertEqual(self.user_data.read_bytes(), b"private persisted ledger")

    def test_failed_rollback_does_not_replace_changed_targets(self):
        self.create()
        self.snapshot.apply(self.desired)
        self.new.write_bytes(b"unexpected live config")
        with self.assertRaisesRegex(install.DeployError, "TARGET_CHANGED_AFTER_SNAPSHOT"):
            self.snapshot.restore_files()
        self.assertEqual(self.new.read_bytes(), b"unexpected live config")
        self.assertEqual(self.old.read_bytes(), self.desired[self.old])


class UnitAndRollbackTests(unittest.TestCase):
    def diagnostic(self, *, code=0, **updates):
        receipt = {"schema": "nasuraya-agent-diagnostics/1", "probe": {"state": "success"},
                   "executables": {"match": True}, "integration": {"state": "ok", "records": 1},
                   "cognition": {"state": "verified_history", "completed": 2, "incomplete": 0}}
        receipt.update(updates)
        return types.SimpleNamespace(returncode=code, stdout=install.canonical(receipt))

    def test_diagnostic_failure_exit_one_retains_precise_safe_reason(self):
        with self.assertRaisesRegex(install.DeployError, "LOCAL_MODEL_PROBE_FAILED"):
            install.verify_diagnostics(self.diagnostic(code=1, probe={"state": "failed", "private": "NEVER_PRINT"}))

    def test_diagnostic_allows_verified_incomplete_history_without_claiming_healing(self):
        output = install.verify_diagnostics(self.diagnostic(cognition={"state": "incomplete", "completed": 3, "incomplete": 1}))
        self.assertEqual(output, {"state": "incomplete", "incomplete": 1})
        for state in ("invalid", "missing", "empty", "unknown"):
            with self.subTest(state=state):
                with self.assertRaisesRegex(install.DeployError, "EXISTING_COGNITIVE_HISTORY_NOT_VERIFIED"):
                    install.verify_diagnostics(self.diagnostic(cognition={"state": state, "completed": 0, "incomplete": 0}))

    def test_diagnostic_requires_recorded_journal_and_matching_installed_code(self):
        with self.assertRaisesRegex(install.DeployError, "LIVE_INTEGRATION_JOURNAL_NOT_VERIFIED"):
            install.verify_diagnostics(self.diagnostic(integration={"state": "ok", "records": 0}))
        with self.assertRaisesRegex(install.DeployError, "INSTALLED_COGNITION_HASH_MISMATCH"):
            install.verify_diagnostics(self.diagnostic(executables={"match": False}))

    def test_missing_unit_nonzero_is_accepted_only_with_explicit_not_found(self):
        missing = types.SimpleNamespace(returncode=1, stdout=b"LoadState=not-found\nActiveState=inactive\n")
        with mock.patch.object(install, "execute", return_value=missing):
            self.assertEqual(install.unit_state(install.SERVICE)["LoadState"], "not-found")
        for output in (b"", b"LoadState=loaded\n"):
            with mock.patch.object(install, "execute", return_value=types.SimpleNamespace(returncode=1, stdout=output)):
                with self.assertRaisesRegex(install.DeployError, "UNIT_STATE_UNAVAILABLE"):
                    install.unit_state(install.SERVICE)

    def test_only_fixed_units_and_paths_are_generated(self):
        values = install.units(RELEASE)
        self.assertEqual(set(values), {install.SYSTEM / install.SERVICE, install.SYSTEM / install.TIMER, install.DROPIN})
        service = values[install.SYSTEM / install.SERVICE].decode()
        self.assertIn("User=nasuraya", service)
        self.assertIn("WorkingDirectory=" + str(RELEASE), service)
        self.assertIn("ExecStart=/usr/bin/python3 -B -m tools.nasu_live_integration run", service)
        self.assertIn("IPAddressDeny=any", service)
        self.assertEqual([x for x in service.splitlines() if x.startswith("ReadWritePaths=")], ["ReadWritePaths=" + str(install.STATE)])
        self.assertIn("OnCalendar=hourly", values[install.SYSTEM / install.TIMER].decode())
        self.assertIn("Persistent=true", values[install.SYSTEM / install.TIMER].decode())
        self.assertIn("NASU_COGNITION_SOURCE_ROOT=" + str(RELEASE), values[install.DROPIN].decode())

    def test_systemctl_rejects_other_units_and_actions_before_running(self):
        with mock.patch.object(install, "execute") as runner:
            for action, name in (("restart", "ollama.service"), ("stop", "nasuraya-awake.service"),
                                 ("stop", install.COGNITIVE_SERVICE), ("mask", install.TIMER)):
                with self.subTest(action=action, name=name):
                    with self.assertRaises(install.DeployError):
                        install.systemctl(action, name)
            runner.assert_not_called()

    def test_rollback_restores_fixed_units_and_prior_timer_states(self):
        snapshot = mock.Mock()
        snapshot.data = {"phase": "installed", "revision": REV, "states": STATES}
        events = []
        with mock.patch.object(install, "systemctl", side_effect=lambda *a, **k: events.append(a)), \
             mock.patch.object(install, "unit_state", return_value={"ActiveState": "inactive"}):
            result = install.rollback(snapshot)
        snapshot.restore_files.assert_called_once()
        self.assertEqual(result["DEPLOYMENT"], "ROLLED_BACK")
        self.assertEqual(snapshot.data["phase"], "rolled_back")
        self.assertIn(("restart", install.BRIDGE_SERVICE), events)
        self.assertIn(("enable", install.COGNITIVE_TIMER), events)
        self.assertIn(("start", install.COGNITIVE_TIMER), events)
        self.assertNotIn(("stop", install.COGNITIVE_SERVICE), events)

    def test_busy_cognition_refuses_rollback_and_restores_timer(self):
        snapshot = mock.Mock()
        snapshot.data = {"phase": "installed", "revision": REV, "states": STATES}
        events = []
        with mock.patch.object(install, "systemctl", side_effect=lambda *a, **k: events.append(a)), \
             mock.patch.object(install, "unit_state", return_value={"ActiveState": "activating"}):
            with self.assertRaisesRegex(install.DeployError, "COGNITION_RUNNING_RETRY_ROLLBACK"):
                install.rollback(snapshot)
        snapshot.restore_files.assert_not_called()
        self.assertIn(("start", install.COGNITIVE_TIMER), events)
        self.assertNotIn(("stop", install.TIMER, install.SERVICE), events)

    def test_quiesce_restores_timer_on_status_failure_or_interrupt(self):
        for failure in (OSError("injected status failure"), KeyboardInterrupt()):
            events = []
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(install, "systemctl", side_effect=lambda *a, **k: events.append(a)), \
                     mock.patch.object(install, "unit_state", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        install.quiesce_cognition(STATES["cognitive_timer"], "BUSY")
                self.assertEqual(events, [("stop", install.COGNITIVE_TIMER), ("enable", install.COGNITIVE_TIMER), ("start", install.COGNITIVE_TIMER)])

    def test_quiesce_restores_timer_even_if_stop_command_fails_partially(self):
        events = []
        def system(action, unit):
            events.append((action, unit))
            if len(events) == 1:
                raise OSError("injected partial stop")
        with mock.patch.object(install, "systemctl", side_effect=system), \
             mock.patch.object(install, "unit_state") as state:
            with self.assertRaises(OSError):
                install.quiesce_cognition(STATES["cognitive_timer"], "BUSY")
        state.assert_not_called()
        self.assertEqual(events[-1], ("start", install.COGNITIVE_TIMER))

    def test_restore_attempts_start_even_when_enable_fails(self):
        events = []
        def system(action, unit):
            events.append((action, unit))
            if action == "enable":
                raise OSError("injected enable failure")
        with mock.patch.object(install, "systemctl", side_effect=system):
            with self.assertRaisesRegex(install.DeployError, "TIMER_STATE_RESTORE_FAILED"):
                install.restore_timer(install.COGNITIVE_TIMER, STATES["cognitive_timer"])
        self.assertEqual(events[-1], ("start", install.COGNITIVE_TIMER))

    def test_release_allowlist_covers_fixed_topic_sources_and_tests(self):
        from tools import nasu_autonomous_cognition as cognition
        for source, test in cognition.TOPICS.values():
            self.assertIn(source, install.FILES)
            if test:
                self.assertIn("tests/" + test, install.FILES)
        for path in install.FILES:
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)
        self.assertEqual(len(install.FILES), len(set(install.FILES)))


if __name__ == "__main__":
    unittest.main()
