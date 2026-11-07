"""Fresh, bounded SOFTWARE-body demonstrations of the integrated workspace.

Run only through verified nasuraya_body_loop worker with no API key.
"""
from pathlib import Path

from .experience import ExperienceController
from .host import BodyLoop


def demo(output_dir):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    results = {}
    for fixture in ("normal", "sleep"):
        path = output / (fixture + ".sqlite")
        with BodyLoop.start(path, fixture=fixture, max_actions=3) as loop:
            c = ExperienceController.enable(loop)
            before = loop.status()
            c.enable_workspace()
            first = c.step("first")
            saved = c.status()["state"]["workspace"]
            assert first["plan"]["workspace"]["preferred"] in ("walk", "observe")
            assert loop.status()["actions_reserved"] == 1
            assert loop.status()["actions_remaining"] == before["actions_remaining"] - 1
        with BodyLoop(path) as loop:
            c = ExperienceController(loop)
            assert c.status()["state"]["workspace"] == saved
            second = c.step("second")
            first_replay = c.step("first")
            assert first_replay["replayed"] and first_replay["this_call_native_cycles"] == 0
            third = c.step("third")
            state = c.status()
            assert state["integrated_workspace"]["learned_native_cycles"] == 3
            assert state["native"]["completed_cycles"] == 3
            assert state["native"]["actions_remaining"] == 0
            results[fixture] = {
                "requested": [x["plan"]["preferred"] for x in (first, second, third)],
                "native_actual": [x["native_receipt"]["actual_action"] for x in (first, second, third)],
                "attention": [x["plan"]["workspace"]["attention"] for x in (first, second, third)],
                "reasons": [x["plan"]["workspace"]["reason"] for x in (first, second, third)],
                "workspace_cycles_after_reopen": state["integrated_workspace"]["learned_native_cycles"],
                "replay_created_extra_body_cycles": False,
                "cold_restart_preserved_workspace": True,
                "native_protection_owned_by_body": True,
            }
    assert results["normal"]["requested"][0] == "walk"
    assert results["sleep"]["requested"][0] == "observe"
    return {
        "schema": "nasuraya-integrated-workspace-demo/1",
        "source": "source-verified native software-body fixtures",
        "software_body_cycles": 6,
        "workspace_updated_from_native_receipts": 6,
        "sessions_reopened": 2,
        "fixtures": results,
        "api_calls": 0,
        "physical_actuation": False,
        "consciousness_claim": None,
        "scope": "functional cognitive integration in authored synthetic fixtures",
    }
