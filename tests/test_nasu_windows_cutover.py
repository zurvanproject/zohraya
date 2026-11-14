"""Static and Linux fail-closed checks for Windows scheduler cutover jobs."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
freeze=load("awake_freeze",ROOT/"tools/bridge_jobs/nasu_awake_freeze_windows.py")
resume=load("awake_resume",ROOT/"tools/bridge_jobs/nasu_awake_resume_windows.py")
class Cutover(unittest.TestCase):
    def test_linux_cannot_mutate_windows_tasks(self):
        with patch.object(freeze.os,"name","posix"),patch.object(resume.os,"name","posix"):
            self.assertEqual(freeze.main(),"FREEZE=BLOCKED;CAUSE=NOT_WINDOWS")
            self.assertEqual(resume.main(),"RESUME=BLOCKED;CAUSE=NOT_WINDOWS")
    def test_target_only_both_awake_jobs(self):
        for script in (freeze.PS,resume.PS):
            self.assertIn("NasurayaAwakeHourly",script)
            self.assertIn("NasurayaAwakeIngress",script)
            self.assertNotIn("NasurayaBridge",script)
            self.assertNotIn("Remove-ScheduledTask",script)
    def test_freeze_blocks_running_and_rolls_back(self):
        self.assertIn("TASK_BUSY",freeze.PS)
        self.assertIn("Enable-ScheduledTask",freeze.PS)
        self.assertIn("Disable-ScheduledTask",freeze.PS)
        self.assertIn("State.ToString()",freeze.PS)
if __name__=="__main__":unittest.main()
