"""Convert a matching authenticated bridge receipt into bounded model-tool data."""
import math
import re

GOAL_ID="nasuraya-review-20261107-v1"


def parse_reply(comment, request_id):
    if comment.get("user",{}).get("login")!="zurvanproject":
        raise ValueError("untrusted result author")
    match=re.fullmatch(
        r"Nasuraya Bridge v2 result; request_id=comment-"+str(request_id)+
        r"; command=run tadash_goal_call\r?\nResult: OK ([a-zA-Z0-9 .,:;=/_()+-]{1,180})",
        comment.get("body",""))
    if not match:
        raise ValueError("missing exact request/result identity")
    fields={}
    for item in match.group(1).split(";"):
        key,separator,value=item.partition("=")
        if not separator or key in fields:
            raise ValueError("invalid public result field")
        fields[key]=value
    expected={"G","N","R","E","F","P","S","Q","D","A","MEM","X","SIG","PHY"}
    if set(fields)!=expected:
        raise ValueError("missing or rejected native result")
    if fields["G"] not in ("ACTIVE","DONE") or not re.fullmatch(r"[0-3]/3",fields["N"]):
        raise ValueError("invalid goal count")
    count=int(fields["N"][0])
    if (fields["G"]=="DONE")!=(count==3):
        raise ValueError("goal completion mismatch")
    if fields["X"]!="0" or fields["PHY"]!="0" or not re.fullmatch(r"[0-9a-f]{16}",fields["SIG"]):
        raise ValueError("invalid replay or scope evidence")
    for name in ("Q","D","A"):
        if fields[name] not in ("none","walk","observe","protect"):
            raise ValueError("unknown native action")
    state={name:float(fields[key]) for name,key in
           (("energy","E"),("fatigue","F"),("pain","P"),("sleep_pressure","S"))}
    if any(not math.isfinite(x) or not 0<=x<=1 for x in state.values()):
        raise ValueError("nonfinite or out of range observation")
    for key in ("R","MEM"):
        if not re.fullmatch(r"[0-9]{1,5}",fields[key]):
            raise ValueError("invalid native count")
    return {"goal_id":GOAL_ID,"goal_complete":count==3,"goal_cycles_completed":count,
            "goal_cycle_limit":3,"body_revision":int(fields["R"]),
            "state":state,"measurement_precision":0.001,
            "model_requested_action":fields["Q"],"native_selected_action":fields["D"],
            "actual_action":fields["A"],"feedback_recalled":int(fields["MEM"]),
            "checkpoint_sha256_prefix":fields["SIG"],"replay_extra_cycles":0,
            "physical_actuation":False,"scope":"generated software-body fixture",
            "bridge_request_id":request_id,"bridge_reply_id":comment["id"]}

