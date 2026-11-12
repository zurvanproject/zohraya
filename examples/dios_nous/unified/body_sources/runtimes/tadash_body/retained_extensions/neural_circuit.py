"""A small external spiking-circuit simulator, in ms, mV, pF, nS and pA.

Conductance LIF cells, delayed exponential synapses and bounded pair STDP.
Named roles are stipulated toy functions, not reconstructed brain anatomy.
This module does not access or change the language model's neurons or weights.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile


SCHEMA = "nasuraya.spiking_circuit/1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def finite(value, name, lower=None, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if (not math.isfinite(value) or (lower is not None and value < lower)
            or (upper is not None and value > upper)):
        raise ValueError(f"{name} outside declared range")
    return float(value)


def integer(value, name, lower=0):
    if type(value) is not int or value < lower:
        raise ValueError(f"{name} must be an integer >= {lower}")
    return value


@dataclass(frozen=True)
class Cell:
    name: str
    capacitance_pf: float = 120.0
    leak_ns: float = 6.0
    rest_mv: float = -65.0
    threshold_mv: float = -50.0
    reset_mv: float = -65.0
    refractory_ms: float = 2.0

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Cell needs a name")
        for f in fields(self):
            if f.name != "name":
                finite(getattr(self, f.name), f.name)
        if (self.capacitance_pf <= 0 or self.leak_ns <= 0 or self.refractory_ms < 0
                or self.threshold_mv <= max(self.rest_mv, self.reset_mv)):
            raise ValueError("Invalid cell parameters")


@dataclass(frozen=True)
class Synapse:
    name: str
    pre: str
    post: str
    weight_ns: float
    delay_ms: float = 2.0
    decay_ms: float = 5.0
    reversal_mv: float = 0.0
    plastic: bool = False
    minimum_ns: float = 0.0
    maximum_ns: float = 20.0
    a_plus_ns: float = 0.25
    a_minus_ns: float = 0.26
    trace_ms: float = 20.0

    def __post_init__(self):
        for name in ("name", "pre", "post"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError("Synapse identities must be nonempty strings")
        if type(self.plastic) is not bool:
            raise ValueError("Plasticity must be explicit")
        for f in fields(self):
            if f.name not in {"name", "pre", "post", "plastic"}:
                finite(getattr(self, f.name), f.name)
        if (self.delay_ms <= 0 or self.decay_ms <= 0 or self.trace_ms <= 0
                or self.minimum_ns < 0 or self.maximum_ns < self.minimum_ns
                or not self.minimum_ns <= self.weight_ns <= self.maximum_ns
                or self.a_plus_ns < 0 or self.a_minus_ns < 0):
            raise ValueError("Invalid synapse parameters")
        if self.plastic and self.reversal_mv < 0:
            raise ValueError("This prototype supports excitatory plasticity only")


class Circuit:
    def __init__(self, cells, synapses, *, dt_ms=0.5, source=None):
        self.dt_ms = finite(dt_ms, "dt_ms", lower=0.01, upper=1.0)
        self.cells = {cell.name: cell for cell in cells}
        self.synapses = {syn.name: syn for syn in synapses}
        if not self.cells or len(self.cells) != len(cells) or len(self.synapses) != len(synapses):
            raise ValueError("A nonempty circuit and unique identities are required")
        self.delays = {}
        for syn in self.synapses.values():
            if syn.pre not in self.cells or syn.post not in self.cells:
                raise ValueError("Synapse points to an unknown cell")
            ticks = round(syn.delay_ms / self.dt_ms)
            if ticks < 1 or not math.isclose(ticks * self.dt_ms, syn.delay_ms, abs_tol=1e-10):
                raise ValueError("Delay must be a positive multiple of dt_ms")
            self.delays[syn.name] = ticks
        self.tick = 0
        self.neurons = {key: {"voltage_mv": cell.rest_mv, "refractory_until_tick": 0,
                              "spike_count": 0} for key, cell in self.cells.items()}
        self.connections = {key: {"weight_ns": syn.weight_ns, "conductance_ns": 0.0,
                                  "pre_trace": 0.0, "post_trace": 0.0}
                            for key, syn in self.synapses.items()}
        self.pending = []
        self.source = deepcopy(source or {"kind": "declared_synthetic_circuit"})

    def step(self, currents_pa=None):
        currents = dict(currents_pa or {})
        if set(currents) - set(self.cells):
            raise ValueError("Current requested for unknown cell")
        currents = {k: finite(v, "injected current", lower=-10000, upper=10000)
                    for k, v in currents.items()}
        # State is at t=tick*dt. Arrivals at this boundary affect the next interval.
        due = [item for item in self.pending if item[0] == self.tick]
        self.pending = [item for item in self.pending if item[0] > self.tick]
        deliveries = []
        for _, key in sorted(due):
            syn, state = self.synapses[key], self.connections[key]
            # Transmission uses the weight immediately before this arrival's LTD.
            delivered = state["weight_ns"]
            state["conductance_ns"] += delivered
            if syn.plastic:
                state["weight_ns"] = max(syn.minimum_ns,
                    state["weight_ns"] - syn.a_minus_ns * state["post_trace"])
            state["pre_trace"] += 1.0
            deliveries.append({"synapse": key, "delivered_ns": delivered})
        next_tick = self.tick + 1
        conductance = {k: 0.0 for k in self.cells}
        reversal_drive = {k: 0.0 for k in self.cells}
        for key, syn in self.synapses.items():
            state = self.connections[key]
            decay = math.exp(-self.dt_ms / syn.decay_ms)
            # Exact mean of the decaying conductance over this interval. Freezing
            # that mean in the membrane solution is an exponential-Euler approximation.
            average = state["conductance_ns"] * syn.decay_ms / self.dt_ms * (1 - decay)
            conductance[syn.post] += average
            reversal_drive[syn.post] += average * syn.reversal_mv
            state["conductance_ns"] *= decay
            trace_decay = math.exp(-self.dt_ms / syn.trace_ms)
            state["pre_trace"] *= trace_decay
            state["post_trace"] *= trace_decay
        spikes, before_reset = [], {}
        for key, cell in self.cells.items():
            state = self.neurons[key]
            if self.tick < state["refractory_until_tick"]:
                candidate = cell.reset_mv
            else:
                total = cell.leak_ns + conductance[key]
                equilibrium = (cell.leak_ns * cell.rest_mv + reversal_drive[key]
                               + currents.get(key, 0.0)) / total
                candidate = equilibrium + (state["voltage_mv"] - equilibrium) * math.exp(
                    -self.dt_ms * total / cell.capacitance_pf)
                if candidate >= cell.threshold_mv:
                    spikes.append(key)
                    state["spike_count"] += 1
                    # Ceil avoids shortening a non-grid refractory interval.
                    state["refractory_until_tick"] = next_tick + math.ceil(
                        cell.refractory_ms / self.dt_ms)
            before_reset[key] = candidate
            state["voltage_mv"] = cell.reset_mv if key in spikes else candidate
        for key, syn in self.synapses.items():
            state = self.connections[key]
            if syn.post in spikes:
                if syn.plastic:
                    state["weight_ns"] = min(syn.maximum_ns,
                        state["weight_ns"] + syn.a_plus_ns * state["pre_trace"])
                state["post_trace"] += 1.0
            if syn.pre in spikes:
                self.pending.append([next_tick + self.delays[key], key])
        self.pending.sort()
        self.tick = next_tick
        return {"tick": self.tick, "time_ms": self.tick * self.dt_ms,
                "spikes": spikes, "pre_reset_voltage_mv": before_reset,
                "voltages_mv": {k: s["voltage_mv"] for k, s in self.neurons.items()},
                "weights_ns": {k: s["weight_ns"] for k, s in self.connections.items()},
                "deliveries_at_ms": (self.tick - 1) * self.dt_ms,
                "deliveries": deliveries}

    def payload(self):
        return {"schema": SCHEMA, "dt_ms": self.dt_ms, "tick": self.tick,
                "cells": [asdict(cell) for cell in self.cells.values()],
                "synapses": [asdict(syn) for syn in self.synapses.values()],
                "neurons": deepcopy(self.neurons), "connections": deepcopy(self.connections),
                "pending": deepcopy(self.pending), "source": deepcopy(self.source)}

    @classmethod
    def restore(cls, payload):
        if not isinstance(payload, dict) or set(payload) != {
                "schema", "dt_ms", "tick", "cells", "synapses", "neurons", "connections",
                "pending", "source"} or payload["schema"] != SCHEMA:
            raise ValueError("Unsupported or incomplete circuit checkpoint")
        if not isinstance(payload["cells"], list) or not isinstance(payload["synapses"], list):
            raise ValueError("Cell and synapse records must be lists")
        try:
            model = cls([Cell(**v) for v in payload["cells"]],
                        [Synapse(**v) for v in payload["synapses"]],
                        dt_ms=payload["dt_ms"], source=payload["source"])
        except TypeError as exc:
            raise ValueError("Invalid circuit specification") from exc
        integer(payload["tick"], "tick")
        if (not isinstance(payload["neurons"], dict) or not isinstance(payload["connections"], dict)
                or set(payload["neurons"]) != set(model.cells)
                or set(payload["connections"]) != set(model.synapses)):
            raise ValueError("Checkpoint identities do not match circuit")
        for key, state in payload["neurons"].items():
            if not isinstance(state, dict) or set(state) != {
                    "voltage_mv", "refractory_until_tick", "spike_count"}:
                raise ValueError("Incomplete cell state")
            finite(state["voltage_mv"], "voltage_mv")
            if state["voltage_mv"] >= model.cells[key].threshold_mv:
                raise ValueError("A saved cell cannot be above threshold")
            until = integer(state["refractory_until_tick"], "refractory_until_tick")
            if until > payload["tick"] + math.ceil(model.cells[key].refractory_ms / model.dt_ms):
                raise ValueError("Impossible refractory interval")
            integer(state["spike_count"], "spike_count")
        for key, state in payload["connections"].items():
            if not isinstance(state, dict) or set(state) != {
                    "weight_ns", "conductance_ns", "pre_trace", "post_trace"}:
                raise ValueError("Incomplete synapse state")
            syn = model.synapses[key]
            finite(state["weight_ns"], "weight_ns", lower=syn.minimum_ns, upper=syn.maximum_ns)
            for name in ("conductance_ns", "pre_trace", "post_trace"):
                finite(state[name], name, lower=0)
            if not syn.plastic and state["weight_ns"] != syn.weight_ns:
                raise ValueError("Fixed synapse weight changed")
        if not isinstance(payload["pending"], list):
            raise ValueError("Pending arrivals must be a list")
        for item in payload["pending"]:
            if (not isinstance(item, list) or len(item) != 2 or not isinstance(item[1], str)
                    or item[1] not in model.synapses):
                raise ValueError("Invalid pending arrival")
            tick = integer(item[0], "arrival_tick", lower=payload["tick"])
            if tick > payload["tick"] + model.delays[item[1]]:
                raise ValueError("Arrival exceeds the declared transmission delay")
        if payload["pending"] != sorted(payload["pending"]):
            raise ValueError("Pending arrivals are not ordered")
        model.tick = payload["tick"]
        model.neurons = deepcopy(payload["neurons"])
        model.connections = deepcopy(payload["connections"])
        model.pending = deepcopy(payload["pending"])
        return model

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.payload()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(canonical({"payload": payload, "sha256": digest(payload)}) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path):
        envelope = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}
                or digest(envelope["payload"]) != envelope["sha256"]):
            raise ValueError("Circuit checkpoint checksum mismatch")
        return cls.restore(envelope["payload"])


def toy_circuit(*, plastic=True, learned_weight_ns=1.2, dt_ms=0.5):
    cells = [Cell(name) for name in ("seat_input", "arm_input", "attention",
                                    "association", "regulation", "brake")]
    synapses = [
        Synapse("seat_to_attention", "seat_input", "attention", 12.0),
        Synapse("arm_to_attention", "arm_input", "attention", 12.0),
        Synapse("attention_to_association", "attention", "association", learned_weight_ns,
                plastic=plastic, maximum_ns=12.0),
        Synapse("association_to_attention", "association", "attention", 1.0, delay_ms=4.0),
        Synapse("association_to_regulation", "association", "regulation", 12.0),
        Synapse("attention_to_brake", "attention", "brake", 2.0),
        Synapse("regulation_to_brake", "regulation", "brake", 12.0),
        Synapse("brake_to_attention", "brake", "attention", 10.0,
                reversal_mv=-75.0, decay_ms=10.0),
        Synapse("brake_to_association", "brake", "association", 10.0,
                reversal_mv=-75.0, decay_ms=10.0),
    ]
    return Circuit(cells, synapses, dt_ms=dt_ms,
                   source={"kind": "hand_designed_six_cell_circuit", "anatomical_mapping": False})


def sensory_currents(observation):
    """A declared encoding of two existing toy-body channels, not a sensor read."""
    if (not isinstance(observation, dict) or observation.get("kind") != "simulator_observation"
            or observation.get("scope") != "nasuraya.sensory_attention/1"):
        raise ValueError("Requires a sensory-layer simulator observation")
    channels = observation["channels"]
    pressure = finite(channels["contact"]["seat_pressure_pa"], "seat pressure", lower=0)
    load = finite(channels["gravity"]["unsupported_arm_force_n"], "arm load", lower=0)
    return {"seat_input": min(10000.0, pressure / 30.0),
            "arm_input": min(10000.0, load * 2.0)}
