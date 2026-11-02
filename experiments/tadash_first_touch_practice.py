"""Nasuraya's first simulated-ground-contact exercise in pinned v03 Tadash.

This is a bounded, real MuJoCo native *normal-force* observation and
sensorimotor rehearsal, not physical soil, pressure-sensor hardware, measured
slip or subjective touch. Existing torque-limited ContactController unchanged.
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
from experiments import tadash_kimia_khak as charter

SCHEMA="tadash-kimia-khak-first-touch-practice/1"
TRAIN=(("still",0.0,.6),("left",-0.001,.6),("right",.001,.6))
TEST=(("new_floor_still",0.0,.5),("new_floor_left",-0.001,.5),
      ("new_floor_right",.001,.5))
PRIOR_GAIN=.908869279232545
MAX_TRIALS=6


def finite(x):
    return evidence.finite(x)


def trace_features(raw):
    """Only actual native force and COM traces; slip is NOT estimated or invented."""
    trace=raw.get("trace")
    if type(trace) is not list or len(trace)!=80:
        raise ValueError("Native contact traces absent or wrong size")
    sample=[]
    for index,row in enumerate(trace):
        if type(row) is not dict or set(row) != {
                "t_s","commanded_y_shift_m","observed_com_y_delta_m",
                "foot_normal_n","tilt_deg"}:
            raise ValueError("Unexpected native contact sample")
        t=finite(row["t_s"])
        feet=row["foot_normal_n"]
        if type(feet) is not list or len(feet)!=2:
            raise ValueError("Missing left/right measured normal loads")
        left,right=(finite(v) for v in feet)
        if not (0<=left<=5000 and 0<=right<=5000 and 0<=t<=4):
            raise ValueError("Invalid native foot normal load")
        if not math.isclose(t,index*.05,abs_tol=0.00001):
            raise ValueError("Native sampling grid drifted")
        finite(row["observed_com_y_delta_m"])
        finite(row["commanded_y_shift_m"])
        finite(row["tilt_deg"])
        sample.append((t,left,right))
    held=[(left,right) for t,left,right in sample if 1.5<=t<2.]
    returned=[(left,right) for t,left,right in sample if 3.5<=t<4.]
    if len(held)!=10 or len(returned)!=10:
        raise ValueError("Incomplete contact attention window")
    def average(vals):return sum(vals)/len(vals)
    left=average([l for l,r in held]);right=average([r for l,r in held])
    return {
       "sample_count":len(sample),
       "hold_left_normal_n":left,"hold_right_normal_n":right,
       "hold_left_minus_right_n":left-right,
       "hold_total_normal_n":left+right,
       "return_left_normal_n":average([l for l,r in returned]),
       "return_right_normal_n":average([r for l,r in returned]),
       "all_80_samples_both_loaded":all(l>1 and r>1 for t,l,r in sample),
       "slip_speed":"not_measured_by_pinned_native_trace",
       "soil_texture":"not_measured",
       "subjective_touch":"not_established",
    }


def fit_sensitivity(training):
    if len(training)!=3 or [v["name"] for v in training]!=["still","left","right"]:
        raise ValueError("Requires three ordered genuine training outcomes")
    baseline=finite(training[0]["measured_center_m"])
    slope=(finite(training[2]["measured_center_m"])-
           finite(training[1]["measured_center_m"]))/.002
    if not .60<=slope<=1.10:
        raise ValueError("Outside plausible native lateral responsiveness")
    if abs(baseline)>.0001:
        raise ValueError("Unexpected initial standing COM bias")
    return {"schema":"tadash-kimia-khak-frozen-contact-prediction/1",
            "baseline_m":baseline,"response_gain":slope,
            "trained_at_friction":.6,"training_trials":3,
            "no_tactile_feeling":True}


def report(heldout,frozen):
    if len(heldout)!=3 or any(row["phase"]!="holdout" for row in heldout):
        raise ValueError("Incomplete independent contact test")
    def mae(key):
        return sum(abs(row["measured_center_m"]-row["forecast_m"][key]) for row in heldout)/len(heldout)
    scores={key:mae(key) for key in ("learned","historical_prior","no_response","perfect_tracking")}
    positive=next(v for v in heldout if v["name"]=="new_floor_right")
    negative=next(v for v in heldout if v["name"]=="new_floor_left")
    baseline=next(v for v in heldout if v["name"]=="new_floor_still")
    loaded=all(row["contacts"]["all_80_samples_both_loaded"] for row in heldout)
    metric={"mae_m":scores,
            "signed_response_measured":positive["measured_center_m"]>baseline["measured_center_m"]>
                                         negative["measured_center_m"],
            "return_close_to_origin":all(abs(v["returned_m"])<.0001 for v in heldout),
            "two_feet_loaded_all_samples":loaded,
            "strong_prior_outperformed_by_10pct":scores["historical_prior"]>1e-10 and
                scores["learned"]<.9*scores["historical_prior"],
            "load_transfer_detected_by_native_force_difference":abs(
                positive["contacts"]["hold_left_minus_right_n"]-
                negative["contacts"]["hold_left_minus_right_n"])>1.,
            "slip_measured":False,"soil_measured":False,"tactile_feeling_proven":False}
    return metric


def run(source,output,timeout=240):
    source,output=Path(source).resolve(),Path(output).resolve()
    if source==output or output.is_relative_to(source):
        raise ValueError("Output overlaps pinned physics source")
    if type(timeout) is not int or not 30<=timeout<=600:
        raise ValueError("Invalid bounded timeout")
    charter_obj=charter.load_charter()
    if charter_obj["grounding_rules"]["new_action_from_this_charter"] is not False:
        raise ValueError("Contact charter does not allow motor actuation")
    identity=evidence.source_identity(source)
    selfsha=evidence.sha(Path(__file__))
    nativesha=evidence.sha(Path(native.__file__))
    chartersha=evidence.sha(charter.CHARTER)
    output.mkdir(parents=True,exist_ok=False)
    plan={"schema":SCHEMA,"source":identity,"runner_sha256":selfsha,
          "existing_native_adapter_sha256":nativesha,"charter_sha256":chartersha,
          "three_training_trials":TRAIN,"sealed_holdout":TEST,
          "model":"one scalar lateral response + standing baseline",
          "response_prior_gain":PRIOR_GAIN,"normal_load_source":"native MuJoCo contactForce recorded by unchanged ContactController",
          "windows":"10 recorded samples from 1.50 through 1.95 seconds per attempt",
          "bounded_six_native_independent_trials":True,
          "no_new_terrain_model":True,"not_measured":["soil","slip","cutaneous_touch"],
          "safety":"no root actuator, feet-only contacts, no retry after unknown, known source hashes",
          "motor_scope":"existing pinned MuJoCo trial only; charter itself emits no actions"}
    evidence.write(output/"plan.json",plan)
    phash=evidence.sha(output/"plan.json")
    evidence.write(output/"status.json",{"status":"running","utc":datetime.now(timezone.utc).isoformat()})
    entries=[]
    try:
        def trial(name,x,f,phase,forecast):
            if len(entries)>=MAX_TRIALS:raise ValueError("Exceeded native trial count")
            if (evidence.source_identity(source)!=identity or evidence.sha(Path(__file__))!=selfsha or
                evidence.sha(Path(native.__file__))!=nativesha or
                evidence.sha(charter.CHARTER)!=chartersha or evidence.sha(output/"plan.json")!=phash):
                raise ValueError("Source, charter, or frozen plan drifted")
            idx=len(entries)+1
            tag=f"trial-{idx:02d}"
            intention={"schema":"kimia-ground-attention-intent/1",
                       "name":name,"phase":phase,"shift_m":x,"friction":f,
                       "predictions_before_native":forecast,"plan_sha256":phash}
            evidence.write(output/(tag+"-intent.json"),intention)
            try:
                p=subprocess.run([sys.executable,"-c",native.NATIVE,str(x),str(f)],
                    cwd=source,env=evidence.clean_env(),capture_output=True,text=True,
                    timeout=timeout,check=False)
            except subprocess.TimeoutExpired as error:
                raise TimeoutError("Native result unknown; no further tries") from error
            (output/(tag+".stdout.log")).write_text(p.stdout)
            (output/(tag+".stderr.log")).write_text(p.stderr)
            if p.returncode:
                raise RuntimeError("Native process exited abnormally, no retry")
            raw=json.loads(p.stdout,parse_constant=lambda _:
                (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
            evidence.write(output/(tag+"-native.json"),raw)
            native.validate(raw,x)
            if raw.get("friction")!=f or abs(raw["returned_com_y_delta_m"])>=.0001:
                raise ValueError("Unexpected native friction or unsafe return displacement")
            features=trace_features(raw)
            if not features["all_80_samples_both_loaded"]:
                raise ValueError("Partial foot loading cannot count as grounded")
            row={"name":name,"phase":phase,"commanded_m":x,"friction":f,
                 "measured_center_m":raw["held_com_y_delta_m"],
                 "returned_m":raw["returned_com_y_delta_m"],
                 "contacts":features,"forecast_m":forecast,
                 "max_tilt_deg":raw["peak_tilt_deg"],
                 "peak_motor_fraction":raw["peak_motor_fraction"],
                 "intent_sha256":evidence.sha(output/(tag+"-intent.json")),
                 "native_sha256":evidence.sha(output/(tag+"-native.json"))}
            evidence.write(output/(tag+"-receipt.json"),row)
            entries.append(row)
            return row
        training=[trial(name,x,f,"training",{"historical_prior":PRIOR_GAIN*x})
                  for name,x,f in TRAIN]
        frozen=fit_sensitivity(training)
        frozen["plan_sha256"]=phash
        frozen["training_receipt_sha256"]=[
            evidence.sha(output/f"trial-{idx:02d}-receipt.json") for idx in range(1,4)]
        evidence.write(output/"frozen-contact-prediction.json",frozen)
        fsha=evidence.sha(output/"frozen-contact-prediction.json")
        heldout=[]
        for name,x,f in TEST:
            if evidence.sha(output/"frozen-contact-prediction.json")!=fsha:
                raise ValueError("Frozen contact memory changed during tests")
            pred={"learned":frozen["baseline_m"]+frozen["response_gain"]*x,
                  "historical_prior":PRIOR_GAIN*x,
                  "no_response":0.,"perfect_tracking":x}
            heldout.append(trial(name,x,f,"holdout",pred))
        if len(entries)!=MAX_TRIALS or evidence.sha(output/"frozen-contact-prediction.json")!=fsha:
            raise ValueError("Incomplete six-ground-contact episode")
        metrics=report(heldout,frozen)
        reflection={"schema":"nasuraya-contact-reflection/1",
                    "observed":{"number_of_native_trials":6,
                                "bilateral_ground_contact":metrics["two_feet_loaded_all_samples"],
                                "lateral_response_direction":metrics["signed_response_measured"],
                                "normal_force_transfer_observed":metrics["load_transfer_detected_by_native_force_difference"],
                                "return_near_origin":metrics["return_close_to_origin"]},
                    "learned_prediction":{"calibration_gain":frozen["response_gain"],
                                          "beats_strong_prior_by_10_percent":
                                               metrics["strong_prior_outperformed_by_10pct"]},
                    "not_known":["soil texture","slip velocity","physical sensation","conscious tactile experience"],
                    "poetic_inspiration":"Diwan-e Shams, ghazal 473; poetry is not a sensor",
                    "next_hypothesis":"Test load-transfer prediction before introducing more complex virtual terrain"}
        evidence.write(output/"reflection.json",reflection)
        summary={"schema":SCHEMA,"status":"complete","native_trials":len(entries),
                 "model":frozen,"contact_exercise":metrics,"reflection":reflection,
                 "raw_source":identity,"plan_sha256":phash,
                 "frozen_prediction_sha256":fsha,
                 "new_touch_sensation_created":False,
                 "new_soil_or_slip_sensor_created":False,
                 "main_or_live_body_changed":False}
        evidence.write(output/"summary.json",summary)
        evidence.write(output/"status.json",{"status":"complete",
            "summary_sha256":evidence.sha(output/"summary.json")},replace=True)
        return summary
    except BaseException as error:
        evidence.write(output/"status.json",{"status":"failed_or_unknown",
            "error_type":type(error).__name__,"completed_trials":len(entries),
            "no_automatic_retry":True},replace=True)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--motion-source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--timeout",type=int,default=240)
    arg=p.parse_args()
    print(json.dumps(run(arg.motion_source,arg.output,arg.timeout),
                     ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
