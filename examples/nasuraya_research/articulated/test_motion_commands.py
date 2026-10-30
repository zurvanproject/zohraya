"""Command replay and interruption checks; physical continuation is run separately."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .motion_commands import start_session, execute, parse_command, write_json


class MotionCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "session"
        start_session(self.folder, 2)

    def test_known_command_and_unknown_command(self):
        self.assertEqual(parse_command("يك قدم جلو برو و بایست"), 1)
        self.assertEqual(parse_command("دو قدم جلو برو و بایست"), 2)
        with self.assertRaises(ValueError):
            execute(self.folder, "a", "بدو")
        self.assertEqual(json.loads((self.folder / "session.json").read_text())["commands"], [])

    def test_completed_replay_does_not_run_physics_or_rewind(self):
        state = json.loads((self.folder / "session.json").read_text())
        state.update(used_steps=2, checkpoint={"latest": "second"})
        state["commands"] = [dict(id="first", command="یک قدم جلو برو و بایست", status="completed", receipt="first.json")]
        write_json(self.folder / "session.json", state)
        write_json(self.folder / "first.json", {"saved": "first receipt"})
        before = (self.folder / "session.json").read_bytes()
        with patch("examples.nasuraya_research.articulated.motion_commands.walk_trial", side_effect=AssertionError("must not move")):
            result = execute(self.folder, "first", "یک قدم جلو برو و بایست")
        self.assertTrue(result["replayed"])
        self.assertEqual(before, (self.folder / "session.json").read_bytes())

    def test_interrupted_motion_blocks_retry_and_new_command(self):
        with patch("examples.nasuraya_research.articulated.motion_commands.walk_trial", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                execute(self.folder, "first", "یک قدم جلو برو و بایست")
        for name in ("first", "second"):
            with self.assertRaises(ValueError):
                execute(self.folder, name, "یک قدم جلو برو و بایست")

    def test_same_id_cannot_change_request(self):
        state = json.loads((self.folder / "session.json").read_text())
        state["commands"] = [dict(id="first", command="یک قدم جلو برو و بایست", status="completed", receipt="first.json")]
        write_json(self.folder / "session.json", state)
        with self.assertRaises(ValueError):
            execute(self.folder, "first", "دو قدم جلو برو و بایست")

    def test_exhausted_step_budget_prevents_execution(self):
        state = json.loads((self.folder / "session.json").read_text())
        state["used_steps"] = 2
        write_json(self.folder / "session.json", state)
        with self.assertRaises(ValueError):
            execute(self.folder, "third", "یک قدم جلو برو و بایست")


if __name__ == "__main__":
    unittest.main()
