"""Causal, conservation, replay and process-continuation checks for V2."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from unified_body_v2 import UnifiedBody, ROOT, digest, instant


def fixture(*, disabled=()):
    b=deepcopy(TEMPLATE)
    b.disabled=sorted(disabled)
    b.migration["test_fixture"]=True
    return b


def run(b, external=None, duration=.5, requested=None):
    return b.cycle(event_id="test-"+str(b.revision+1),
        at_utc=(instant(b.owner.wall_utc)+timedelta(seconds=duration)).isoformat(),
        duration_s=duration,external=external or {},requested=requested,
        expected_revision=b.revision)


from synthetic_fixture import synthetic_origin
ORIGIN=synthetic_origin()
TEMPLATE=UnifiedBody.migrate(ORIGIN)


class IntegrationChecks(unittest.TestCase):
    def test_exact_migration_no_stock_or_memory_reset(self):
        self.assertEqual(TEMPLATE.owner.checkpoint(),ORIGIN)
        self.assertEqual(TEMPLATE.modules["gut"]["mouth_J"],0)
        self.assertFalse(TEMPLATE.migration["physical_stocks_reset"])

    def test_all_twelve_systems_have_current_regional_packets(self):
        b=fixture();run(b,duration=.1)
        self.assertEqual({p["system_stage"] for p in b.bus},set(range(1,13)))
        self.assertEqual(len(b.bus),97)
        self.assertTrue(all(p["status"]=="available" for p in b.bus))
        self.assertTrue(all(p["sampled_at_s"]==b.owner.owner.body.state.time_s for p in b.bus))

    def test_energy_water_light_balance_across_new_compartments(self):
        r=run(fixture(),dict(meal_J=20000,drink_L=.5,irradiance_w_m2=600),duration=1)
        self.assertLess(r["whole_body_audit"]["energy_error_J"],5e-5)
        self.assertLess(r["whole_body_audit"]["water_error_L"],1e-8)
        self.assertLess(r["whole_body_audit"]["light_error_J"],1e-8)

    def test_gut_route_cut_stops_absorption_and_preserves_food(self):
        a,b=fixture(),fixture(disabled=("gut_to_fuel",))
        ra,rb=run(a,{"meal_J":10000},duration=1),run(b,{"meal_J":10000},duration=1)
        self.assertGreater(ra["outputs"]["gut"]["total_absorbed_J"],0)
        self.assertEqual(rb["outputs"]["gut"]["total_absorbed_J"],0)
        self.assertAlmostEqual(rb["outputs"]["gut"]["mouth_J"]+rb["outputs"]["gut"]["stomach_J"],10000)
        self.assertGreater(a.owner.owner.body.state.fuel_J,b.owner.owner.body.state.fuel_J)

    def test_closed_swallow_keeps_ingested_input_in_mouth(self):
        r=run(fixture(),dict(meal_J=10000,drink_L=.2,swallow_permitted=False),duration=1)
        self.assertEqual(r["outputs"]["gut"]["mouth_J"],10000)
        self.assertEqual(r["outputs"]["gut"]["total_absorbed_J"],0)
        self.assertFalse(r["outputs"]["mouth"]["swallow_open"])

    def test_light_cut_removes_energy_and_thermal_input(self):
        a,b=fixture(),fixture(disabled=("resonan_to_energy",))
        ra,rb=run(a,{"irradiance_w_m2":800}),run(b,{"irradiance_w_m2":800})
        self.assertGreater(ra["whole_body_audit"]["photochemical_J"],0)
        self.assertEqual(rb["whole_body_audit"]["photochemical_J"],0)
        self.assertEqual(rb["whole_body_audit"]["external_heat_J"],0)
        self.assertGreater(a.owner.owner.body.state.fuel_J,b.owner.owner.body.state.fuel_J)

    def test_resonan_saturation_reduces_acceptance(self):
        a,b=fixture(),fixture();b.modules["special"]["resonan_attention"]=1.0
        ra,rb=run(a,{"irradiance_w_m2":1200},duration=.1),run(b,{"irradiance_w_m2":1200},duration=.1)
        self.assertGreater(ra["whole_body_audit"]["photochemical_J"],rb["whole_body_audit"]["photochemical_J"])

    def test_renal_capacity_changes_filtration_and_bladder_flow(self):
        a,b=fixture(),fixture()
        run(a,{"capacities":{"kidney":1.0}},duration=1)
        run(b,{"capacities":{"kidney":.2}},duration=1)
        self.assertGreater(a.owner.owner.renal.state["filtered_L"],b.owner.owner.renal.state["filtered_L"])
        self.assertGreater(a.modules["renal"]["bladder_L"],b.modules["renal"]["bladder_L"])

    def test_bladder_storage_and_voiding_are_distinct(self):
        b=fixture();run(b,duration=1)
        self.assertGreater(b.modules["renal"]["bladder_L"],0)
        self.assertEqual(b.modules["renal"]["voided_L"],0)
        r=run(b,{"void_permitted":True})
        self.assertGreater(r["whole_body_audit"]["voided_L"],0)
        self.assertLess(r["whole_body_audit"]["water_error_L"],1e-8)

    def test_inflammation_cost_couples_into_same_fuel_budget(self):
        a,b=fixture(),fixture(disabled=("immune_to_metabolic",))
        a.modules["immune"]["inflammation"]=.8;b.modules["immune"]["inflammation"]=.8
        ra,rb=run(a),run(b)
        self.assertGreater(ra["organ_metabolism_J"],rb["organ_metabolism_J"])
        self.assertLess(a.owner.owner.body.state.fuel_J,b.owner.owner.body.state.fuel_J)

    def test_blood_capacity_reaches_oxygen_solver(self):
        a,b=fixture(),fixture(disabled=("blood_to_oxygen",))
        a.modules["blood"]["rbc_capacity"]=.5;b.modules["blood"]["rbc_capacity"]=.5
        ra,rb=run(a),run(b)
        self.assertLess(ra["outputs"]["cardiorespiratory"]["oxygen_adequacy_proxy"],rb["outputs"]["cardiorespiratory"]["oxygen_adequacy_proxy"])

    def test_fresh_sensory_input_drives_existing_circuit(self):
        a,b=fixture(),fixture();t=a.owner.owner.body.state.time_s
        sample=dict(value=1.0,source_id="test",sampled_at_s=t,kind="declared_simulated_input")
        ra,rb=run(a,{"sensors":{"vision":sample}},duration=1),run(b,duration=1)
        self.assertGreater(ra["outputs"]["neural"]["attention_hz"],rb["outputs"]["neural"]["attention_hz"])
        self.assertLess(a.modules["neural"]["optional_motor_fraction"],b.modules["neural"]["optional_motor_fraction"])

    def test_unknown_and_expired_inputs_are_not_zero_measurements(self):
        b=fixture();self.assertIsNone(b.bus[0]["value"])
        run(b,duration=.1)
        self.assertIsNone(b.modules["senses"]["irradiance"])
        p=b.read_packet(b.bus[0]["node_id"],at_simulated_s=b.owner.owner.body.state.time_s+6)
        self.assertEqual(p["status"],"expired");self.assertIsNone(p["value"])

    def test_old_sensory_sample_is_excluded_from_neural_encoding(self):
        b,c=fixture(),fixture();t=b.owner.owner.body.state.time_s
        old=dict(value=1.0,source_id="old-test",sampled_at_s=t-6,kind="declared_simulated_input")
        r=run(b,{"sensors":{"hearing":old}},duration=.1)
        control=run(c,duration=.1)
        self.assertIn("hearing",r["outputs"]["senses"]["expired"])
        # Retained membrane potentials and pending spikes are allowed to
        # remain active. Expiry removes input; it does not erase neural state.
        self.assertEqual(b.modules["neural"]["circuit"],c.modules["neural"]["circuit"])
        self.assertEqual(r["outputs"]["neural"]["attention_hz"],control["outputs"]["neural"]["attention_hz"])

    def test_neural_feedback_changes_actual_paid_upper_motion(self):
        a,b=fixture(),fixture(disabled=("neural_to_motor",))
        a.modules["neural"]["optional_motor_fraction"]=.3
        b.modules["neural"]["optional_motor_fraction"]=.3
        event={"native":{"upper_targets":{"shoulder_L":.3,"elbow_L":.3}}}
        run(a,event,requested="observe");run(b,event,requested="observe")
        self.assertLess(a.owner.aux["upper_angles"]["shoulder_L"],b.owner.aux["upper_angles"]["shoulder_L"])
        self.assertLess(a.owner.aux["accessory_energy_J"],b.owner.aux["accessory_energy_J"])

    def test_affect_route_cut_changes_autonomic_response(self):
        a,b=fixture(),fixture(disabled=("affect_to_autonomic",))
        a.affect["affect"]["fear"]=.9;b.affect["affect"]["fear"]=.9
        ra,rb=run(a,duration=1),run(b,duration=1)
        self.assertGreater(ra["owner"]["outcome_minimum_state"]["sympathetic"],rb["owner"]["outcome_minimum_state"]["sympathetic"])

    def test_actual_body_feedback_reaches_full_affect_state(self):
        a,b=fixture(),fixture(disabled=("body_to_affect",))
        run(a);run(b)
        self.assertEqual(a.affect["somatic"]["fatigue"],a.owner.body()["minimum_state"]["fatigue"])
        self.assertNotEqual(a.affect["somatic"]["fatigue"],b.affect["somatic"]["fatigue"])

    def test_endocrine_feedback_changes_incremental_metabolism(self):
        a,b=fixture(),fixture(disabled=("endocrine_to_metabolic",))
        ra,rb=run(a),run(b)
        self.assertGreater(ra["organ_metabolism_J"],rb["organ_metabolism_J"])
        self.assertGreater(ra["outputs"]["endocrine"]["insulin"],.5)

    def test_reproductive_indices_have_bounded_feedback(self):
        a,b=fixture(),fixture()
        ra,rb=run(a,{"capacities":{"ovary":1.0}}),run(b,{"capacities":{"ovary":0.0}})
        self.assertGreater(ra["outputs"]["reproductive"]["estrogen"],rb["outputs"]["reproductive"]["estrogen"])
        self.assertTrue(all(0<=v<=1 for v in rb["outputs"]["reproductive"].values()))

    def test_single_owner_tick_and_shared_neural_clock(self):
        b=fixture();old=b.owner.owner.renal.state["ticks"]
        r=run(b,duration=1)
        self.assertEqual(b.owner.owner.renal.state["ticks"]-old,10)
        self.assertEqual(b.modules["tick"],10)
        self.assertEqual(b.modules["neural"]["integration_ticks"],2000)
        self.assertLess(r["whole_body_audit"]["neural_clock_error_s"],1e-7)

    def test_memory_contains_actual_native_receipt(self):
        b=fixture();r=run(b)
        rows=[e for e in b.owner.owner.memory.memory.episodes if e["context"]=="whole-body-v2"]
        self.assertEqual(len(rows),1)
        self.assertAlmostEqual(rows[0]["payload"]["fuel_used_J"],sum(t["fuel_used_J"] for t in r["trace"]))

    def test_exact_cold_checkpoint_continuation(self):
        b=fixture();run(b,{"meal_J":10000,"drink_L":.2,"irradiance_w_m2":300})
        c=UnifiedBody.restore(json.loads(json.dumps(b.checkpoint(),sort_keys=True)))
        ra,rb=run(b,duration=.1),run(c,duration=.1)
        self.assertEqual(ra,rb);self.assertEqual(b.checkpoint(),c.checkpoint())

    def test_event_replay_does_not_advance_any_organ(self):
        b=fixture();event=dict(event_id="replay",at_utc=b.owner.wall_utc,duration_s=.1,expected_revision=0)
        r=b.cycle(**event);before=b.checkpoint()
        self.assertEqual(b.cycle(**event),r);self.assertEqual(b.checkpoint(),before)
        with self.assertRaises(ValueError):b.cycle(**(event|{"duration_s":.2}))
        self.assertEqual(b.checkpoint(),before)

    def test_rejected_stale_and_invalid_inputs_do_not_mutate_state(self):
        b=fixture();before=b.checkpoint()
        for extra in [{"expected_revision":9},{"external":{"drink_L":float("nan")}},
                      {"external":{"capacities":{"ghost":1}}},{"duration_s":.15}]:
            with self.assertRaises(ValueError):b.cycle(**(dict(event_id="bad",at_utc=b.owner.wall_utc)|extra))
            self.assertEqual(b.checkpoint(),before)

    def test_checksum_and_unjournaled_changes_are_rejected(self):
        b=fixture();run(b,duration=.1);env=b.checkpoint()
        corrupt=deepcopy(env);corrupt["payload"]["modules"]["gut"]["stomach_J"]+=1
        with self.assertRaises(ValueError):UnifiedBody.restore(corrupt)
        corrupt["sha256"]=digest(corrupt["payload"])
        with self.assertRaises(ValueError):UnifiedBody.restore(corrupt)

    def test_atomic_file_replacement_rejects_second_stale_writer(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"state.json";b=fixture();b.save(path)
            a,c=UnifiedBody.load(path),UnifiedBody.load(path)
            run(a,duration=.1);a.save(path)
            run(c,duration=.1)
            with self.assertRaises(ValueError):c.save(path)
            self.assertEqual(UnifiedBody.load(path).checkpoint(),a.checkpoint())

    def test_separate_python_process_resumes_identically(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"state.json";event_path=Path(d)/"event.json";out=Path(d)/"out.json"
            b=fixture();run(b,duration=.1);b.save(path)
            event=dict(event_id="process-resume",at_utc=b.owner.wall_utc,duration_s=.1,expected_revision=b.revision)
            event_path.write_text(json.dumps(event))
            predicted=deepcopy(b);expected=predicted.cycle(**event)
            p=subprocess.run([sys.executable,str(ROOT/"unified_body_v2.py"),"step","--state",str(path),"--event",str(event_path),"--output",str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(out.read_text()),expected)
            self.assertEqual(UnifiedBody.load(path).checkpoint(),predicted.checkpoint())


if __name__=="__main__":unittest.main(verbosity=2)
