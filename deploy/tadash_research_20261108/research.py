"""Finite synthetic project probes. One independent, deterministic cohort per slot."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from math import ceil, log
import os
from pathlib import Path
import random
from statistics import mean, median

from neuropelvic import NeuroPelvic
import valuation as v

SCHEMA = "nasuraya-evening-v1"
SLOT_COUNT = 48
PINS = {
    "neuropelvic.py": ("333b42e9c855b071c881c6e6f96870aaae5ecd64",
                       "11af35930b67c1f9d52621e1c00319bcd8c3087f68e1f4044026adfbfc485c11"),
    "valuation.py": ("765b496f0f9013ac800c25e81b7285a746eee237",
                     "95dcafec504947a956a2b86f8e7d8ac222bc7a2fc33b315c12104b6ee05fedbe"),
}
CONTEXTS = tuple(v.CONTEXTS)


def check_sources():
    for name, (_, expected) in PINS.items():
        data = Path(__file__).with_name(name).read_bytes().replace(b"\r\n", b"\n")
        if sha256(data).hexdigest() != expected:
            raise ValueError("unexpected research source: " + name)


def sim(intensity, cutoff, mode="start", rhythm=.70, recovery_cue=.8):
    model = NeuroPelvic()
    if mode != "no_start":
        model.start_cycle()
    for tick in range(350):
        # Stop input *before* the step at the specified simulated time.
        model.step(.1, rhythm=rhythm, intensity=intensity if tick < cutoff else 0.,
                   breath_cue=recovery_cue, attention=.7, stop=mode == "stop" and tick == 10)
        if tick >= cutoff and model.state.phase == "baseline":
            break
    events = {r["to"]: r["time"] for r in model.events}
    return {"cutoff_s": cutoff/10, "peaks": model.peak_count,
            "peak_at_s": events.get("peak"), "restored_at_s": events.get("baseline"),
            "final_phase": model.state.phase}


def physiology(slot):
    # Permutation spreads early time slots across the entire intensity range.
    intensity = round(.68 + ((23*slot+31) % SLOT_COUNT)*.31/(SLOT_COUNT-1), 5)
    traces = [sim(intensity, cutoff) for cutoff in range(10, 111, 5)]
    # Analytic prediction for the source's exponential rise and threshold hold.
    # Withdrawing near this prediction tests the implementation's discrete timing.
    # Distinct recovery cues can change restoration latency after a peak.
    boundaries = []
    for rhythm in (.1, .3, .5, .7, .9, 1.):
        target = .88*intensity+.12*rhythm
        horizon = NeuroPelvic.MAX_RISING_SECONDS
        crossing = None
        if target > NeuroPelvic.PEAK_THRESHOLD:
            crossing = -1.8*log(1.-NeuroPelvic.PEAK_THRESHOLD/target)+NeuroPelvic.PEAK_HOLD_SECONDS
        center = min(horizon, crossing) if crossing is not None else horizon
        for offset in range(-7, 8):
            cutoff = max(1, ceil(10*center)+offset)
            for cue in (.25, .90):
                t = sim(intensity, cutoff, rhythm=rhythm, recovery_cue=cue)
                t.update(rhythm=rhythm, recovery_cue=cue, predicted_onset_s=crossing)
                boundaries.append(t)
    negative = sim(intensity, 110, "no_start")
    stopped = sim(intensity, 110, "stop")
    assert negative["peaks"] == stopped["peaks"] == 0
    assert all(t["final_phase"] == "baseline" for t in traces+[negative, stopped])
    reaching = [t["cutoff_s"] for t in traces if t["peaks"]]
    return {"input_intensity": intensity, "traces": traces, "boundary_traces": boundaries, "no_start": negative,
            "early_stop": stopped, "first_tested_duration_with_peak_s": min(reaching) if reaching else None}


def noise(rng):
    return tuple(rng.uniform(-.02, .02) for _ in range(3))


def best(q):
    return max(v.ACTIONS, key=q.get)


def context_trial(seed, error_rate, train_n):
    rng = random.Random(seed)
    agent = v.Learner.blank()
    # Follow the source's epsilon-greedy fitting rather than train on test outcomes.
    for ctx, n in v.episodes(seed+100000, train_n):
        act = agent.choose(ctx, rng, epsilon=.22)
        agent.learn(ctx, act, v.outcome(ctx, act, n)["intrinsic_utility_proxy"])
    picks = {c: best(agent.q[c]) for c in CONTEXTS}
    blind = best({a: mean(agent.q[c][a] for c in CONTEXTS) for a in v.ACTIONS})
    totals = Counter()
    errors = 0
    for ctx, n in v.episodes(seed+200000, 128):
        wrong = rng.choice([c for c in CONTEXTS if c != ctx])
        seen = wrong if rng.random() < error_rate else ctx
        errors += int(seen != ctx)
        actions = {"clean": picks[ctx], "noisy": picks[seen], "blind": blind, "rest": "rest"}
        scores = {a: v.outcome(ctx, a, n)["intrinsic_utility_proxy"] for a in v.ACTIONS}
        for label, a in actions.items():
            totals[label] += scores[a]
        totals["oracle"] += max(scores.values())
    return {"seed": seed, "train_n": train_n, "label_errors": errors,
            "mean_utility": {name: round(total/128, 6) for name, total in totals.items()}}


def changed_utility(action, n):
    r = v.outcome("curious", action, n)
    if action != "explore":
        return r["intrinsic_utility_proxy"]
    after = list(r["after"])
    after[2] = v.clamp(r["before"][2]+n[2])
    return v.utility(r["before"], after, 0.)


def reversal_trial(seed, pre_blocks):
    # Each action is observed once per training block with identical noise.
    # The held-out probes do not update the policy. Previous evidence is kept.
    rng = random.Random(seed)
    agent = v.Learner.blank()
    for _ in range(pre_blocks):
        n = noise(rng)
        for a in v.ACTIONS:
            agent.learn("curious", a, v.outcome("curious", a, n)["intrinsic_utility_proxy"])
    frozen = best(agent.q["curious"])
    choices = []
    for _ in range(128):
        n = noise(rng)
        for a in v.ACTIONS:
            agent.learn("curious", a, changed_utility(a, n))
        choices.append(best(agent.q["curious"]))
    stable = next((i+1 for i, a in enumerate(choices)
                   if a == "rest" and all(c == "rest" for c in choices[i:])), None)
    final = choices[-1]
    probe = [noise(random.Random(seed+300000+i*1000000)) for i in range(24)]
    gain = mean(changed_utility(final, n)-changed_utility(frozen, n) for n in probe)
    return {"seed": seed, "pre_blocks": pre_blocks, "frozen": frozen, "final": final,
            "blocks_to_rest_through_end": stable, "heldout_gain_over_frozen": round(gain, 6)}


def cohort(slot):
    p = physiology(slot)
    error_rate = (0., .10, .25, .50, .75, 1.)[slot % 6]
    seeds = [8100000+slot*1000+i for i in range(128)]
    contexts = [context_trial(seed, error_rate, (16, 64, 320, 960)[i%4])
                for i, seed in enumerate(seeds)]
    reversals = [reversal_trial(seed+400000, (8, 24, 48, 96, 192, 256, 384, 512)[i%8])
                 for i, seed in enumerate(seeds)]
    return {"schema": SCHEMA, "slot": slot, "source_commits": {k:v[0] for k,v in PINS.items()},
            "scope": "isolated synthetic sidecar and contextual bandit; no native worker actions",
            "physiology": p, "context": {"error_rate": error_rate, "trials": contexts},
            "reversal": {"post_blocks": 128, "trials": reversals},
            "physiology_cases": len(p["traces"])+len(p["boundary_traces"])+2, "heldout_choices": len(contexts)*128,
            "reversal_trials": len(reversals)}


def read_slot(path):
    r = json.loads(path.read_text(encoding="utf-8"))
    if (r.get("schema") != SCHEMA or path.name != "slot-%02d.json" % r["slot"] or
            not 0 <= r["slot"] < SLOT_COUNT):
        raise ValueError("incompatible slot receipt " + path.name)
    return r


def summary(directory):
    rows = [read_slot(p) for p in sorted(directory.glob("slot-??.json"))]
    totals = {k: sum(r[k] for r in rows) for k in ("physiology_cases","heldout_choices","reversal_trials")}
    gains = [t["heldout_gain_over_frozen"] for r in rows for t in r["reversal"]["trials"]]
    totals.update(slots=len(rows), latest_slot=max((r["slot"] for r in rows),default=None),
                  peak_grid_cells=sum(int(t["peaks"]>0) for r in rows for k in ("traces", "boundary_traces") for t in r["physiology"][k]),
                  control_peak_count=sum(r["physiology"][k]["peaks"] for r in rows for k in ("no_start","early_stop")),
                  reversal_gain=round(mean(gains),6) if gains else None)
    totals["context_results"] = {}
    for e in sorted({r["context"]["error_rate"] for r in rows}):
        trials=[t for r in rows if r["context"]["error_rate"]==e for t in r["context"]["trials"]]
        totals["context_results"][str(e)] = {k:round(mean(t["mean_utility"][k] for t in trials),6)
                                            for k in ("clean","noisy","blind","rest","oracle")}
    totals["reversal_results"] = {}
    reversals = [t for r in rows for t in r["reversal"]["trials"]]
    for n in sorted({t["pre_blocks"] for t in reversals}):
        trials=[t for t in reversals if t["pre_blocks"]==n]
        waits=[t["blocks_to_rest_through_end"] for t in trials if t["blocks_to_rest_through_end"] is not None]
        totals["reversal_results"][str(n)] = {"trials":len(trials),"switched":len(waits),
                                               "median_blocks":median(waits) if waits else None}
    return totals


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slot", type=int, choices=range(SLOT_COUNT))
    mode.add_argument("--summary", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    check_sources()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.summary:
        result = summary(args.out)
    else:
        target = args.out / ("slot-%02d.json" % args.slot)
        if not target.exists():
            r = cohort(args.slot)
            # A fixed slot and seed range produce identical output on replay.
            tmp = target.with_suffix(".%d.tmp" % os.getpid())
            tmp.write_text(json.dumps(r,sort_keys=True,allow_nan=False),encoding="utf-8")
            tmp.replace(target)
        row = read_slot(target)
        result = {k: row[k] for k in ("slot", "physiology_cases","heldout_choices","reversal_trials")}
    print(json.dumps(result, sort_keys=True,separators=(",",":")))


if __name__ == "__main__":
    main()
