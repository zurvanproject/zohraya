"""Bounded native Tadash affect/action bridge with actual MuJoCo feedback.

Frozen synthetic context labels become *authored motor task labels*, not measured
emotions. Four action mappings each run against real pinned v03 physics, updating
a persistent table from native tracking errors. The learned table is frozen
before tests on slightly changed targets and friction. Every heldout policy arm
is run separately in native physics; no synthetic rewards are scored here.

It is a scoped hardware-free controller-selection experiment, not sentience,
autonomous behavior, a changed ChatGPT model, or general motor learning.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import sqlite3
from pathlib import Path
import subprocess
import sys

from experiments import tadash_motion_episode as evidence
from experiments import tadash_weight_shift as native
from experiments import tadash_affect_decision_learning as prior

SCHEMA = "tadash-native-affect-motor-reversal/2"
MOTOR_AUDIT_SCHEMA = "tadash-motor-learning-independent-audit/1"
POLICY_AUDIT_SCHEMA = "tadash-affect-decision-learning-audit/1"
TRAIN_FRICTION = 0.6
# REVERSED TASK v0.2: research-assigned target labels deliberately differ from
# the prior synthetic preference mapping; this is NOT an emotional stimulus.
CONTEXT_TARGETS = {"curious": .001, "frustrated": .003, "tired": .002, "steady": 0.}
ACTION_NOMINAL_M = {"explore": .003, "repeat": .002, "simplify": .001, "rest": 0.}
HOLDOUT_OFFSETS = (+.00015, -.00015)
HOLDOUT_FRICTIONS = (.50, .55)
MAX_TRIALS = 40
REWARD_SCALE_M = .004
MIN_GAIN_REPEAT = .08
MIN_GAIN_PRIOR = .08
MIN_WINS_REPEAT = 5


def load_inputs(motor_path, policy_path):
    motor_doc = evidence.read(motor_path)
    policy_doc = evidence.read(policy_path)
    if (motor_doc.get("schema") != MOTOR_AUDIT_SCHEMA or motor_doc.get("workflow_run_id") != 41484110737
            or motor_doc.get("model_source_commit") != evidence.MOTION_COMMIT
            or motor_doc.get("all_conditions_met") is not True
            or motor_doc.get("native_trials") != 19):
        raise ValueError("Unverified motor gain provenance")
    gain = evidence.finite(motor_doc.get("trained_command_gain"))
    if not 1.0 < gain < 1.3:
        raise ValueError("Out-of-bounds previous command calibration")
    if (policy_doc.get("schema") != POLICY_AUDIT_SCHEMA or
            policy_doc.get("workflow_run_id") != 41497413001 or
            policy_doc.get("training", {}).get("feedback_source") !=
            "authored synthetic fixture, not native body" or
            set(policy_doc.get("learned_policy", {})) != set(CONTEXT_TARGETS) or
            set(policy_doc["learned_policy"].values()) != set(ACTION_NOMINAL_M)):
        raise ValueError("Wrong prior synthetic policy audit")
    for label in CONTEXT_TARGETS:
        if prior.context(prior.CONTEXTS[label]) != label:
            raise ValueError("Prior affect context mapping changed")
    return {"motor_audit_sha256": evidence.sha(motor_path),
            "policy_audit_sha256": evidence.sha(policy_path),
            "command_gain": gain, "prior_policy": policy_doc["learned_policy"]}


def native_reward(target, observed):
    target = evidence.finite(target)
    observed = evidence.finite(observed)
    if abs(target) > .0032:
        raise ValueError("Unsafe desired target")
    return max(0., 1. - abs(observed-target)/REWARD_SCALE_M)


class Feedback:
    """Durable scalar motor-feedback training; NEVER reads holdouts for fitting."""
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        self.db.execute("CREATE TABLE IF NOT EXISTS q (context TEXT, action TEXT, count INTEGER, mean REAL, PRIMARY KEY(context,action))")
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, ctx TEXT NOT NULL, action TEXT NOT NULL, reward REAL NOT NULL, native_sha TEXT NOT NULL)")
        for c in CONTEXT_TARGETS:
            for a in ACTION_NOMINAL_M:
                self.db.execute("INSERT OR IGNORE INTO q VALUES(?,?,0,0.0)",(c,a))

    def learn(self, identifier, ctx, action, reward, raw_sha):
        if ctx not in CONTEXT_TARGETS or action not in ACTION_NOMINAL_M:
            raise ValueError("Unknown context or motor action")
        if type(identifier) is not str or not identifier.startswith("training-"):
            raise ValueError("Only training identifiers may update motor policy")
        if not 0. <= evidence.finite(reward) <= 1.:
            raise ValueError("Invalid motor feedback")
        if not isinstance(raw_sha,str) or len(raw_sha)!=64:
            raise ValueError("Missing raw native receipt digest")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT ctx,action,reward,native_sha FROM receipts WHERE id=?", (identifier,)).fetchone()
            if old is not None:
                if old != (ctx,action,reward,raw_sha):
                    raise ValueError("Conflicting motor feedback replay")
                self.db.execute("COMMIT")
                return False
            n,m = self.db.execute("SELECT count,mean FROM q WHERE context=? AND action=?", (ctx,action)).fetchone()
            self.db.execute("UPDATE q SET count=?,mean=? WHERE context=? AND action=?",
                            (n+1,m+(reward-m)/(n+1),ctx,action))
            self.db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)",(identifier,ctx,action,reward,raw_sha))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def freeze(self):
        rows=self.db.execute("SELECT context,action,count,mean FROM q ORDER BY context,action").fetchall()
        if len(rows)!=16 or any(n!=1 for c,a,n,v in rows) or self.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]!=16:
            raise ValueError("Incomplete or duplicated native motor training")
        q = {c:{} for c in CONTEXT_TARGETS}
        for c,a,n,value in rows:
            if not 0. <= evidence.finite(value) <= 1.:
                raise ValueError("Invalid stored motor reward")
            q[c][a] = value
        policy={c:max(ACTION_NOMINAL_M,key=lambda a:(q[c][a],-list(ACTION_NOMINAL_M).index(a)))
                for c in CONTEXT_TARGETS}
        return {"schema":"tadash-native-feedback-policy/1", "q_native":q, "policy":policy,
                "native_feedback_receipts":16, "frozen_before_holdout":True}
    def close(self):
        self.db.close()


def score_pairs(pairs):
    if len(pairs)!=8 or set(x["context"] for x in pairs)!=set(CONTEXT_TARGETS):
        raise ValueError("Incomplete held-out contexts")
    means={arm:sum(evidence.finite(x["reward"][arm]) for x in pairs)/len(pairs)
           for arm in ("native_learned","always_repeat","prior_synthetic")}
    wins = sum(x["reward"]["native_learned"] > x["reward"]["always_repeat"]+1e-10 for x in pairs)
    vs_old = sum(x["reward"]["native_learned"] > x["reward"]["prior_synthetic"]+1e-10 for x in pairs)
    gates={"native_learned_vs_repeat_gain_0.08": means["native_learned"]-means["always_repeat"]>=MIN_GAIN_REPEAT,
           "native_learned_vs_repeat_wins_at_least_5":wins>=MIN_WINS_REPEAT,
           "novel_policy_gain_over_prior_synthetic_0.01":means["native_learned"]-means["prior_synthetic"]>=MIN_GAIN_PRIOR}
    return {"holdout_reward_mean":means,"wins_vs_repeat":wins,"wins_vs_prior":vs_old,
            "predeclared_gates":gates,
            "better_than_repeat":gates["native_learned_vs_repeat_gain_0.08"] and gates["native_learned_vs_repeat_wins_at_least_5"],
            "new_decision_learning_beyond_prior_demonstrated":all(gates.values())}


def run(source, output, motor_audit, policy_audit, timeout=240):
    source,output=Path(source).resolve(),Path(output).resolve()
    if source==output or output.is_relative_to(source):
        raise ValueError("Experiment output overlaps pinned body")
    if type(timeout) is not int or not 30<=timeout<=600:
        raise ValueError("Bad timeout")
    identity=evidence.source_identity(source)
    inputs=load_inputs(motor_audit,policy_audit)
    scriptsha=evidence.sha(Path(__file__))
    parentsha=evidence.sha(Path(native.__file__))
    output.mkdir(parents=True,exist_ok=False)
    plan={"schema":SCHEMA,"source":identity,"audits":inputs,"script_sha256":scriptsha,
          "native_wrapper_sha256":parentsha,
          "contexts":CONTEXT_TARGETS,"actions_m":ACTION_NOMINAL_M,
          "training_friction":TRAIN_FRICTION,
          "holdout_target_offsets_m":HOLDOUT_OFFSETS,
          "holdout_friction":HOLDOUT_FRICTIONS,
          "reward":"1-abs(measured held COM - desired goal)/4mm, clamped 0..1",
          "train_native_trials":16,"holdout_native_trials":24,"max_native_trials":MAX_TRIALS,
          "minimum_gain_over_repeat":MIN_GAIN_REPEAT,"minimum_gain_over_prior":MIN_GAIN_PRIOR,
          "minimum_wins_over_repeat":MIN_WINS_REPEAT,
          "limit":"hand-authored context-to-motor-goal; fixed command menu; deterministic MuJoCo; no autonomous actuator"}
    evidence.write(output/"plan.json",plan)
    plan_sha=evidence.sha(output/"plan.json")
    evidence.write(output/"status.json",{"status":"running","utc":datetime.now(timezone.utc).isoformat()})
    db=None
    completed=[]
    try:
        db=Feedback(output/"native-feedback.sqlite")
        def motor_trial(phase,ctx,action,target,friction,arm):
            if len(completed)>=MAX_TRIALS:
                raise ValueError("Native trial cap exceeded")
            if (evidence.source_identity(source)!=identity or evidence.sha(Path(__file__))!=scriptsha or
                    evidence.sha(Path(native.__file__))!=parentsha or evidence.sha(output/"plan.json")!=plan_sha):
                raise ValueError("Frozen source or contract drift")
            if ctx not in CONTEXT_TARGETS or action not in ACTION_NOMINAL_M:
                raise ValueError("Unexpected action")
            applied = ACTION_NOMINAL_M[action]*inputs["command_gain"]
            if not 0 <= applied <= .0035:
                raise ValueError("Command beyond limited mechanical range")
            tag=f"trial-{len(completed)+1:02d}"
            intent={"schema":"tadash-native-affect-intent/1","phase":phase,"context":ctx,"arm":arm,
                    "action":action,"desired_m":target,"applied_command_m":applied,
                    "friction":friction,"plan_sha256":plan_sha}
            evidence.write(output/(tag+"-intent.json"),intent)
            try:
                p=subprocess.run([sys.executable,"-c",native.NATIVE,str(applied),str(friction)],
                                 cwd=source,env=evidence.clean_env(),capture_output=True,text=True,
                                 check=False,timeout=timeout)
            except subprocess.TimeoutExpired as ex:
                raise TimeoutError("Unknown native motor outcome; no retry permitted") from ex
            (output/(tag+".stdout.log")).write_text(p.stdout)
            (output/(tag+".stderr.log")).write_text(p.stderr)
            if p.returncode:
                raise RuntimeError("Native motor exited abnormally, no auto retry")
            raw=json.loads(p.stdout,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
            evidence.write(output/(tag+"-native.json"),raw)
            native.validate(raw,applied)
            if raw.get("friction")!=friction:
                raise ValueError("Friction evidence mismatch")
            reward=native_reward(target,raw["held_com_y_delta_m"])
            row={"id":tag,"phase":phase,"context":ctx,"arm":arm,"action":action,
                 "target_m":target,"applied_m":applied,"friction":friction,"reward":reward,
                 "observed_com_m":raw["held_com_y_delta_m"],
                 "native_sha256":evidence.sha(output/(tag+"-native.json")),
                 "intent_sha256":evidence.sha(output/(tag+"-intent.json")),
                 "peak_motor_fraction":raw["peak_motor_fraction"],
                 "peak_tilt_deg":raw["peak_tilt_deg"],"return_delta_m":raw["returned_com_y_delta_m"]}
            evidence.write(output/(tag+"-receipt.json"),row)
            completed.append(row)
            return row
        for label,goal in CONTEXT_TARGETS.items():
            for action in ACTION_NOMINAL_M:
                row=motor_trial("train",label,action,goal,TRAIN_FRICTION,"independent_full_action_feedback")
                db.learn("training-"+row["id"],label,action,row["reward"],row["native_sha256"])
        learned=db.freeze()
        evidence.write(output/"frozen-native-policy.json",learned)
        frozen_sha=evidence.sha(output/"frozen-native-policy.json")
        db.close();db=None
        cold=Feedback(output/"native-feedback.sqlite")
        try:
            recovered=cold.freeze()
        finally:
            cold.close()
        if learned!=recovered:
            raise ValueError("Cold restart lost native feedback learning")
        paired=[]
        for idx,(friction,delta) in enumerate(zip(HOLDOUT_FRICTIONS,HOLDOUT_OFFSETS)):
            for ctx,goal in CONTEXT_TARGETS.items():
                desired=goal+delta
                selection={"native_learned":learned["policy"][ctx],
                           "always_repeat":"repeat",
                           "prior_synthetic":inputs["prior_policy"][ctx]}
                arms=list(selection)
                if (idx+list(CONTEXT_TARGETS).index(ctx))%2:
                    arms.reverse()
                evidence.write(output/f"holdout-intent-{idx}-{ctx}.json",
                               {"context":ctx,"goal_m":desired,"friction":friction,
                                "choices_frozen":selection,"model_sha256":frozen_sha})
                samples={}
                for arm in arms:
                    samples[arm]=motor_trial("holdout",ctx,selection[arm],desired,friction,arm)
                paired.append({"context":ctx,"goal_m":desired,"friction":friction,
                               "actions":selection,"reward":{arm:samples[arm]["reward"] for arm in selection},
                               "raw_receipts":{arm:samples[arm]["native_sha256"] for arm in selection}})
        if len(completed)!=MAX_TRIALS or evidence.sha(output/"frozen-native-policy.json")!=frozen_sha:
            raise ValueError("Incomplete trial set or policy altered on holdout")
        metrics=score_pairs(paired)
        summary={"schema":SCHEMA,"status":"complete","native_trials":len(completed),
                 "native_training_trials":16,"heldout_pairs":8,
                 "prior_synthetic_policy":inputs["prior_policy"],
                 "native_learned_policy":learned["policy"],
                 "policy_changed_vs_prior":learned["policy"]!=inputs["prior_policy"],
                 "metrics":metrics,"source_identity":identity,
                 "plan_sha256":plan_sha,"frozen_native_policy_sha256":frozen_sha,
                 "cold_recovered":True,"main_or_chatgpt_changed":False,
                 "claim":"narrow native sensory motor reward table, not true emotions or general autonomy"}
        evidence.write(output/"summary.json",summary)
        evidence.write(output/"status.json",{"status":"complete",
                       "summary_sha256":evidence.sha(output/"summary.json")},replace=True)
        return summary
    except BaseException as e:
        evidence.write(output/"status.json",{"status":"failed_or_unknown",
                       "error_type":type(e).__name__,
                       "completed_trials":len(completed),
                       "no_automatic_retry":True},replace=True)
        raise
    finally:
        if db is not None: db.close()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--motion-source",type=Path,required=True)
    ap.add_argument("--motor-audit",type=Path,required=True)
    ap.add_argument("--policy-audit",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--timeout",type=int,default=240)
    a=ap.parse_args()
    print(json.dumps(run(a.motion_source,a.output,a.motor_audit,a.policy_audit,a.timeout),
                     ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
