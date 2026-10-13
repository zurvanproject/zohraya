"""External conservation audit; never calls the controller's accounting code."""
from copy import deepcopy
import math

CHANNELS = ("elbow", "hip_L", "knee_L", "ankle_L", "hip_R", "knee_R", "ankle_R", "tail")
TISSUE_J_KG = 10000.0
TOLERANCES = {"energy_J": 5e-5, "water_L": 1e-8,
              "material_kg": 1e-9, "wound_kg": 1e-9, "force_N": 1e-7}

def finite_tree(value):
    if isinstance(value, float):
        assert math.isfinite(value), "nonfinite output"
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite_tree(item)

class ConservationAudit:
    def __init__(self, initial):
        self.initial = deepcopy(initial)
        self.frames = 0
        self.food_J = self.water_L = self.work_J = self.removed_J = self.loss_L = 0.0
        self.injuries = {c: 0.0 for c in CHANNELS}
        self.repairs = {c: 0.0 for c in CHANNELS}
        self.max_errors = {k: 0.0 for k in TOLERANCES}

    def frame(self, f):
        finite_tree(f)
        s, m, l = f["state"], f["motor"], f["ledger"]
        dt = l["dt_s"]
        self.frames += 1
        self.food_J += l["food_input_J"]
        self.water_L += l["water_input_L"]
        # Reconstruct mechanical work from delivered force and supplied speed.
        self.work_J += sum(m["force_N"][c] * m["speeds_m_s"][c] * dt for c in CHANNELS)
        self.removed_J += l["heat_removed_J"]
        self.loss_L += l["evaporated_L"] + l["respiratory_water_loss_L"] + l["urine_loss_L"]
        for c in CHANNELS:
            self.injuries[c] += l["injury_events_kg"][c]
            self.repairs[c] += l["repair_by_channel_kg"][c]
        repaired_delta = s["repaired_kg"] - self.initial["repaired_kg"]
        source_J = sum(self.initial[k] for k in ("fuel_J", "reserve_J", "heat_J")) + self.food_J
        accounted_J = sum(s[k] for k in ("fuel_J", "reserve_J", "heat_J"))
        accounted_J += self.work_J + self.removed_J + repaired_delta * TISSUE_J_KG
        water_source = self.initial["free_water_L"] + self.initial["bound_water_L"] + self.water_L
        errors = {
            "energy_J": abs(source_J - accounted_J),
            "water_L": abs(water_source - s["free_water_L"] - s["bound_water_L"] - self.loss_L),
            "material_kg": abs(self.initial["material_kg"] - s["material_kg"] - repaired_delta),
            "wound_kg": max(abs(self.initial["wounds_kg"][c] + self.injuries[c]
                                  - s["wounds_kg"][c] - self.repairs[c]) for c in CHANNELS),
            "force_N": max(max(0.0, m["force_N"][c] - m["capacity_N"][c],
                                m["force_N"][c] - m["requests_N"][c]) for c in CHANNELS),
        }
        for key, error in errors.items():
            self.max_errors[key] = max(self.max_errors[key], error)
            assert error <= TOLERANCES[key], (key, self.frames, error)
        for key in ("fuel_J", "reserve_J", "free_water_L", "bound_water_L",
                    "material_kg", "repaired_kg", "heat_J"):
            assert s[key] >= 0, (key, s[key])
        assert all(v >= 0 for v in s["wounds_kg"].values())
        assert all(0 <= v <= 1 for v in s["fatigue"].values())
        assert l["repair_material_kg"] <= 0.00003 * dt + 1e-12, "repair allowance duplicated"
        assert abs(sum(l["repair_by_channel_kg"].values()) - l["repair_material_kg"]) < 1e-12
        assert abs(l["water_bound_L"] - l["repair_material_kg"] * 3) < 1e-12
        motor_J = sum(m["force_N"][c] * (m["speeds_m_s"][c] / 0.30 + 0.06) * dt for c in CHANNELS)
        assert abs(motor_J - l["motor_energy_J"]) < 1e-7
        assert l["reserve_used_J"] <= 1800 * dt + 1e-7
        assert l["fuel_used_J"] + l["reserve_used_J"] >= motor_J - 1e-7
        if m["critical_stop"] or m["systemic_stop"]:
            assert all(v == 0 for v in m["force_N"].values()), "optional force during stop"
        if "balance" in f:
            assert m["support_executed"] == f["balance"]["protective_step_executed"]

    def result(self):
        return {"passed": True, "frames": self.frames, "max_errors": self.max_errors,
                "mechanical_work_J": self.work_J, "water_loss_L": self.loss_L}
