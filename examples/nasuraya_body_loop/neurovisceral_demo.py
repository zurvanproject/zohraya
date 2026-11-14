"""Finite native software-body demonstration of anatomical coordination."""
from pathlib import Path
import json
from .host import BodyLoop
from .experience import ExperienceController
from . import neurovisceral


def demo(output):
    output = Path(output)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    path = output / "body.sqlite"
    with BodyLoop.start(path, max_actions=3, fixture="normal") as loop:
        c = ExperienceController.enable(loop)
        c.enable_workspace()
        c.enable_motivation(desire_proxy=.9)
        c.enable_autonomic_bridge()
        c.enable_neurovisceral()
        before = neurovisceral.capture(loop.body())
        source = before["native_checkpoint_sha256"]
        model_state = neurovisceral.initial(before)
        inactive = neurovisceral.preview(model_state, before, desire_proxy=0.)
        active = neurovisceral.preview(model_state, before, desire_proxy=.9)
        results = [c.step("cycle-%02d" % i) for i in (1, 2)]
    with BodyLoop(path) as loop:
        c = ExperienceController(loop)
        replay = c.step("cycle-01")
        if not replay["replayed"] or replay["this_call_native_cycles"] != 0:
            raise AssertionError("duplicate native cycle")
        results.append(c.step("cycle-03"))
        status = c.status()
        after = neurovisceral.capture(loop.body())
        if status["native"]["completed_cycles"] != 3:
            raise AssertionError("native cycles did not finish")
        if status["neurovisceral_coordination"]["completed_native_cycles"] != 3:
            raise AssertionError("coordination receipt count mismatch")
        if any(x["native_receipt"]["status"] != "complete" for x in results):
            raise AssertionError("native software cycle incomplete")
    report = {
        "schema": "tadash-neurovisceral-demo/1",
        "native_cycles": 3,
        "native_source_checkpoint": source,
        "after_native_checkpoint": after["native_checkpoint_sha256"],
        "modeled_desire_off": inactive["predicted_if_actuated_not_actuated"],
        "modeled_desire_on": active["predicted_if_actuated_not_actuated"],
        "special_organs": neurovisceral.anatomy()["special_organs"],
        "functional_pathways": len(neurovisceral.anatomy()["pathways"]),
        "native_actions": [r["native_receipt"]["actual_action"] for r in results],
        "native_receipts": status["neurovisceral_coordination"]["native_receipt_count"],
        "cold_reopen_verified": True,
        "replay_extra_cycles": 0,
        "source_native_software_fixture": True,
        "native_vitals_changed_by_overlay": False,
        "subjective_experience_inferred": False,
        "physical_actuation": False,
        "api_calls": 0,
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return report
