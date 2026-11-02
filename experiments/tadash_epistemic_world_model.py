"""Epistemic micro-world for the pinned Tadash v03 MuJoCo body.

Separate what is hypothesized from what the unchanged native simulator measured.
Compare three predictive explanations with leave-one-out training evidence,
freeze the chosen hypothesis before disjoint native trials, and report if a
strong calibrated prior still wins. Not subjective perception or general physics.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys

from experiments import tadash_motion_episode as evidence
from experiments import tadash_weight_shift as native

SCHEMA = "tadash-epistemic-micro-world/1"
TRAIN = tuple((x,f) for f in (.5,.6) for x in (-.003,-.001,.001,.003))
HOLDOUT = ((-.0025,.55),(-.0015,.55),(.0015,.55),(.0025,.55),
           (-.002,.52),(.002,.52),(-.002,.58),(.002,.58))
KINDS = ("linear","friction","curvature")
PRIOR_GAIN = .908869279232545
MAX_RUNS = len(TRAIN) + len(HOLDOUT)


def validate_point(x,f):
    x, f = evidence.finite(x), evidence.finite(f)
    if abs(x)>.003 or not .5<=f<=.6:
        raise ValueError("Out of known little world: abstain")
    return x,f


def basis(kind,x,f):
    validate_point(x,f)
    if kind=="linear": return (x,)
    if kind=="friction": return (x,x*(f-.55))
    if kind=="curvature": return (x,x*(abs(x)/.003)**2)
    raise ValueError("Unknown hypothesis")


def coefficients(kind,rows):
    if len(rows)<4: raise ValueError("Insufficient native observations")
    z=[basis(kind,r["command_m"],r["friction"]) for r in rows]
    y=[evidence.finite(r["observed_m"]) for r in rows]
    s00=sum(v[0]**2 for v in z)
    b0=sum(v[0]*a for v,a in zip(z,y))
    if s00<=1e-16: raise ValueError("Unidentifiable response")
    if len(z[0])==1: return [b0/s00]
    s11=sum(v[1]**2 for v in z)
    s01=sum(v[0]*v[1] for v in z)
    b1=sum(v[1]*a for v,a in zip(z,y))
    det=s00*s11-s01*s01
    if det <= max(1e-26,s00*s11*1e-10):
        raise ValueError("Unidentifiable conditional model")
    return [(b0*s11-b1*s01)/det,(s00*b1-s01*b0)/det]


def estimate(kind,coeffs,x,f):
    features=basis(kind,x,f)
    prediction=sum(c*v for c,v in zip(coeffs,features))
    if not math.isfinite(prediction): raise ValueError("Nonfinite forecast")
    return prediction


def choose_model(rows):
    if len(rows)!=len(TRAIN): raise ValueError("Missing original train cases")
    scores={}
    for kind in KINDS:
        errors=[]
        for i,r in enumerate(rows):
            parts=rows[:i]+rows[i+1:]
            c=coefficients(kind,parts)
            errors.append(abs(estimate(kind,c,r["command_m"],r["friction"])-r["observed_m"]))
        scores[kind]=sum(errors)/len(errors)
    best="linear"
    for kind in ("friction","curvature"):
        if scores[kind] < scores[best]*.90:
            best=kind
    return best,scores,{kind:coefficients(kind,rows) for kind in KINDS}


def evaluate(rows):
    if len(rows)!=len(HOLDOUT):
        raise ValueError("Incomplete unseen test")
    mae={}
    for key in ("chosen","prior","identity","zero"):
        mae[key]=sum(abs(r["observed_m"]-r["predictions"][key]) for r in rows)/len(rows)
    conditions={
        "better_than_zero":mae["chosen"]<mae["zero"],
        "better_than_unadjusted_command":mae["chosen"]<mae["identity"],
        "better_than_prior_by_10_percent":mae["prior"]>1e-10 and mae["chosen"]<.9*mae["prior"],
        "predicted_direction_correct":all(r["observed_m"]*r["command_m"]>0 for r in rows),
        "returned_to_center_within_0_1mm":all(abs(r["returned_m"])<.0001 for r in rows)
    }
    return {"mae_m":mae,"criteria":conditions,"all_strong_prior_gates_met":all(conditions.values()),
            "scope":"Only held COM response under fixed v03 contact model; no general world understanding"}


def run(source,out,timeout=240):
    source,out=Path(source).resolve(),Path(out).resolve()
    if source==out or out.is_relative_to(source): raise ValueError("Source/output overlap")
    if type(timeout) is not int or not 30<=timeout<=600: raise ValueError("Invalid timeout")
    ident=evidence.source_identity(source)
    own=evidence.sha(Path(__file__))
    motor_sha=evidence.sha(Path(native.__file__))
    out.mkdir(parents=True,exist_ok=False)
    plan={"schema":SCHEMA,"identity":ident,"harness_sha256":own,"native_wrapper_sha256":motor_sha,
          "training":TRAIN,"holdout":HOLDOUT,"hypotheses":KINDS,"prior_gain":PRIOR_GAIN,
          "model_selection":"training-only leave-one-out MAE; complex needs 10% gain",
          "claim_gate":"frozen test improvement >=10% over already calibrated prior",
          "safety":"out-of-domain abstention, all native guards and no automatic retry",
          "max_trials":MAX_RUNS,"not_feelings_or_general_world":True}
    evidence.write(out/"plan.json",plan)
    plan_sha=evidence.sha(out/"plan.json")
    evidence.write(out/"status.json",{"status":"running","started_utc":datetime.now(timezone.utc).isoformat()})
    rows=[]
    try:
        def trial(phase,x,f,predictions):
            validate_point(x,f)
            if (evidence.source_identity(source)!=ident or evidence.sha(Path(__file__))!=own
                or evidence.sha(Path(native.__file__))!=motor_sha
                or evidence.sha(out/"plan.json")!=plan_sha):
                raise ValueError("Source/plan changed")
            if len(rows)>=MAX_RUNS: raise ValueError("Bounded trial count reached")
            tag=f"trial-{len(rows)+1:02d}"
            intent={"phase":phase,"command_m":x,"friction":f,
                    "predictions":predictions,"plan_sha256":plan_sha}
            evidence.write(out/(tag+"-intent.json"),intent)
            try:
                p=subprocess.run([sys.executable,"-c",native.NATIVE,str(x),str(f)],
                      cwd=source,env=evidence.clean_env(),text=True,capture_output=True,
                      timeout=timeout,check=False)
            except subprocess.TimeoutExpired as error:
                raise TimeoutError("Unknown native result; no retry") from error
            (out/(tag+".stdout.log")).write_text(p.stdout)
            (out/(tag+".stderr.log")).write_text(p.stderr)
            if p.returncode: raise RuntimeError("Native failed, no automatic retry")
            raw=json.loads(p.stdout,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
            evidence.write(out/(tag+"-native.json"),raw)
            native.validate(raw,x)
            if raw.get("friction")!=f: raise ValueError("Friction mismatch")
            row={"trial":len(rows)+1,"phase":phase,"command_m":x,"friction":f,
                 "observed_m":raw["held_com_y_delta_m"],"returned_m":raw["returned_com_y_delta_m"],
                 "predictions":predictions,"peak_tilt_deg":raw["peak_tilt_deg"],
                 "max_motor_fraction":raw["peak_motor_fraction"],
                 "native_sha256":evidence.sha(out/(tag+"-native.json")),
                 "intent_sha256":evidence.sha(out/(tag+"-intent.json"))}
            evidence.write(out/(tag+"-receipt.json"),row)
            rows.append(row)
            return row
        for x,f in TRAIN:
            trial("train",x,f,{"prior":PRIOR_GAIN*x,"identity":x,"zero":0.})
        best,cv,models=choose_model(rows)
        frozen={"schema":SCHEMA,"chosen":best,"cv_training_mae_m":cv,
                "models":models,"fit_only_on_8_training_results":True,
                "training_receipts":[evidence.sha(out/f"trial-{i:02d}-receipt.json") for i in range(1,9)]}
        evidence.write(out/"frozen-world-model.json",frozen)
        fsha=evidence.sha(out/"frozen-world-model.json")
        test=[]
        for x,f in HOLDOUT:
            if evidence.sha(out/"frozen-world-model.json")!=fsha: raise ValueError("Model thawed")
            alternatives={k:estimate(k,c,x,f) for k,c in models.items()}
            forecast={"chosen":alternatives[best],"prior":PRIOR_GAIN*x,
                      "identity":x,"zero":0.,"alternate_hypotheses":alternatives}
            test.append(trial("holdout",x,f,forecast))
        if len(rows)!=MAX_RUNS or evidence.sha(out/"frozen-world-model.json")!=fsha:
            raise ValueError("Incomplete evaluation")
        metric=evaluate(test)
        ledger={"schema":"tadash-world-knowledge-ledger/1",
                "observed":{"native_trials":len(rows),"test_mae_m":metric["mae_m"],
                            "same_sign_as_command":metric["criteria"]["predicted_direction_correct"],
                            "returned_to_origin":metric["criteria"]["returned_to_center_within_0_1mm"]},
                "hypothesized":{"alternatives":KINDS,"training_only_choice":best,
                                "crossvalidation_mae":cv},
                "refutable_claim":{"beats_prior_by_10_percent":
                    metric["criteria"]["better_than_prior_by_10_percent"]},
                "unknown":["uneven terrain","new contact types","sensor noise",
                           "general navigation","subjective experience"],
                "creative_next_question":"Does prediction uncertainty rise near loss of foot contact? Not tested.",
                "narrative":"Within this small simulated world, lateral commands shift my modeled center of mass; the size and limits must be measured, never invented."}
        evidence.write(out/"knowledge-ledger.json",ledger)
        summary={"schema":SCHEMA,"status":"complete","native_trials":len(rows),"training":len(TRAIN),
                 "holdout":len(test),"selected":best,"metrics":metric,
                 "knowledge":ledger,"frozen_world_sha256":fsha,"plan_sha256":plan_sha,
                 "no_model_weights_or_native_sources_modified":True}
        evidence.write(out/"summary.json",summary)
        evidence.write(out/"status.json",{"status":"complete","summary_sha256":evidence.sha(out/"summary.json")},replace=True)
        return summary
    except BaseException as error:
        evidence.write(out/"status.json",{"status":"failed_or_unknown","completed_trials":len(rows),
                                         "error_type":type(error).__name__,
                                         "no_automatic_retry":True},replace=True)
        raise


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--motion-source",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--timeout",type=int,default=240)
    a=ap.parse_args()
    print(json.dumps(run(a.motion_source,a.output,a.timeout),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
