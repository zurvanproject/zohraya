import json
from pathlib import Path
import tempfile
import unittest

from examples.nasuraya_agent_loop.guided import start, observe, act, finish
from examples.nasuraya_agent_loop.local import State, ToolRejected


class GuidedTests(unittest.TestCase):
    def test_state_survives_reload_and_runs_caller_selected_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"checkpoint.json"
            start(path, State(29, 78, 3), max_actions=4)
            observe(path)
            self.assertEqual(act(path,"recover",{"ticks":3},"prepare")["state"]["energy"],89)
            for _ in range(3):
                observe(path)
                act(path,"process_job",{},"work")
            result=finish(path,Path(folder)/"output")
            self.assertEqual(result["status"],"completed")
            self.assertEqual(result["actions_used"],4)
            self.assertFalse(result["external_model_api_used"])
            with self.assertRaisesRegex(ValueError,"closed"):
                observe(path)

    def test_budget_and_fresh_observation_persist_across_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"checkpoint.json"
            start(path,max_actions=1)
            with self.assertRaises(ToolRejected):
                act(path,"process_job",{},"before observing")
            observe(path)
            act(path,"process_job",{},"one job")
            observe(path)
            with self.assertRaises(ToolRejected):
                act(path,"recover",{"ticks":1},"budget spent")
            self.assertEqual(observe(path)["actions_used"],1)

    def test_invalid_checkpoint_state_or_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"checkpoint.json"
            start(path)
            original=json.loads(path.read_text())
            for field,value in [("actions_used",8),("observed",True)]:
                corrupted={**original,field:value}
                path.write_text(json.dumps(corrupted))
                with self.assertRaises(ValueError):
                    observe(path)
            corrupted={**original,"state":{**original["state"],"energy":100}}
            path.write_text(json.dumps(corrupted))
            with self.assertRaises(ValueError):
                observe(path)

    def test_creation_refuses_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"checkpoint.json"
            start(path)
            with self.assertRaises(FileExistsError):
                start(path)
