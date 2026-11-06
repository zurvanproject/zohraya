"""One-owner whole-body integration for the existing Tadash software body.

The retained V09 plant owns fuel, reserve, water, material, heat and gas. New
gut and bladder compartments are included in an outer conservation audit.
Hormone/cell/immune/reproductive indices are explicit uncalibrated proxies.
97 anatomical nodes receive regional projections, not 97 independent organ
solvers. A retained six-cell circuit runs on the same simulated time grid.
"""
from __future__ import annotations

import argparse
import fcntl
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "retained_extensions"))
from neural_circuit import Circuit
import nasuraya_affective_layer_v01 as affect
import nasuraya_emotion_spectrum_v01 as spectrum
import special_physiology_v1 as special_physiology
from persistent_embodiment_v1 import (PersistentEmbodiment, AccessoryBody,
    ACTIONS, atomic_json, digest, finite, instant, clamp)
from actuated_breath_v1 import ActuatedBreath
from renal_physiology_v09 import RenalInputs

SCHEMA = "nasuraya-whole-body/2.0"
TTL_S = 5.0
ROUTES = {
    "blood_to_oxygen", "immune_to_metabolic", "gut_to_fuel",
    "resonan_to_energy", "neural_to_motor", "body_to_affect",
    "affect_to_autonomic", "kidney_to_bladder", "spandar_to_decision",
    "endocrine_to_metabolic",
}
STAGE_KEYS = {1:"endocrine", 2:"blood", 3:"renal", 4:"immune",
    5:"cardiorespiratory", 6:"gut", 7:"senses", 8:"mouth",
    9:"reproductive", 10:"musculoskeletal", 11:"neural", 12:"special"}
CAPACITY_KEYS = {"heart", "lung", "kidney", "gut", "liver", "immune", "ovary"}


def source_hashes():
    names = ["unified_body_v2.py", "anatomy_systems_v01.json", "special_physiology_v1.py"]
    names += ["retained_extensions/" + n for n in (
        "neural_circuit.py", "nasuraya_affective_layer_v01.py",
        "nasuraya_emotion_spectrum_v01.py", "nasuraya_decision_core_v1.py")]
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


def relax(x, target, dt, tau):
    return x + (1.0-math.exp(-dt/tau))*(target-x)


def native_total(body):
    s = body.state
    return s.fuel_J+s.reserve_J+s.heat_J+s.repaired_kg*10000.0


def lumen_energy(m):
    return m["gut"]["mouth_J"]+m["gut"]["stomach_J"]


def lumen_water(m):
    return m["gut"]["mouth_water_L"]+m["gut"]["stomach_water_L"]


def initial_modules(owner, neural):
    return {
        "endocrine": dict(adh=owner.owner.renal.state["water_signal"],
            acth=.2, cortisol=.2, thyroid=.5, insulin=.5, glucagon=.5, epo=.1),
        "blood": dict(rbc_capacity=1.0, hemostasis=.8),
        "immune": dict(pathogen_index=0.0, inflammation=0.0, lymph_load=0.0),
        "gut": dict(mouth_J=0.0, stomach_J=0.0, mouth_water_L=0.0,
            stomach_water_L=0.0, total_absorbed_J=0.0, total_absorbed_water_L=0.0),
        "renal": dict(bladder_L=0.0, voided_L=0.0),
        "mouth": dict(swallow_open=True, phonation=0.0),
        "reproductive": dict(gonadotropin=.5, estrogen=.5, progesterone=.5),
        "neural": dict(circuit=neural.payload(), origin_tick=neural.tick,
            integration_ticks=0, attention_hz=0.0, regulation_hz=0.0,
            optional_motor_fraction=1.0, encoding="declared interoceptive encoding on existing toy ports"),
        "senses": dict(samples={}, expired=[], irradiance=None),
        "special": dict(resonan_attention=0.0, shutter=1.0,
            spandar_digest=digest(owner.aux["body_memory"]), spandar_last_error=0.0,
            azarine_budget_J=min(7200.0, owner.owner.body.state.reserve_J),
            azarine_pool="tagged ceiling within the retained reserve_J; not an extra stock"),
        "outputs": {}, "tick":0, "origin_time_s":owner.owner.body.state.time_s,
        "published_packets":0, "last_paid_W":{}, "last_requests_W":{},
        "source_scope":"new indices initialized explicitly; retained physical stocks unchanged",
    }


def rates(context, body, i, dt):
    """Prepare from one previous snapshot. Outputs affect the following tick."""
    m, env, disabled = context["modules"], context["environment"], context["disabled"]
    s = body.state
    caps = env.get("capacities", {})
    cap = lambda key: caps.get(key, 1.0)
    immune = m["immune"]["inflammation"]
    demand = dict(endocrine=2.0+2.0*m["endocrine"]["thyroid"], blood=1.0,
        immune=1.0+8.0*immune, gut=1.0+2.0*float(lumen_energy(m)>0),
        reproductive=.5, neural=2.0, special=.2, mouth=1.5*float(env.get("voice_request",False)))
    if "endocrine_to_metabolic" in disabled: demand["endocrine"]=2.0
    if "immune_to_metabolic" in disabled: demand["immune"]=1.0
    gut = m["gut"]
    # Swallowing and absorption are separate, paid stages. Admission occurs
    # below after the actual metabolism grant, without conjuring stored fuel.
    swallowing = bool(env.get("swallow_permitted",True) and i.ventilation_ok
                      and context["airway_capacity"]>.4)
    portal = cap("gut")*cap("liver")*min(1.0,s.free_water_L/110.0)
    absorbed = min(gut["stomach_J"], 2000.0*portal*dt, gut["stomach_J"]*dt/30.0)
    water = min(gut["stomach_water_L"], .01*portal*dt)
    if "gut_to_fuel" in disabled: absorbed=water=0.0
    irradiance = m["senses"]["irradiance"]
    incident_W = 0.0 if irradiance is None else irradiance*.02
    # Explicit fictional light transduction: compact 0.02 m2 area, 12%
    # chemical storage, 58% body heat, 30% rejection; no deployed photoveil.
    temperature = 37.0+s.heat_J/(195.0*3500.0)
    shutter = clamp((37.4-temperature)/.2)
    if m["special"]["resonan_attention"]>.95: shutter*=.25
    if "resonan_to_energy" in disabled: shutter=0.0
    photo_W=incident_W*.12*shutter
    thermal_W=incident_W*.58*shutter
    rejected_W=incident_W-photo_W-thermal_W
    tissue_plan = None
    if "tissue" in m["special"]:
        tissue_plan = special_physiology.plan(m["special"]["tissue"],
            env.get("special_physiology", {}), irradiance, temperature,
            disabled, s.reserve_J, dt)
        lobes = tissue_plan["lobes"].values()
        incident_W = sum(x["incident_W"] for x in lobes)
        photo_W = sum(x["photo_W"] for x in lobes)
        thermal_W = sum(x["thermal_W"] for x in lobes)
        rejected_W = incident_W - photo_W - thermal_W
        shutter = sum(x["shutter"] for x in lobes) / 2
        demand["special"] += tissue_plan["azarine_load_W"]
    requests=sum(demand.values())
    hydration=max(.5,min(1.0,s.free_water_L/110.0))
    table=body.table[str(round(math.floor((hydration+1e-9)*10)/10,1))]
    oxygen_W=table["flow_L_min"]*.20*.65*20000/60*i.oxygen_fraction
    # Native vital/respiratory/renal/postural work keeps priority. The 20 W
    # renal headroom is a conservative accounting fixture, not physiology.
    headroom=max(0.0,min(oxygen_W,i.aerobic_limit_W,s.fuel_J/dt)
        -177.0-table["pump_extra_metabolic_W"]-i.respiratory_work_requested_W
        -body.accessory_requested_W-20.0)
    organ_W=min(requests,headroom)
    # Transport cannot outrun the budget granted to the supporting modules.
    transport_fraction=organ_W/requests if requests else 0.0
    absorbed*=transport_fraction;water*=transport_fraction
    return dict(demand=demand,organ_W=organ_W,absorbed_J=absorbed,
        absorbed_water_L=water,swallowing=swallowing,incident_W=incident_W,
        photo_W=photo_W,thermal_W=thermal_W,rejected_W=rejected_W,shutter=shutter,tissue_plan=tissue_plan)


def settle(context, body, f, plan):
    m, env = context["modules"], context["environment"]
    dt=f["ledger"]["dt_s"]; s=body.state
    old=deepcopy({k:m[k] for k in ("endocrine","blood","immune","reproductive")})
    oxygen=f["circulation"]["oxygen_adequacy_proxy"]
    hydration=clamp(s.free_water_L/110.0)
    energy=clamp(s.fuel_J/4000000.0)
    pain=f["pain"]["peak_intensity_proxy"]
    perfusion=clamp(f["circulation"]["Q_L_min"]/body.table["1.0"]["flow_L_min"])
    funded=clamp(f["organs"]["paid_W"]/max(1e-12,sum(plan["demand"].values())))
    d=dt*funded
    e=m["endocrine"]
    e["adh"]=body.renal.state["water_signal"]
    e["acth"]=relax(old["endocrine"]["acth"],clamp(.2+.5*pain+.3*old["immune"]["inflammation"]-.2*e["cortisol"]),d,15.0)
    e["cortisol"]=relax(old["endocrine"]["cortisol"],e["acth"],d,30.0)
    e["thyroid"]=relax(old["endocrine"]["thyroid"],clamp(.5*energy),d,90.0)
    e["insulin"]=relax(old["endocrine"]["insulin"],energy,d,20.0)
    e["glucagon"]=relax(old["endocrine"]["glucagon"],1.0-energy,d,20.0)
    e["epo"]=relax(old["endocrine"]["epo"],clamp(.1+1.5*(1.0-oxygen)),d,60.0)
    m["blood"]["rbc_capacity"]=clamp(old["blood"]["rbc_capacity"]+d*1e-6*(e["epo"]-.1))
    m["blood"]["hemostasis"]=relax(old["blood"]["hemostasis"],clamp(.8-.25*m["immune"]["inflammation"]),d,120.0)
    im=m["immune"]
    # Index decay, not a mass model of pathogens or clinical immune kinetics.
    clearance=env.get("capacities",{}).get("immune",1.0)*funded*perfusion
    im["pathogen_index"]=clamp(im["pathogen_index"]*math.exp(-dt*clearance/120.0))
    im["inflammation"]=relax(old["immune"]["inflammation"],clamp(im["pathogen_index"]+.4*pain),d,12.0)
    im["lymph_load"]=relax(old["immune"]["lymph_load"],im["inflammation"]*(1.0-.5*perfusion),d,30.0)
    gut=m["gut"]
    gut["stomach_J"]-=plan["absorbed_J"]
    gut["stomach_water_L"]-=plan["absorbed_water_L"]
    gut["total_absorbed_J"]+=plan["absorbed_J"]
    gut["total_absorbed_water_L"]+=plan["absorbed_water_L"]
    swallowed=min(gut["mouth_J"],5000.0*dt*funded) if plan["swallowing"] else 0.0
    swallowed_water=min(gut["mouth_water_L"],.05*dt*funded) if plan["swallowing"] else 0.0
    gut["mouth_J"]-=swallowed;gut["stomach_J"]+=swallowed
    gut["mouth_water_L"]-=swallowed_water;gut["stomach_water_L"]+=swallowed_water
    urine=f["ledger"]["urine_loss_L"]
    if "kidney_to_bladder" in context["disabled"]: m["renal"]["voided_L"]+=urine
    else: m["renal"]["bladder_L"]+=urine
    void=min(m["renal"]["bladder_L"],.02*dt) if env.get("void_permitted",False) else 0.0
    m["renal"]["bladder_L"]-=void;m["renal"]["voided_L"]+=void
    r=m["reproductive"]; o=old["reproductive"]
    r["gonadotropin"]=relax(o["gonadotropin"],clamp(1.0-(o["estrogen"]+o["progesterone"])/2),d,120.0)
    ovary=env.get("capacities",{}).get("ovary",1.0)
    r["estrogen"]=relax(o["estrogen"],r["gonadotropin"]*ovary,d,240.0)
    r["progesterone"]=relax(o["progesterone"],r["gonadotropin"]*ovary,d,300.0)
    m["mouth"]["swallow_open"]=plan["swallowing"]
    m["mouth"]["phonation"]=float(env.get("voice_request",False) and oxygen>.7 and f["respiration"]["ventilation_ok"]
        and swallowed == 0.0 and swallowed_water == 0.0)*funded
    # One circuit integration interval is exactly one body substep. Preserve
    # its learned weights and prior tick; no new training is falsely inferred.
    circuit=Circuit.restore(m["neural"]["circuit"])
    steps=round(dt*1000/circuit.dt_ms)
    counts={k:0 for k in circuit.cells}
    m["senses"]["expired"]=[k for k,v in m["senses"]["samples"].items() if s.time_s-v["sampled_at_s"]>TTL_S]
    sensory=max((v["value"] for k,v in m["senses"]["samples"].items() if k not in m["senses"]["expired"]),default=0.0)
    currents={"seat_input":min(10000.0,250.0*pain+150.0*(1.0-oxygen)+350.0*sensory),
        "arm_input":min(10000.0,200.0*max(s.fatigue.values())+150.0*im["inflammation"])}
    for _ in range(steps):
        row=circuit.step({k:v*funded for k,v in currents.items()})
        for k in row["spikes"]:counts[k]+=1
    n=m["neural"]
    n["circuit"]=circuit.payload();n["integration_ticks"]+=steps
    n["attention_hz"]=counts["attention"]/dt;n["regulation_hz"]=counts["regulation"]/dt
    n["optional_motor_fraction"]=clamp(1.0-.35*pain-.25*im["inflammation"]-.001*n["regulation_hz"],.15,1.0)
    sp=m["special"]
    sp["shutter"]=plan["shutter"]
    cue=m["senses"]["irradiance"]
    sp["resonan_attention"]=relax(sp["resonan_attention"],0.0 if cue is None else clamp(cue/1200.0),d,2.0)
    sp["azarine_budget_J"]=min(7200.0,s.reserve_J)
    if "tissue" in sp:
        special_physiology.settle(sp["tissue"], env.get("special_physiology", {}),
            plan["tissue_plan"], dt=dt, time_s=s.time_s, funded=funded,
            oxygen=oxygen, perfusion=perfusion, total_heat_J=s.heat_J)
    m["last_paid_W"]={k:v*funded for k,v in plan["demand"].items()}
    m["last_requests_W"]=plan["demand"]
    m["tick"]+=1
    m["outputs"]={
        "endocrine":deepcopy(e), "blood":deepcopy(m["blood"]),
        "renal":dict(**m["renal"],**body.renal.concentrations(s.free_water_L)),
        "immune":deepcopy(im),
        "cardiorespiratory":dict(Q_L_min=f["circulation"]["Q_L_min"],
            head_pressure_proxy_mmHg=f["circulation"]["head_pressure_proxy_mmHg"],
            oxygen_adequacy_proxy=oxygen,rate_min=f["respiration"]["rate_min"],
            usable_o2_L=f["respiration"]["state"]["usable_o2_L"] if "state" in f["respiration"] else context["gas"].usable_o2_L),
        "gut":deepcopy(gut), "senses":deepcopy(m["senses"]),
        "mouth":deepcopy(m["mouth"]), "reproductive":deepcopy(r),
        "musculoskeletal":dict(fatigue=deepcopy(s.fatigue),loads_N=deepcopy(s.previous_force_N),
            pain=pain,repaired_kg=s.repaired_kg,temperature_proxy_C=37.0+s.heat_J/(195.0*3500.0)),
        "neural":{k:deepcopy(v) for k,v in n.items() if k!="circuit"},
        "special":deepcopy(sp),
    }
    context["receipts"].append(dict(time_s=s.time_s,dt_s=dt,
        photo_J=plan["photo_W"]*dt,thermal_J=plan["thermal_W"]*dt,
        incident_J=plan["incident_W"]*dt,rejected_J=plan["rejected_W"]*dt,
        absorbed_J=plan["absorbed_J"],absorbed_water_L=plan["absorbed_water_L"],
        urine_transfer_L=urine,voided_L=void,organ_paid_J=f["organs"]["paid_W"]*dt,
        food_native_input_J=f["ledger"]["food_input_J"],fuel_used_J=f["ledger"]["fuel_used_J"],reserve_used_J=f["ledger"]["reserve_used_J"],
        mechanical_work_J=f["ledger"]["work_J"],removed_heat_J=f["ledger"]["heat_removed_J"],
        evaporated_L=f["ledger"]["evaporated_L"],respiratory_loss_L=f["ledger"]["respiratory_water_loss_L"],
        samples={k:deepcopy(m["outputs"][k]) for k in ("cardiorespiratory","renal","immune","neural")}))


class SharedOrganBody(AccessoryBody):
    organ_context=None

    def step(self, i):
        c=self.organ_context
        if c is None:return super().step(i)
        m=c["modules"];caps=c["environment"].get("capacities",{})
        rbc=1.0 if "blood_to_oxygen" in c["disabled"] else m["blood"]["rbc_capacity"]
        # Lung capacity belongs to gas exchange; RBC/heart capacity belongs
        # to downstream delivery. Do not debit lung capacity twice.
        oxygen_factor=rbc*caps.get("heart",1.0)
        motor=1.0 if "neural_to_motor" in c["disabled"] else m["neural"]["optional_motor_fraction"]
        # Postural support retains its reservation; only optional loads change.
        i=replace(i,oxygen_fraction=i.oxygen_fraction*oxygen_factor,
            force_requests_N={k:v*motor for k,v in i.force_requests_N.items()})
        p=rates(c,self,i,i.dt_s)
        thermal_J=p["thermal_W"]*i.dt_s
        self.state.heat_J+=thermal_J
        original_resp=i.respiratory_work_requested_W
        # The native ledger's historical food_input_J name becomes aggregate
        # external energy input. The explicit breakdown distinguishes light
        # heat from chemical substrate; heat never enters fuel or gas demand.
        inp=replace(i,food_intake_J_s=i.food_intake_J_s+p["absorbed_J"]/i.dt_s+p["photo_W"],
            water_intake_L_s=i.water_intake_L_s+p["absorbed_water_L"]/i.dt_s,
            respiratory_work_requested_W=original_resp+p["organ_W"])
        self.renal_input=replace(self.renal_input,perfusion_factor=caps.get("kidney",1.0))
        original_servo=self.accessory_requested_W
        self.accessory_requested_W=original_servo*motor
        try:f=super().step(inp)
        finally:self.accessory_requested_W=original_servo
        f["accessory_motor"]["requested_W"]=original_servo
        f["accessory_motor"]["paid_fraction"]*=motor
        f["accessory_motor"]["neural_optional_fraction"]=motor
        total=original_resp+p["organ_W"]
        fraction=clamp(f["circulation"]["respiratory_work_actual_W"]/total) if total else 1.0
        f["circulation"]["respiratory_work_actual_W"]=original_resp*fraction
        f["ledger"]["food_input_J"]+=thermal_J
        f["ledger"]["source_breakdown_J"]=dict(native_food_J=i.food_intake_J_s*i.dt_s,
            gut_transfer_J=p["absorbed_J"],photochemical_J=p["photo_W"]*i.dt_s,external_thermal_J=thermal_J)
        f["organs"]=dict(requests_W=p["demand"],requested_W=sum(p["demand"].values()),
            paid_W=p["organ_W"]*fraction,extra_cost_is_design_assumption=True,
            accounting="included once in native fuel, oxygen and heat balances")
        c["pending_plan"]=p
        return f


class SharedBreath(ActuatedBreath):
    def step(self, e):
        c=self.body.organ_context
        self.exchange_capacity=(1.0 if c is None else
            c["environment"].get("capacities",{}).get("lung",1.0))
        f=super().step(e)
        c=self.body.organ_context
        if c is not None:settle(c,self.body,f,c.pop("pending_plan"))
        return f


class CoupledEmbodiment(PersistentEmbodiment):
    def _attach(self):
        super()._attach()
        self.owner.body.__class__=SharedOrganBody
        self.owner.body.organ_context=None
        self.physical.coupling.__class__=SharedBreath

    def _simulate(self, *args, **kwargs):
        initial=self.owner.body.state.fuel_J
        r=super()._simulate(*args,**kwargs)
        # Replace the predecessor's intake-only diagnostic with an accounting
        # diagnostic that recognizes declared gut transfers and light capture.
        error=0.0;prior=initial
        for f in r["frames"]:
            thermal=f["ledger"].get("source_breakdown_J",{}).get("external_thermal_J",0.0)
            error=max(error,abs(prior+f["ledger"]["food_input_J"]-thermal-f["ledger"]["fuel_used_J"]-f["state"]["fuel_J"]))
            prior=f["state"]["fuel_J"]
        r["energy_balance_error_J"]=error
        return r


class UnifiedBody:
    def __init__(self, owner, modules, affect_state, migration, *, disabled=()):
        if set(disabled)-ROUTES:raise ValueError("unknown coupling ablation")
        self.owner=owner;self.modules=deepcopy(modules);self.affect=deepcopy(affect_state)
        self.migration=deepcopy(migration);self.disabled=sorted(disabled)
        self.anatomy=json.loads((ROOT/"anatomy_systems_v01.json").read_text())
        self.revision=0;self.requests={};self.results={};self.journal=[]
        self.episodes=[];self.bus=[];self.loaded_sha256=None

    @classmethod
    def migrate(cls, envelope):
        owner=CoupledEmbodiment.restore(envelope)
        neural=Circuit.load(ROOT/"retained_extensions/trained_circuit.json")
        af=affect.load(ROOT/"retained_extensions/initial_affect.json")
        obj=cls(owner,initial_modules(owner,neural),af,dict(source_schema=envelope["payload"]["schema"],
            source_sha256=envelope["sha256"],source_owner_revision=owner.revision,
            source_owner_time_s=owner.owner.body.state.time_s,
            source_library_file_id="synthetic-local-source",
            physical_stocks_reset=False,initial_gut_and_bladder_pools=0.0,
            new_proxy_indices_initialized_explicitly=True,
            old_source_files_modified=False,physical_sensor_connected=False,
            background_execution_started=False))
        if owner.checkpoint()!=envelope:raise ValueError("migration changed retained state")
        obj._publish()
        return obj

    def enable_special_physiology(self):
        """Explicit initialization before the first cycle; existing journals stay immutable."""
        if self.revision or "tissue" in self.modules["special"]:
            raise ValueError("special physiology requires a fresh, unenabled migration")
        self.modules["special"]["tissue"] = special_physiology.initial(self.owner.owner.body.state.heat_J)
        self.migration["special_physiology"] = dict(schema=special_physiology.SCHEMA,
            host_mass_kg=195.0, host_crown_height_cm=250.0, empirical_validation=False)
        self._publish()

    def _publish(self):
        time_s=self.owner.owner.body.state.time_s
        outputs=self.modules["outputs"]
        self.bus=[dict(node_id=n["id"],name_fa=n["name_fa"],system_stage=n["system_stage"],
            sampled_at_s=time_s,valid_until_s=time_s+TTL_S,evidence_level="B",
            kind="regional_projection_of_reduced_simulation",
            value=deepcopy(outputs.get(STAGE_KEYS[n["system_stage"]])),
            status="available" if STAGE_KEYS[n["system_stage"]] in outputs else "not_yet_sampled",
            independent_organ_solver=False) for n in self.anatomy["nodes"]]

    def read_packet(self, node_id, *, at_simulated_s):
        finite(at_simulated_s,"packet read clock",0,1e12)
        packet=next((p for p in self.bus if p["node_id"]==node_id),None)
        if packet is None:raise ValueError("unknown anatomical node")
        if at_simulated_s<packet["sampled_at_s"]:raise ValueError("future sample")
        result=deepcopy(packet)
        if at_simulated_s>packet["valid_until_s"]:
            result.update(status="expired",value=None)
        return result

    def validate_input(self, external, now, duration):
        if not isinstance(external,dict):raise ValueError("input must be an object")
        allowed={"native","meal_J","drink_L","irradiance_w_m2","capacities",
            "pathogen_index_input","sensors","voice_request","swallow_permitted","void_permitted","social","special_physiology"}
        if set(external)-allowed:raise ValueError("unknown whole-body input")
        if "special_physiology" in external:
            if "tissue" not in self.modules["special"]:
                raise ValueError("enable special physiology before supplying its inputs")
            special_physiology.validate_input(external["special_physiology"])
        self.owner.validate_external(external.get("native",{}),now)
        finite(external.get("meal_J",0.0),"meal",0,500000.0)
        finite(external.get("drink_L",0.0),"drink",0,2.0)
        if "irradiance_w_m2" in external:finite(external["irradiance_w_m2"],"light",0,2500.0)
        finite(external.get("pathogen_index_input",0.0),"pathogen index")
        caps=external.get("capacities",{})
        if not isinstance(caps,dict) or set(caps)-CAPACITY_KEYS:raise ValueError("unknown capacity")
        for k,v in caps.items():finite(v,k)
        for k in ("voice_request","swallow_permitted","void_permitted"):
            if k in external and type(external[k]) is not bool:raise ValueError("explicit boolean needed")
        sensors=external.get("sensors",{})
        if not isinstance(sensors,dict) or set(sensors)-{"vision","hearing","smell","taste","touch"}:
            raise ValueError("unknown sensory channel")
        for k,row in sensors.items():
            if not isinstance(row,dict) or set(row)!={"value","source_id","sampled_at_s","kind"}:
                raise ValueError("complete sensory provenance required")
            if row["kind"]!="declared_simulated_input" or not isinstance(row["source_id"],str) or not row["source_id"]:
                raise ValueError("only declared simulated samples accepted on this channel")
            finite(row["value"],k);finite(row["sampled_at_s"],"sample time",0,self.owner.owner.body.state.time_s)
            previous=self.modules["senses"]["samples"].get(k)
            if previous is not None:
                if row["sampled_at_s"] < previous["sampled_at_s"]:
                    raise ValueError("out-of-order sensory sample: " + k)
                if row["sampled_at_s"] == previous["sampled_at_s"] and row != previous:
                    raise ValueError("contradictory sensory sample at same timestamp: " + k)
        if "social" in external:
            if not isinstance(external["social"],dict):raise ValueError("social event object needed")
            affect.validate_event(external["social"])
        finite(duration,"duration",.1,60.0)
        if abs(duration*10-round(duration*10))>1e-8:raise ValueError("duration must align to .1 seconds")
        json.dumps(external,allow_nan=False)

    def _somatic(self):
        b=self.owner.body();m=b["minimum_state"]
        return dict(pain=m["pain"],hunger=1-m["energy"],thirst=1-m["hydration"],
            fatigue=m["fatigue"],warmth=clamp((m["temperature"]-37.0)/.5),
            cold=clamp((37.0-m["temperature"])/.5),touch=clamp(sum(bool(v) for v in self.owner.aux["contacts"].values())/2),
            comfort=clamp(1.0-max(m["pain"],m["fatigue"])),arousal=m["arousal"],nausea=0.0)

    def cycle(self, *, event_id, at_utc, duration_s=1.0, external=None,
              requested=None, expected_revision=None):
        external=deepcopy(external or {});now=instant(at_utc)
        self.validate_input(external,now,duration_s)
        if not isinstance(event_id,str) or not event_id or len(event_id)>120:raise ValueError("bounded event id required")
        if requested is not None and requested not in ACTIONS:raise ValueError("unknown requested action")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision<0):raise ValueError("integer revision required")
        request=digest(dict(external=external,duration_s=duration_s,requested=requested,expected_revision=expected_revision,at_utc=now.isoformat()))
        if event_id in self.requests:
            if self.requests[event_id]!=request:raise ValueError("conflicting event replay")
            if event_id not in self.results:raise ValueError("already executed; result archived, do not replay")
            return deepcopy(self.results[event_id])
        if expected_revision is not None and self.revision!=expected_revision:raise ValueError("stale writer")
        if now<instant(self.owner.wall_utc):raise ValueError("wall clock moved backwards")
        work=deepcopy(self);before_native=work.owner.body()
        before_walk_steps=work.owner.physical.state.walk_steps
        before_modules=deepcopy(work.modules);before_sha=digest(dict(native=before_native,modules=before_modules,affect=work.affect))
        old_energy=native_total(work.owner.owner.body)+lumen_energy(work.modules)
        old_water=work.owner.owner.body.state.free_water_L+work.owner.owner.body.state.bound_water_L+lumen_water(work.modules)+work.modules["renal"]["bladder_L"]
        old_void=work.modules["renal"]["voided_L"]
        native=deepcopy(external.get("native",{}))
        meal=external.get("meal_J",0.0)+native.pop("food_J",0.0)
        water=external.get("drink_L",0.0)+native.pop("water_L",0.0)
        if meal>500000.0 or water>2.0:raise ValueError("aggregate meal/drink limit exceeded")
        work.modules["gut"]["mouth_J"]+=meal
        work.modules["gut"]["mouth_water_L"]+=water
        work.modules["immune"]["pathogen_index"]=clamp(work.modules["immune"]["pathogen_index"]+external.get("pathogen_index_input",0.0))
        t=work.owner.owner.body.state.time_s
        work.modules["senses"]["samples"].update(external.get("sensors",{}))
        work.modules["senses"]["expired"]=[k for k,v in work.modules["senses"]["samples"].items() if t-v["sampled_at_s"]>TTL_S]
        work.modules["senses"]["irradiance"]=external.get("irradiance_w_m2")
        # Fresh simulated samples retain their provenance. Absent light is
        # unknown and supplies zero energy; it is never asserted to be dark.
        somatic=work._somatic() if "body_to_affect" not in work.disabled else deepcopy(work.affect["somatic"])
        ae=deepcopy(external.get("social",{}))
        ae.update(id=event_id+":affect",source=ae.get("source","synthetic_fixture"),
            elapsed_hours=duration_s/3600.0,energy=before_native["minimum_state"]["energy"],body=somatic)
        ar=affect.transition(work.affect,ae)
        af=work.affect["affect"]
        if "affect_to_autonomic" not in work.disabled and "emotion" not in native:
            channels={"fear":max(af["fear"],af["anxiety"]),"anger":af["anger"],
                "affection":max(af["affection"],af["tenderness"]),"curiosity":af["curiosity"]}
            emotion=max(channels,key=channels.get)
            native.update(emotion=emotion,emotion_intensity=channels[emotion])
        chosen=requested
        if chosen is None and "spandar_to_decision" not in work.disabled:
            tissue=work.modules["special"].get("tissue")
            if tissue is not None and not tissue["spandar"]["valid"]:
                chosen="protect" if somatic["fatigue"]>.45 or somatic["pain"]>.35 else "observe"
            elif work.modules["special"]["spandar_last_error"]>.02:chosen="observe"
            elif somatic["fatigue"]>.45 or somatic["pain"]>.35:chosen="protect"
            elif somatic["arousal"]>.45:chosen="slow_breath"
        context=dict(modules=work.modules,environment=external,disabled=work.disabled,
            airway_capacity=native.get("airway_capacity",1.0),gas=work.owner.physical.coupling.gas,receipts=[])
        work.owner.owner.body.organ_context=context
        result=work.owner.cycle(event_id="whole-body:"+event_id,at_utc=now.isoformat(),
            duration_s=duration_s,external=native,requested=chosen)
        context=work.owner.owner.body.organ_context
        work.modules=context["modules"];receipts=context["receipts"]
        # Outcome feedback, rather than a second organ advance.
        if "body_to_affect" not in work.disabled:work.affect["somatic"].update(work._somatic())
        affect.validate(work.affect)
        error=result["prediction"]["mean_scaled_absolute_error"]
        sp = work.modules["special"]
        memory_digest = digest(work.owner.aux["body_memory"])
        if "tissue" in sp:
            monitor = special_physiology.sample_memory(sp["tissue"],
                time_s=work.owner.owner.body.state.time_s,
                memory_digest=memory_digest, prediction_error=error)
            if monitor["valid"]:
                sp["spandar_last_error"] = monitor["sampled_error"]
                sp["spandar_digest"] = monitor["sampled_digest"]
        else:
            sp["spandar_last_error"]=error
            sp["spandar_digest"]=memory_digest
        work.modules["outputs"]["special"]=deepcopy(work.modules["special"])
        work.revision+=1;work.modules["published_packets"]+=len(work.anatomy["nodes"])*len(receipts)
        work._publish()
        new_energy=native_total(work.owner.owner.body)+lumen_energy(work.modules)
        new_water=work.owner.owner.body.state.free_water_L+work.owner.owner.body.state.bound_water_L+lumen_water(work.modules)+work.modules["renal"]["bladder_L"]
        photo=sum(r["photo_J"] for r in receipts);heat=sum(r["thermal_J"] for r in receipts)
        mechanical=sum(r["mechanical_work_J"] for r in receipts);removed=sum(r["removed_heat_J"] for r in receipts)
        voided=work.modules["renal"]["voided_L"]-old_void
        loss=sum(r["evaporated_L"]+r["respiratory_loss_L"] for r in receipts)+voided
        ee=abs(old_energy+meal+photo+heat-new_energy-mechanical-removed)
        we=abs(old_water+water-new_water-loss)
        light_error=max((abs(r["incident_J"]-r["photo_J"]-r["thermal_J"]-r["rejected_J"]) for r in receipts),default=0)
        if ee>5e-5 or we>1e-8 or light_error>1e-8:raise ValueError("whole-body conservation failed")
        circuit=work.modules["neural"]
        native_delta=work.owner.owner.body.state.time_s-work.modules["origin_time_s"]
        neural_delta=circuit["integration_ticks"]*circuit["circuit"]["dt_ms"]/1000.0
        if abs(native_delta-neural_delta)>1e-7:raise ValueError("neural/body clock divergence")
        # Append a receipt to the retained long-term memory using its native
        # schema, so future recall consumes the actual executed body outcome.
        bank=work.owner.owner.memory.memory
        kernel_hash=source_hashes()["unified_body_v2.py"]
        # Historical evidence retains its original source identity. A revised
        # kernel writes a new source rather than reassigning old evidence.
        source="whole_body_kernel_v2:"+kernel_hash[:16]
        bank.register_source(source,kernel_hash,"declared_runtime_journal")
        epoch=work.migration["source_sha256"][:24]
        episode=dict(id=event_id+":body-receipt",kind="physical_receipt",context="whole-body-v2",epoch=epoch,
            topic="integrated_body",sampled_at_s=work.owner.owner.body.state.time_s,
            source_ref=source,source_record=event_id,
            payload=dict(body_valid=result["physical_model_valid"],body_veto=result["selected_action"]!=requested if requested else False,
                optional_pause_executed=result["selected_action"]=="protect",executed_walk_touchdowns=work.owner.physical.state.walk_steps-before_walk_steps,
                fuel_used_J=sum(r["fuel_used_J"] for r in receipts),reserve_used_J=sum(r["reserve_used_J"] for r in receipts),
                receipt_scope="actual full native fuel and reserve debits",
                selected_action=result["selected_action"]))
        bank.record_batch("whole-body-v2",epoch,work.revision,[episode])
        after_sha=digest(dict(native=work.owner.body(),modules=work.modules,affect=work.affect))
        entry=dict(event_id=event_id,revision=work.revision,request_sha256=request,
            before_sha256=before_sha,after_sha256=after_sha,
            previous_event_sha256=work.journal[-1]["sha256"] if work.journal else None,
            causes=["declared_environment_input","internal_regulation","single_owner_simulated_action","outcome_feedback"],
            simulated_seconds=duration_s,owner_ticks=len(receipts),wall_utc=now.isoformat())
        entry["sha256"]=digest(entry);work.journal.append(entry)
        out=dict(schema=SCHEMA,event_id=event_id,revision=work.revision,owner=result,
            systems=12,regional_packets=len(work.bus),owner_ticks=len(receipts),
            organ_metabolism_J=sum(r["organ_paid_J"] for r in receipts),
            whole_body_audit=dict(energy_error_J=ee,water_error_L=we,light_error_J=light_error,
                meal_input_J=meal,drink_input_L=water,photochemical_J=photo,external_heat_J=heat,
                voided_L=voided,same_owner_ticks=True,neural_clock_error_s=abs(native_delta-neural_delta)),
            affect_plan=ar["plan"],somatic_feedback=deepcopy(work.affect["somatic"]),
            outputs=deepcopy(work.modules["outputs"]),trace=receipts,
            physical_sensor_connected=False,background_execution_started=False)
        work.requests[event_id]=request;work.results[event_id]=deepcopy(out)
        work.results=dict(list(work.results.items())[-16:])
        work.episodes=(work.episodes+[dict(event_id=event_id,body_time_s=work.owner.owner.body.state.time_s,
            action=result["selected_action"],prediction_error=error,bank_episode_id=episode["id"])])[-128:]
        self.__dict__=work.__dict__
        return deepcopy(out)

    def checkpoint(self):
        p=dict(schema=SCHEMA,source_fingerprints=source_hashes(),revision=self.revision,
            owner=self.owner.checkpoint(),modules=deepcopy(self.modules),affect=deepcopy(self.affect),
            migration=deepcopy(self.migration),disabled=self.disabled,requests=self.requests,
            results=self.results,journal=self.journal,episodes=self.episodes,bus=self.bus)
        return dict(payload=p,sha256=digest(p))

    @classmethod
    def restore(cls, envelope):
        if set(envelope)!={"payload","sha256"} or digest(envelope["payload"])!=envelope["sha256"]:
            raise ValueError("whole-body checksum mismatch")
        p=envelope["payload"]
        required={"schema","source_fingerprints","revision","owner","modules","affect","migration","disabled","requests","results","journal","episodes","bus"}
        if set(p)!=required or p["schema"]!=SCHEMA or p["source_fingerprints"]!=source_hashes():raise ValueError("whole-body schema/source mismatch")
        obj=cls(CoupledEmbodiment.restore(p["owner"]),p["modules"],p["affect"],p["migration"],disabled=p["disabled"])
        for k in ("revision","requests","results","journal","episodes","bus"):setattr(obj,k,deepcopy(p[k]))
        # JSON object key order is not commit chronology. Evict by the stored
        # monotonically increasing receipt revision after a cold restore.
        obj.results=dict(sorted(obj.results.items(),key=lambda item:item[1]["revision"]))
        affect.validate(obj.affect);Circuit.restore(obj.modules["neural"]["circuit"])
        previous=None;previous_body=None
        for row in obj.journal:
            if row["sha256"]!=digest({k:v for k,v in row.items() if k!="sha256"}) or row["previous_event_sha256"]!=previous:raise ValueError("whole-body journal broken")
            if previous_body is not None and row["before_sha256"]!=previous_body:raise ValueError("unrecorded module change between cycles")
            previous=row["sha256"]
            previous_body=row["after_sha256"]
        if len(obj.journal)!=obj.revision or obj.modules["tick"]<0:raise ValueError("whole-body revision mismatch")
        for x in (lumen_energy(obj.modules),lumen_water(obj.modules),obj.modules["renal"]["bladder_L"]):finite(x,"compartment",0,1e12)
        if len(obj.bus)!=len(obj.anatomy["nodes"]):raise ValueError("incomplete anatomical bus")
        native_delta=obj.owner.owner.body.state.time_s-obj.modules["origin_time_s"]
        n=obj.modules["neural"]
        if abs(native_delta-n["integration_ticks"]*n["circuit"]["dt_ms"]/1000)>1e-7:raise ValueError("checkpoint clocks disagree")
        if n["circuit"]["tick"]-n["origin_tick"]!=n["integration_ticks"]:raise ValueError("circuit tick mismatch")
        if previous_body is not None and previous_body!=digest(dict(native=obj.owner.body(),modules=obj.modules,affect=obj.affect)):
            raise ValueError("unrecorded current module change")
        bus=deepcopy(obj.bus);obj._publish()
        if obj.bus!=bus:raise ValueError("stored bus does not match its source state")
        obj.loaded_sha256=envelope["sha256"]
        return obj

    @classmethod
    def load(cls, path):
        return cls.restore(json.loads(Path(path).read_text()))

    def save(self, path, *, expected_sha256=None):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        with (path.parent/("."+path.name+".lock")).open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if path.exists():
                old=json.loads(path.read_text())
                expected=expected_sha256 or self.loaded_sha256
                if expected is None or old.get("sha256")!=expected:raise ValueError("file changed since read")
            elif self.loaded_sha256 is not None:raise ValueError("previous checkpoint disappeared")
            envelope=self.checkpoint();atomic_json(path,envelope);self.loaded_sha256=envelope["sha256"]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("step");s.add_argument("--state",required=True);s.add_argument("--event",required=True)
    s.add_argument("--output",required=True)
    s=sub.add_parser("inspect");s.add_argument("--state",required=True)
    a=p.parse_args();body=UnifiedBody.load(a.state)
    if a.command=="inspect":
        print(json.dumps(dict(schema=SCHEMA,revision=body.revision,
            body=body.owner.body()["minimum_state"],system_count=12,regional_count=len(body.bus),
            latest_outputs=body.modules["outputs"]),ensure_ascii=False,indent=2))
        return
    event=json.loads(Path(a.event).read_text());out=body.cycle(**event)
    body.save(a.state);atomic_json(a.output,out)
    print(json.dumps(dict(event_id=out["event_id"],revision=out["revision"],audit=out["whole_body_audit"])))


if __name__=="__main__":main()
