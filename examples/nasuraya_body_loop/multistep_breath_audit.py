"""Test frozen one-step action forecasts on continuous trajectories in the native simulator."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .__main__ import ROOT, SOURCE, verified_sources
from .rare_breath_audit import bracket

FIT_SHA256 = "b63ecb0368dba9a8540fade7201a05d21fac14c3b7f4fd81ebfe9389447ae674"
DURATION = 0.1
STEPS = 5
MODELS = ("bracket", "feedback_gate", "previous_action", "incumbent_bucket")


def cases():
    panel = [("interior", x, .07, .47) for x in (.498, .517, .522, .532, .542, .556)]
    panel.extend([("stress", .532, .78, .47), ("stress", .532, .07, .93)])
    return [
        dict(id=f"trajectory-{i+1:02d}", group=group,
             initial=dict(fatigue=fatigue, pain=pain, sleep=sleep))
        for i, (group, fatigue, pain, sleep) in enumerate(panel)
    ]


def feedback_gate(bracket_action, previous, feedback):
    if feedback["walk"] is False:
        if previous == "observe" and feedback["observe"] is True:
            return "observe"
        return None
    return bracket_action


def score(rows):
    out = dict(n=len(rows), actual=dict(Counter(r["actual"] for r in rows)))
    for model in MODELS:
        bucket = model == "incumbent_bucket"
        positive = "other" if bucket else "slow_breath"
        asserted = [r for r in rows if r["predictions"][model] is not None]
        correct = sum(r["predictions"][model] == (r["actual_bucket"] if bucket else r["actual"])
                      for r in asserted)
        alarms = [r for r in asserted if r["predictions"][model] == positive]
        out[model] = dict(asserted=len(asserted), correct=correct, wrong=len(asserted)-correct,
                          abstained=len(rows)-len(asserted),
                          breath_hits=sum(r["actual"] == "slow_breath" for r in alarms),
                          breath_false_alarms=sum(r["actual"] != "slow_breath" for r in alarms))
    return out


def run_worker(output):
    from reflection_cycle import digest
    from synthetic_fixture import prepare_defaults, synthetic_origin
    from . import continuous_self_knowledge as continuous
    from .continuous_self_eval import make_body, start_session
    from .experience import metrics
    from .host import executed_body
    from .self_knowledge import _bucket
    from .self_knowledge_eval import _append, _write

    evidence = ROOT / "docs/evidence"
    fit_data = (evidence / "cloud-breath-audit/fit.json").read_bytes()
    if hashlib.sha256(fit_data).hexdigest() != FIT_SHA256:
        raise ValueError("the frozen one-step training artifact has changed")
    fit = json.loads(fit_data)
    config = json.loads((evidence / "continuous-self-knowledge-v02/selected-config.json").read_text())
    protocol = dict(trajectories=cases(), steps=STEPS, duration_s=DURATION, preferred="walk",
                    fit_sha256=FIT_SHA256, incumbent_config=config,
                    gate="when walk feedback is false, only emit observe after a previous native observe and true observe feedback; otherwise abstain. With no negative walk feedback, use bracket.",
                    success="on steps 2-5, fewer wrong assertions than bracket, at least as many correct assertions and no additional false slow_breath alarms")
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "protocol.json", protocol)
    prepare_defaults()
    origin = synthetic_origin()
    rows = []
    initial_states = set()
    for case in cases():
        session = case["id"]
        initial = make_body(origin, case["initial"])
        with start_session(Path.cwd() / (session + ".sqlite"), session, initial, STEPS) as loop:
            previous = after = None
            prior_ids = set()
            for step in range(1, STEPS+1):
                ident = f"{session}-step-{step}"
                snapshot = loop.observe()
                before = metrics(snapshot)
                checkpoint = snapshot["checkpoint_sha256"]
                if step == 1:
                    if checkpoint in initial_states:
                        raise ValueError("starting states must differ between trajectories")
                    initial_states.add(checkpoint)
                elif checkpoint != after["checkpoint_sha256"]:
                    raise ValueError("trajectory did not resume the preceding body checkpoint")
                recalled = continuous.native_feedback(loop, snapshot, DURATION)
                if any(i is not None and i not in prior_ids for i in recalled["source_ids"].values()):
                    raise ValueError("feedback did not come from an earlier action in this session")
                feedback = recalled["state"]
                single = bracket(fit, before)
                incumbent = continuous.forecast_action(fit, before=before, feedback=feedback,
                                                      preferred="walk", duration_s=DURATION, config=config)
                predictions = dict(bracket=single, feedback_gate=feedback_gate(single, previous, feedback),
                                   previous_action=previous, incumbent_bucket=incumbent["predicted_action"])
                forecast = dict(id=ident, trajectory=session, group=case["group"], step=step,
                                checkpoint=checkpoint, clock=snapshot["simulated_wall_utc"],
                                before=before, previous=previous, feedback=recalled,
                                predictions=predictions, incumbent_status=incumbent["status"])
                _append(output / "forecasts.jsonl", forecast)
                receipt = loop.step(decision_id=ident, duration_s=DURATION, preferred_action="walk")
                record = loop.engine.get(ident)
                if not executed_body(record) or receipt["replayed"]:
                    raise ValueError(f"missing fresh native execution for {ident}")
                if record["request"]["evidence"][0]["source_sha256"] != checkpoint:
                    raise ValueError(f"receipt references different pre-state for {ident}")
                actual = record["actual_outcome"]["body_receipt"]["owner"]["selected_action"]
                if receipt["actual_action"] != actual:
                    raise ValueError(f"disagreement between inner owner and caller at {ident}")
                after = receipt["self_model_after"]
                elapsed = datetime.fromisoformat(after["simulated_wall_utc"]) - datetime.fromisoformat(forecast["clock"])
                if elapsed != timedelta(seconds=DURATION) or after["checkpoint_sha256"] == checkpoint:
                    raise ValueError("native clock and checkpoint must advance by one step")
                _append(output / "receipts.jsonl", dict(id=ident, native_request=receipt["requested_action"],
                        actual=actual, before=checkpoint, after=after["checkpoint_sha256"],
                        clock_after=after["simulated_wall_utc"], native_record_sha256=digest(record)))
                rows.append(dict(forecast, actual=actual, actual_bucket=_bucket(actual)))
                previous = actual
                prior_ids.add(ident)
    first = [r for r in rows if r["step"] == 1]
    later = [r for r in rows if r["step"] > 1]
    if (len(first), len(later), len(initial_states)) != (8, 32, 8):
        raise ValueError("incomplete trajectory panel")
    switches = [r for r in later if r["actual"] != r["previous"]]
    by_phase = dict(first=score(first), later=score(later), action_switches=score(switches))
    for group in ("interior", "stress"):
        by_phase[group + "_later"] = score([r for r in later if r["group"] == group])
    gate, base = (by_phase["later"][name] for name in ("feedback_gate", "bracket"))
    passed = (gate["wrong"] < base["wrong"] and gate["correct"] >= base["correct"]
              and gate["breath_false_alarms"] <= base["breath_false_alarms"])
    summary = dict(schema="nasuraya-sequence-audit/1", trajectories=len(first), steps_per_trajectory=STEPS,
                   decisions=len(rows), fit_count=len(fit), frozen_fit_sha256=FIT_SHA256,
                   later_gate_criterion_met=passed, phases=by_phase, model_api_calls=0,
                   scope="eight designed paths from the same simulated origin; correlated actions within each path")
    _write(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


def main():
    import os
    import subprocess

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    output = parser.parse_args().output_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="nasuraya-sequence-") as directory:
        root = Path(directory)
        for name in verified_sources():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root), str(ROOT))))
        env.pop("OPENAI_API_KEY", None)
        worker = "from pathlib import Path; import sys; from examples.nasuraya_body_loop.multistep_breath_audit import run_worker; run_worker(Path(sys.argv[1]))"
        subprocess.run([sys.executable, "-c", worker, str(output)], cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
