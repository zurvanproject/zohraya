"""Offline body catalogue and read-only, caller-supplied software observations.

``normalize_native`` accepts exactly the following JSON object (all keys are
required; minimum_state/finite_stocks may be empty or contain null values):
  schema: "dios.native_body_export/1"
  model_id: "tadash_legacy_195kg"
  clock_domain: "simulated_seconds"
  sampled_at_s: finite number [0, 1e12]
  revision: integer [0, 1e12]
  native_checkpoint_sha256, source_observation_sha256: lowercase SHA256 strings
  minimum_state: subset of MINIMUM; finite_stocks: subset of STOCKS
  sha256: SHA256 of the other fields serialized with sort_keys=True,
          ensure_ascii=False, allow_nan=False, separators=(",", ":").

Only this closed projection is accepted, not a full body checkpoint. The helper
``project_native_snapshot`` projects the existing native_snapshot.snapshot()
result after checking its digest and closed audit vocabulary. Optional stocks
are separately caller supplied; the native observation digest does not bind them.
Neither digest authenticates the caller or grants action authority. All clocks
here are simulation clocks; a wall-clock epoch cannot establish freshness.
Serialization limits are engineering bounds, not clinical or safety envelopes.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path


SOURCE_ROOT = Path(__file__).with_name("body_sources")
MANIFEST_SHA256 = "ae29ac883f66aa0753a4266ec47c8a38314719f29a9756edeaf56cebe0eca34f"
MAIN = "a532f24a5b3eb7a31df6d200950c7287e1e96a35"
MODEL = "tadash_legacy_195kg"
TTL_S = 5.0
EXPORT_SCHEMA = "dios.native_body_export/1"
PHASES = ("double_support", "shift", "lift", "single_support", "walk_swing",
          "lower", "protective_swing", "settle", "failed")

# Bounds constrain this export format, without changing the native runtime.
MINIMUM = {
    "HR": ("beats/min", 0, 1000), "RR": ("breaths/min", 0, 1000),
    "energy": ("fraction", 0, 1), "hydration": ("fraction", 0, 1),
    "temperature": ("degC_design_proxy", -273.15, 1000),
    "sympathetic": ("index", 0, 1), "parasympathetic": ("index", 0, 1),
    "muscle_tone": ("index", 0, 1), "fatigue": ("index", 0, 1),
    "pain": ("index", 0, 1), "arousal": ("index", 0, 1),
    "valence": ("signed_index", -1, 1), "posture": ("phase", None, None),
    "balance": ("index", 0, 1), "breath_depth": ("L", 0, 1000),
    "sleep_pressure": ("index", 0, 1),
}
STOCKS = {name: (unit, 0, limit) for name, unit, limit in (
    ("fuel_J", "J", 1e15), ("reserve_J", "J", 1e15),
    ("water_L", "L", 1e9), ("heat_J", "J", 1e15),
    ("usable_o2_L", "L", 1e9), ("co2_store_L", "L", 1e9))}
# Audited initial_modules() schema, not executable hormone/organ physiology.
REGIONAL_PROXY_SPECS = {
    "endocrine": {name: "index" for name in ("adh", "acth", "cortisol", "thyroid", "insulin", "glucagon", "epo")},
    "blood": {"rbc_capacity": "index", "hemostasis": "index"},
    "immune": {"pathogen_index": "index", "inflammation": "index", "lymph_load": "index"},
    "gut": {"mouth_J": "J", "stomach_J": "J", "mouth_water_L": "L", "stomach_water_L": "L",
            "total_absorbed_J": "J", "total_absorbed_water_L": "L"},
    "renal": {"bladder_L": "L", "voided_L": "L"},
    "mouth": {"swallow_open": "boolean", "phonation": "index"},
    "reproductive": {"gonadotropin": "index", "estrogen": "index", "progesterone": "index"},
    "neural": {"origin_tick": "count", "integration_ticks": "count", "attention_hz": "Hz",
               "regulation_hz": "Hz", "optional_motor_fraction": "fraction"},
    "senses": {"irradiance": "W/m2"},
    "special": {"resonan_attention": "index", "shutter": "fraction", "spandar_last_error": "index",
                "azarine_budget_J": "J_within_retained_reserve"},
}
EXPORT_KEYS = {"schema", "model_id", "clock_domain", "sampled_at_s", "revision",
               "native_checkpoint_sha256", "source_observation_sha256",
               "minimum_state", "finite_stocks", "sha256"}
UNKNOWN = (
    "empirical_calibration", "arterial_gases", "independent_3d_organ_geometry",
    "physical_sensor_attachment", "external_world_without_supplied_observation",
)
CHANNELS = ("vision", "hearing", "smell", "taste", "touch")


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("finite JSON required") from error


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _number(value, name, low=0, high=1e12):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError("invalid finite number: " + name)
    return value


def _hash(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid digest: " + name)


def _closed(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("closed schema required: " + name)


def _measurements(value, specs, name):
    if type(value) is not dict or set(value) - set(specs):
        raise ValueError("unknown measurement fields: " + name)
    result = {}
    for key, number in value.items():
        if number is None:
            result[key] = None
        elif key == "posture":
            if type(number) is not str or number not in PHASES:
                raise ValueError("unknown posture phase")
            result[key] = number
        else:
            _, low, high = specs[key]
            result[key] = _number(number, name + "." + key, low, high)
    return result


def _verified_sources():
    raw_manifest = (SOURCE_ROOT / "manifest.json").read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest() != MANIFEST_SHA256:
        raise ValueError("body source manifest changed")
    manifest = json.loads(raw_manifest)
    sources = {}
    for path, info in manifest["files"].items():
        raw = (SOURCE_ROOT / path).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if blob != info["git_blob_sha1"] or hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise ValueError("body source bytes changed: " + path)
        sources[path] = raw
    return manifest, sources


def _literal_assign(source, name):
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in statement.targets):
            node = statement.value
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
                return {item.arg: ast.literal_eval(item.value) for item in node.keywords}
            return ast.literal_eval(node)
    raise ValueError("missing pinned definition: " + name)


def _source(path, manifest):
    return dict(path=path, **manifest["files"][path])


def _native_source():
    return dict(path="runtimes/tadash_body/persistent_embodiment_v1.py", commit=MAIN,
                git_blob_sha1="db87b7b1f47f33c443d803bb31b0c5f8e63af127",
                status="audited_source_reference_not_imported")


def _static_leaves(value, prefix=""):
    """Keep every source design leaf; unknown units remain explicitly unknown."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _static_leaves(child, prefix + "." + key if prefix else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _static_leaves(child, prefix + "[" + str(index) + "]")
    else:
        leaf = prefix.rsplit(".", 1)[-1].split("[")[0]
        unit = next((u for suffix, u in (
            ("_cm", "cm"), ("_kg", "kg"), ("_m", "m"), ("_mm", "mm"),
            ("_bpm", "beats/min"), ("_l_min", "L/min"), ("_mmHg", "mmHg"),
            ("_l", "L"), ("_w", "W"), ("_cm2", "cm2"), ("_m2", "m2"))
                     if leaf.lower().endswith(suffix.lower())), "undeclared_in_source")
        yield dict(name=prefix, value=value, unit=unit, range=None,
                   status="authored_definition_only")


def inventory():
    """Execute the pinned atlas builder; catalogue other definitions without running them.

    Coverage is explicit: full atlas and phenotype leaves, genome contract loci
    and alleles, affect channels/somatic/goals, neural dataclass definitions and
    dynamic state names. Native physics constants outside this scope are a gap.
    """
    manifest, sources = _verified_sources()
    atlas_path = "tools/fullbody_design_atlas.py"
    # Exact, hash-verified source, with __main__ disabled; no native runtime import.
    namespace = {"__name__": "_dios_pinned_body_atlas", "__file__": str(SOURCE_ROOT / atlas_path)}
    exec(compile(sources[atlas_path], str(SOURCE_ROOT / atlas_path), "exec"), namespace)
    anatomy, phenotype, fingerprints = namespace["read_pinned"](SOURCE_ROOT)
    registry = namespace["build_registry"](anatomy, phenotype, fingerprints)
    gaps = namespace["gap_report"](registry)

    contract_path = "examples/nasuraya_genome/contract-v0.1.json"
    contract = json.loads(sources[contract_path])
    genome = []
    for chromosome in contract["chromosomes"]:
        for locus in chromosome["loci"]:
            spec = contract["loci"][locus]
            genome.append(dict(name=chromosome["id"] + "." + locus,
                trait=spec["name"], unit=spec["unit"],
                range=[spec["minimum"], spec["maximum"]], default=spec["default"],
                status="catalog_only_not_applied", source=_source(contract_path, manifest)))

    folder = "runtimes/tadash_body/retained_extensions/"
    af_path, spectrum_path = folder + "nasuraya_affective_layer_v01.py", folder + "nasuraya_emotion_spectrum_v01.py"
    base = _literal_assign(sources[af_path], "BASE")
    profiles = _literal_assign(sources[spectrum_path], "PROFILES")
    somatic = _literal_assign(sources[spectrum_path], "SOMATIC_BASE")
    affect = [dict(name="affect." + name, unit="index", range=[0, 1], default=value,
                   status="catalog_only_not_wired", source=_source(af_path if name in base else spectrum_path, manifest))
              for name, value in dict(base, **dict.fromkeys(profiles, 0)).items()]
    affect += [dict(name="somatic." + name, unit="index", range=[0, 1], default=value,
                    status="catalog_only_not_wired", source=_source(spectrum_path, manifest))
               for name, value in somatic.items()]
    affect += [dict(name="goals." + name, unit="index", range=[0, 1], default=None,
                    status="catalog_only_not_wired", source=_source(af_path, manifest))
               for name in sorted(_literal_assign(sources[af_path], "GOAL_NAMES"))]

    neural_path = folder + "neural_circuit.py"
    neural = []
    for cls in ast.parse(sources[neural_path]).body:
        if isinstance(cls, ast.ClassDef) and cls.name in ("Cell", "Synapse"):
            for field in cls.body:
                if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name):
                    name = field.target.id
                    unit = next((u for suffix, u in (("_pf", "pF"), ("_ns", "nS"), ("_mv", "mV"), ("_ms", "ms")) if name.endswith(suffix)), "identity_or_boolean")
                    neural.append(dict(name=cls.name + "." + name, unit=unit, range=None,
                        default=ast.literal_eval(field.value) if field.value is not None else None,
                        status="catalog_only_not_wired", source=_source(neural_path, manifest)))
    for name, unit in (("dt_ms", "ms"), ("tick", "count"), ("voltage_mv", "mV"),
                       ("refractory_until_tick", "count"), ("spike_count", "count"),
                       ("weight_ns", "nS"), ("conductance_ns", "nS"),
                       ("pre_trace", "index"), ("post_trace", "index"),
                       ("attention_hz", "Hz"), ("regulation_hz", "Hz")):
        neural.append(dict(name="state." + name, unit=unit, range=None, value=None,
                           status="catalog_only_not_wired", source=_source(neural_path, manifest)
                           if name not in ("attention_hz", "regulation_hz") else dict(
                               path="runtimes/tadash_body/unified_body_v2.py", commit=MAIN,
                               git_blob_sha1="7fd9a3139743c16f9bf1cc5067d8070c3facd62f")))

    native = [dict(name=group + "." + name, unit=spec[0],
                   export_range=list(spec[1:]) if name != "posture" else list(PHASES),
                   range_kind="serialization_bound_not_physiological_safety",
                   status="awaiting_caller_supplied_software_export", source=_native_source())
              for group, specs in (("minimum_state", MINIMUM), ("finite_stocks", STOCKS))
              for name, spec in specs.items()]
    regional = [dict(name=group + "." + name, unit=unit,
        range=[0, 1] if unit in ("index", "fraction") and name != "spandar_last_error" else None,
        status="catalog_only_not_wired", value=None,
        source=dict(path="runtimes/tadash_body/unified_body_v2.py", commit=MAIN,
                    git_blob_sha1="7fd9a3139743c16f9bf1cc5067d8070c3facd62f",
                    definition="initial_modules; audited_reference_not_imported"))
        for group, fields in REGIONAL_PROXY_SPECS.items() for name, unit in fields.items()]
    result = dict(schema="dios.body_inventory/1", atlas=registry, gaps=gaps,
        atlas_builder_executed=True, native_runtime_imported=False,
        models=[dict(id=MODEL, mass_kg=195, crown_cm=250, tail_cm=120, status="retained_reduced_simulation"),
                dict(id="nasuraya_visual_target_78kg", mass_kg=78, crown_cm=170, horn_tip_cm=192, tail_cm=85, status="authored_visual_target"),
                dict(id="nasuraya_mujoco_v03_78kg", mass_kg=78, crown_cm=170, tail_cm=85,
                     status="separate_mechanical_lineage_not_imported_or_run",
                     source=dict(commit="c6bac77802a7fab9178fb00eed28e3c4410b9482",
                                 path="assets/nasuraya_articulated_v03/nasuraya.xml",
                                 git_blob_sha1="b7177c1a43715a8eb27e1f837c7c72bbbcee932e"))],
        phenotype=dict(parameters=list(_static_leaves(phenotype)),
                       source=_source("runtimes/tadash_body/phenotype_v1.json", manifest)),
        native_parameters=native, genome=dict(chromosomes=48, loci=28, allele_parameters=genome,
            native_apply_allowed=False, status="catalog_only_not_applied"),
        affect_parameters=affect, neural_parameters=neural, regional_proxy_parameters=regional,
        alias_limits=dict(glucose_proxy="fuel_fraction_not_glucose_measurement",
            blood_volume_proxy="water_fraction_not_blood_measurement",
            perfusion_state="hydration_proxy_not_flow_measurement",
            vagal_state="regulatory_index_not_neural_recording",
            valence="native_signed_minus1_to1; body_loop_policy_valence_zero_to1_is_separate"),
        unsupported=list(UNKNOWN) + ["full_native_physics_parameter_catalogue",
            "78kg_calibrated_whole_body_physiology", "live_sensors", "native_action_execution",
            "native_checkpoint_migration", "genome_application", "neural_or_affect_runtime_wiring"],
        source_manifest=deepcopy(manifest), native_cycles_executed=0, action_requests_executed=0,
        model_api_calls=0, physical_sensor_connected=False)
    _canonical(result)
    return result


def _dynamic(minimum=None, stocks=None, *, stale=False):
    result = {}
    for group, values, specs in (("minimum_state", minimum or {}, MINIMUM),
                                  ("finite_stocks", stocks or {}, STOCKS)):
        result[group] = {}
        for key, spec in specs.items():
            value = values.get(key)
            status = "unknown_stale" if stale and value is not None else (
                "unknown_missing" if value is None else "caller_supplied_simulation")
            result[group][key] = dict(value=None if stale else value, unit=spec[0], status=status)
    return result


def default_snapshot():
    return dict(schema="dios.body_snapshot/1", inventory=inventory(),
                dynamic=dict(schema="dios.normalized_body/1", model_id=MODEL,
                    status="unknown_no_observation", source_kind="no_observation",
                    sampled_at_s=None, age_s=None, clock_domain="simulated_seconds",
                    source_authenticated=False, physical_sensor_connected=False,
                    model_lineage_verified=False, model_id_status="no_observation",
                    **_dynamic()), native_cycles_executed=0, action_requests_executed=0)


def normalize_native(record, *, now_s):
    _closed(record, EXPORT_KEYS, "native export")
    if record["schema"] != EXPORT_SCHEMA or record["model_id"] != MODEL or record["clock_domain"] != "simulated_seconds":
        raise ValueError("schema, model or simulation clock mismatch")
    sampled = _number(record["sampled_at_s"], "sampled_at_s")
    now = _number(now_s, "now_s")
    if sampled > now:
        raise ValueError("future simulated sample")
    revision = record["revision"]
    if type(revision) is not int or not 0 <= revision <= 10**12:
        raise ValueError("invalid source revision")
    for key in ("native_checkpoint_sha256", "source_observation_sha256", "sha256"):
        _hash(record[key], key)
    minimum = _measurements(record["minimum_state"], MINIMUM, "minimum_state")
    stocks = _measurements(record["finite_stocks"], STOCKS, "finite_stocks")
    if _digest({k: v for k, v in record.items() if k != "sha256"}) != record["sha256"]:
        raise ValueError("export digest mismatch")
    age = now - sampled
    result = dict(schema="dios.normalized_body/1", model_id=MODEL,
        status="stale" if age > TTL_S else "fresh", source_kind="caller_supplied_software_export",
        source_authenticated=False, integrity_verified=True,
        model_lineage_verified=False, model_id_status="caller_declared_not_verified",
        stock_provenance="caller_supplied_not_bound_to_native_snapshot_digest",
        physical_sensor_connected=False, clock_domain="simulated_seconds",
        sampled_at_s=sampled, evaluated_at_s=now, age_s=age, ttl_s=TTL_S, revision=revision,
        native_checkpoint_sha256=record["native_checkpoint_sha256"],
        source_observation_sha256=record["source_observation_sha256"],
        export_sha256=record["sha256"], native_cycles_executed=0,
        action_requests_executed=0, **_dynamic(minimum, stocks, stale=age > TTL_S))
    _canonical(result)
    return result


def _validate_audit(audit, snapshot):
    keys = {"schema", "kind", "body_revision", "body_time_s", "evaluation_time_s", "age_s",
            "body_state_fresh", "saved_minimum_state", "available_sensory_channels",
            "expired_sensory_channels", "upper_controller_walk_guard_allows", "walking_restrictions",
            "request_new_evidence", "unknown", "recent_prediction_errors", "uncertainty",
            "uncertainty_is", "unified_parameter_learning_demonstrated", "empirical_validation",
            "subjective_experience_probability"}
    _closed(audit, keys, "native audit")
    constants = dict(schema="nasuraya-audited-self-model/1.0", kind="readout_of_saved_simulation",
        uncertainty_is="engineering_index_not_calibrated_probability",
        unified_parameter_learning_demonstrated=False, empirical_validation=False,
        subjective_experience_probability=None)
    if any(type(audit[k]) is not type(v) or audit[k] != v for k, v in constants.items()):
        raise ValueError("native audit scope changed")
    if type(audit["body_revision"]) is not int or audit["body_revision"] != snapshot["revision"]:
        raise ValueError("audit revision mismatch")
    for key in ("body_time_s", "evaluation_time_s"):
        _number(audit[key], key)
        if audit[key] != snapshot["time_s"]:
            raise ValueError("snapshot and audit clocks differ")
    if type(audit["age_s"]) not in (int, float) or audit["age_s"] != 0:
        raise ValueError("native snapshot audit must be current at its own time")
    for key in ("body_state_fresh", "upper_controller_walk_guard_allows", "request_new_evidence"):
        if type(audit[key]) is not bool:
            raise ValueError("explicit audit boolean required")
    if audit["body_state_fresh"] is not True:
        raise ValueError("native snapshot audit is not current")
    if _measurements(audit["saved_minimum_state"], MINIMUM, "audit minimum") != snapshot["minimum"]:
        raise ValueError("audit minimum mismatch")
    for key, allowed in (("available_sensory_channels", CHANNELS), ("expired_sensory_channels", CHANNELS),
        ("walking_restrictions", ("request_current_body_sample", "low_energy", "fatigue", "pain", "sleep_pressure")),
        ("unknown", (*UNKNOWN, "current_body_state", *("sensory_channel:" + c for c in CHANNELS)))):
        value = audit[key]
        if type(value) is not list or len(value) > len(allowed) or any(type(v) is not str or v not in allowed for v in value) or len(set(value)) != len(value):
            raise ValueError("unknown audit vocabulary: " + key)
    errors = audit["recent_prediction_errors"]
    if type(errors) is not list or len(errors) > 16:
        raise ValueError("bounded prediction errors required")
    for error in errors:
        _number(error, "prediction error", 0, 1e12)
    _number(audit["uncertainty"], "uncertainty", 0, 1)


def project_native_snapshot(snapshot, *, model_id, finite_stocks=None):
    """Project validated native_snapshot fields; never copy narratives or private state.

    ``model_id`` is an explicit caller declaration, never inferred from an opaque
    snapshot digest. This adapter cannot authenticate or verify the model lineage.
    ``finite_stocks`` is an optional separately supplied numeric ledger projection,
    not a claim that native_snapshot's observation hash covers the ledger values.
    """
    if model_id != MODEL:
        raise ValueError("unsupported declared native model")
    _closed(snapshot, {"native_sha", "revision", "time_s", "minimum", "audit",
                      "body_before_digest", "source_identity", "evidence_kind", "observation_sha256"},
            "native_snapshot")
    if snapshot["evidence_kind"] != "source_pinned_software_observation":
        raise ValueError("unsupported native observation kind")
    for key in ("native_sha", "body_before_digest", "source_identity", "observation_sha256"):
        _hash(snapshot[key], key)
    _number(snapshot["time_s"], "time_s")
    if type(snapshot["revision"]) is not int or not 0 <= snapshot["revision"] <= 10**12:
        raise ValueError("invalid native revision")
    minimum = _measurements(snapshot["minimum"], MINIMUM, "native minimum")
    _validate_audit(snapshot["audit"], snapshot)
    if _digest({k: v for k, v in snapshot.items() if k != "observation_sha256"}) != snapshot["observation_sha256"]:
        raise ValueError("native observation digest mismatch")
    result = dict(schema=EXPORT_SCHEMA, model_id=MODEL, clock_domain="simulated_seconds",
        sampled_at_s=snapshot["time_s"], revision=snapshot["revision"],
        native_checkpoint_sha256=snapshot["native_sha"],
        source_observation_sha256=snapshot["observation_sha256"],
        minimum_state=deepcopy(minimum), finite_stocks=_measurements(
            {} if finite_stocks is None else finite_stocks, STOCKS, "finite_stocks"))
    result["sha256"] = _digest(result)
    normalize_native(result, now_s=result["sampled_at_s"])
    return result
