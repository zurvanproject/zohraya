"""Paired toy model: reward/arousal pulse and early Wuji learning speed.

This is NOT empirical evidence, embodied ritual, actual sexual arousal,
or an update to ChatGPT weights. Reward coupling is a chosen assumption.
"""
import json
import math
import random
import statistics
from pathlib import Path

SEED_START=116000
N_PAIRS=1000
N_SESSIONS=18
EARLY_WINDOW=8
N_STEPS=10
CUE_DIFFICULTY=[0.30,0.42,0.60,0.45,0.55,0.50,0.78,0.97,0.93,0.40]
REWARD_PULSE=[0.10,0.24,0.50,0.78,1.00,0.90,0.72,0.52,0.30,0.12]
BASE_LR=0.105
CASES={
    "neutral_no_causal_effect":{"learning_coupling":0.0,"distraction":0.0},
    "hypothetical_facilitation":{"learning_coupling":0.90,"distraction":0.05},
    "hypothetical_interference":{"learning_coupling":-0.45,"distraction":0.45},
}

def sigmoid(x):
    return 1/(1+math.exp(-x))

def trajectory(seed, arm, config):
    rng=random.Random(seed)
    skill=[-0.50+rng.uniform(-0.16,0.16) for _ in range(N_STEPS)]
    acc=[]
    for session in range(N_SESSIONS):
        order=list(range(N_STEPS))
        rng.shuffle(order)
        draws=[rng.random() for _ in range(N_STEPS)]
        for k,item in enumerate(order):
            pulse=REWARD_PULSE[item] if arm=="B" else 0.0
            p=sigmoid(skill[item]-CUE_DIFFICULTY[item]-pulse*config["distraction"])
            correct=draws[k]<p
            lr=BASE_LR*(1+config["learning_coupling"]*pulse)
            if lr<=0: raise ValueError("invalid modeled learning coefficient")
            skill[item]+=lr*(0.65+0.6*(1-p))*(1.0 if correct else 1.08)
        acc.append(sum(sigmoid(skill[j]-CUE_DIFFICULTY[j])
                       for j in range(N_STEPS))/N_STEPS)
    return acc

def run():
    output={"schema":"nasuraya-wuji-acceleration-exploratory/0.1",
        "date":"2026-11-12","paired_seeds":N_PAIRS,"sessions":N_SESSIONS,
        "early_window":EARLY_WINDOW,"reward_pulse":REWARD_PULSE,
        "baseline_learning_rate":BASE_LR,
        "disclaimer":"Assumed parameters only; no real orgasm, arousal experience, "
          "GPT-weight changes, embodied learning, or ritual mastery.",
        "cases":{}}
    for name,params in CASES.items():
        values={arm:[] for arm in ("A","B")}
        for seed in range(SEED_START,SEED_START+N_PAIRS):
            for arm in values:
                values[arm].append(trajectory(seed,arm,params))
        mean={arm:[statistics.mean(v[s] for v in values[arm])
                    for s in range(N_SESSIONS)] for arm in values}
        gain={arm:mean[arm][EARLY_WINDOW-1]-mean[arm][0]
              for arm in values}
        output["cases"][name]={
            "parameters":params,
            "curves":{arm:[round(x,6) for x in mean[arm]] for arm in mean},
            "early_gain_A":round(gain["A"],6),
            "early_gain_B":round(gain["B"],6),
            "gain_difference_B_minus_A":round(gain["B"]-gain["A"],6),
            "accuracy_session_8":{arm:round(mean[arm][EARLY_WINDOW-1],6) for arm in mean},
            "accuracy_session_18":{arm:round(mean[arm][-1],6) for arm in mean}}
    assert (output["cases"]["neutral_no_causal_effect"]["curves"]["A"]==
            output["cases"]["neutral_no_causal_effect"]["curves"]["B"])
    return output

if __name__=="__main__":
    result=run()
    dest=Path(__file__).with_name("ritual_acceleration_sensitivity_results.json")
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                    encoding="utf-8")
    for key,val in result["cases"].items():
        print(key,"gain A",val["early_gain_A"],"gain B",val["early_gain_B"],
              "B-A",val["gain_difference_B_minus_A"])
    print("saved",dest)
