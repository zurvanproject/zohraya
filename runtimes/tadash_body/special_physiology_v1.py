"""Opt-in fictional organ physiology; all constants are design assumptions.

The native body remains the only owner of energy. Azarine's heat is a tagged
partition of native heat, never another term in the whole-body energy sum.
This is a reduced numerical model, not measured biology or crystal memory.
"""
from copy import deepcopy
import math

SCHEMA = "nasuraya-special-physiology/1"
SIDES = ("left", "right")
# Ellipsoid (48 x 72 x 48 mm), assumed water-like density/heat capacity.
AZARINE_VOLUME_ML = math.pi / 6 * 48 * 72 * 48 / 1000
LOCAL_C = AZARINE_VOLUME_ML / 1000 * 3500
HOST_C = 195 * 3500  # Explicit legacy host; not the proposed 78 kg body.
CORE_C = HOST_C - LOCAL_C


def bounded(x):
    return max(0.0, min(1.0, x))


def number(x, name, upper=1.0):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= upper:
        raise ValueError("invalid special physiology input: " + name)


def validate_input(value):
    if not isinstance(value, dict) or set(value) - {"resonan", "spandar_perfusion", "azarine_perfusion", "azarine_load_W"}:
        raise ValueError("unknown special physiology input")
    for key in ("spandar_perfusion", "azarine_perfusion", "azarine_load_W"):
        if key in value:
            number(value[key], key, 40 if key.endswith("_W") else 1)
    lobes = value.get("resonan", {})
    if not isinstance(lobes, dict) or set(lobes) - set(SIDES):
        raise ValueError("unknown Resonan side")
    for side, row in lobes.items():
        if not isinstance(row, dict) or set(row) - {"perfusion", "strain", "irradiance_w_m2"}:
            raise ValueError("unknown Resonan input field")
        for key, value in row.items():
            number(value, side + ":" + key, 2500 if key == "irradiance_w_m2" else 1)


def initial(total_heat_J):
    return dict(schema=SCHEMA, host_mass_kg=195.0,
        resonan={side: dict(adaptation=0.0, signal=None, confidence=0.0,
            shutter=1.0, irradiance_w_m2=None) for side in SIDES},
        spandar=dict(valid=False, last_sample_s=None, sampled_digest=None,
            sampled_error=None, adequacy=0.0, period_s=2.0),
        azarine=dict(local_heat_J=total_heat_J * LOCAL_C / HOST_C,
            accounted_total_heat_J=total_heat_J, local_temperature_C=37 + total_heat_J / HOST_C,
            core_temperature_C=37 + total_heat_J / HOST_C, thermal_gate=1.0,
            requested_load_W=0.0, paid_load_J=0.0, exchanged_heat_J=0.0,
            partition_error_J=0.0))


def plan(state, inputs, common_light, temperature, disabled, reserve_J, dt):
    """Each hemisphere owns half the old capture area; missing is unknown."""
    lobes = {}
    for side in SIDES:
        x = inputs.get("resonan", {}).get(side, {})
        light = x.get("irradiance_w_m2", common_light)
        perfusion = x.get("perfusion", 1.0)
        shutter = bounded((37.4 - temperature) / .2) * perfusion
        shutter *= 1 - .75 * state["resonan"][side]["adaptation"]
        if "resonan_to_energy" in disabled:
            shutter = 0.0
        incident = 0 if light is None else light * .01
        lobes[side] = dict(irradiance_w_m2=light, strain=x.get("strain"),
            perfusion=perfusion, shutter=shutter, incident_W=incident,
            photo_W=incident * .12 * shutter, thermal_W=incident * .58 * shutter)
    az = state["azarine"]
    gate = bounded((38.0 - az["local_temperature_C"]) / .5)
    # Workload is paid by the native metabolism, not subtracted from reserve
    # here. The tagged reserve budget only constrains optional admission.
    load = min(inputs.get("azarine_load_W", 0) * gate * inputs.get("azarine_perfusion", 1),
               max(0, min(7200, reserve_J)) / dt)
    return dict(lobes=lobes, azarine_load_W=load, thermal_gate=gate,
        heat_before_J=az["accounted_total_heat_J"])


def settle(state, inputs, p, *, dt, time_s, funded, oxygen, perfusion, total_heat_J):
    """Advance once per paid native substep; exchange conserves tagged heat."""
    support = bounded(funded) * bounded(oxygen) * bounded(perfusion)
    for side in SIDES:
        row, lobe = state["resonan"][side], p["lobes"][side]
        confidence = support * lobe["perfusion"]
        strain = lobe["strain"]
        row["signal"] = None if strain is None else strain * confidence * (1 - .75 * row["adaptation"])
        row["confidence"] = confidence if strain is not None else 0.0
        row["irradiance_w_m2"] = lobe["irradiance_w_m2"]
        row["shutter"] = lobe["shutter"]
        cue = max(0 if strain is None else strain,
                  0 if lobe["irradiance_w_m2"] is None else bounded(lobe["irradiance_w_m2"] / 1200))
        # Passive decay continues when power is lost; excitation needs support.
        target = cue * confidence
        tau = 2 if target > row["adaptation"] else 5
        row["adaptation"] += -math.expm1(-dt / tau) * (target - row["adaptation"])
    monitor = state["spandar"]
    monitor["adequacy"] = support * inputs.get("spandar_perfusion", 1)
    monitor["valid"] = bool(monitor["adequacy"] >= .5 and monitor["last_sample_s"] is not None
        and time_s - monitor["last_sample_s"] <= 5)
    az = state["azarine"]
    # Native metabolism already deposited this paid heat. Reassign its
    # location, not its amount. Baseline .2 W is split .06/.06/.04/.04 W.
    local_paid = (.04 + p["azarine_load_W"]) * funded * dt
    total_delta = total_heat_J - az["accounted_total_heat_J"]
    local = az["local_heat_J"] + total_delta * LOCAL_C / HOST_C + local_paid * (1 - LOCAL_C / HOST_C)
    # These are heat deviations relative to 37 C, not nonnegative stocks.
    # A warmer local node may exceed total excess heat while the large core
    # sits just below 37 C. Clipping it to total would erase local hotspots.
    core = total_heat_J - local
    difference = local / LOCAL_C - core / CORE_C
    conductance = .02 + .8 * perfusion * inputs.get("azarine_perfusion", 1)
    inv_capacity = 1 / LOCAL_C + 1 / CORE_C
    exchange = difference / inv_capacity * -math.expm1(-conductance * inv_capacity * dt)
    local -= exchange
    core = total_heat_J - local
    az.update(local_heat_J=local, accounted_total_heat_J=total_heat_J,
        local_temperature_C=37 + local / LOCAL_C, core_temperature_C=37 + core / CORE_C,
        thermal_gate=p["thermal_gate"], requested_load_W=p["azarine_load_W"],
        paid_load_J=az["paid_load_J"] + p["azarine_load_W"] * funded * dt,
        exchanged_heat_J=az["exchanged_heat_J"] + exchange,
        partition_error_J=abs(local + core - total_heat_J))


def sample_memory(state, *, time_s, memory_digest, prediction_error):
    monitor = state["spandar"]
    if monitor["adequacy"] >= .5 and (monitor["last_sample_s"] is None
            or time_s - monitor["last_sample_s"] >= monitor["period_s"] - 1e-9):
        monitor.update(valid=True, last_sample_s=time_s,
            sampled_digest=memory_digest, sampled_error=prediction_error)
    return deepcopy(monitor)
