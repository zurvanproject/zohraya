"""Execute pinned reduced native models on fixed, nonsexual offline fixtures.

The spiking circuit is an external six-cell toy. Affect is authored engineering
state, and the genome is a software design proposal. None is an LLM's internal
state, evidence of feelings, an authorization source or a native-body write API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from .body import _verified_sources as _body_sources


STATE_SOURCE_ROOT = Path(__file__).with_name("state_sources")
STATE_MANIFEST_SHA256 = "7342b725ee20953ac90a0786184782e4bc324d899ac2c9c6f23f37bd2985cc87"
_RETAINED = "runtimes/tadash_body/retained_extensions/"
_BODY_PATHS = (
    _RETAINED + "neural_circuit.py",
    _RETAINED + "nasuraya_affective_layer_v01.py",
    _RETAINED + "nasuraya_emotion_spectrum_v01.py",
    "examples/nasuraya_genome/contract-v0.1.json",
    "runtimes/tadash_body/phenotype_v1.json",
)


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sources() -> tuple[dict, dict]:
    """Verify all retained bytes before executing any retained model module."""
    raw_manifest = (STATE_SOURCE_ROOT / "manifest.json").read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest() != STATE_MANIFEST_SHA256:
        raise ValueError("state source manifest changed")
    manifest = json.loads(raw_manifest)
    pins, sources = {}, {}
    for path, info in manifest["files"].items():
        raw = (STATE_SOURCE_ROOT / path).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if blob != info["git_blob_sha1"] or hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise ValueError("state source bytes changed: " + path)
        pins[path], sources[path] = info, raw
    body_manifest, body_sources = _body_sources()
    for path in _BODY_PATHS:
        pins[path], sources[path] = body_manifest["files"][path], body_sources[path]
    return pins, sources


# A fixed worker isolates legacy bare imports from the caller's sys.modules and
# ignores PYTHONPATH/site customization via Python's -I -S flags. Explicit
# -X utf8 also covers legacy Path.read_text() calls with no encoding on Windows.
# Its inputs are
# source and output directories plus a source-manifest digest, not user events.
_WORKER = r'''
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
root, output = Path(sys.argv[1]), Path(sys.argv[2])
raw_manifest = (root / 'pins.json').read_bytes()
if hashlib.sha256(raw_manifest).hexdigest() != sys.argv[3]:
    raise ValueError('isolated source manifest changed')
pins = json.loads(raw_manifest)
for path, info in pins.items():
    raw = (root / path).read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if blob != info['git_blob_sha1'] or hashlib.sha256(raw).hexdigest() != info['sha256']:
        raise ValueError('isolated source bytes changed')

sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'runtimes/tadash_body/retained_extensions'))
import neural_circuit as neural
import nasuraya_affective_layer_v01 as affect
from examples.nasuraya_genome import traits

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def numeric_leaves(value):
    if type(value) in (int, float):
        return 1
    if isinstance(value, dict):
        return sum(numeric_leaves(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(numeric_leaves(v) for v in value)
    return 0

def source_rows(paths):
    return [dict(path=path, **pins[path]) for path in paths]

retained = 'runtimes/tadash_body/retained_extensions/'
neural_path = output / 'neural.json'
circuit = neural.toy_circuit(plastic=True, learned_weight_ns=1.2, dt_ms=0.5)
initial_neural = circuit.payload()
# Fixed arm-channel current is a synthetic electrical input, not a sensor read.
for _ in range(120):
    last_step = circuit.step({'arm_input': 900.0})
circuit.save(neural_path)
restored_neural = neural.Circuit.load(neural_path)
neural_roundtrip = restored_neural.payload() == circuit.payload()
for _ in range(8):
    last_step = circuit.step({'arm_input': 0.0})
    restored_neural.step({'arm_input': 0.0})
neural_continuation = restored_neural.payload() == circuit.payload()
circuit.save(neural_path)
final_neural = neural.Circuit.load(neural_path).payload()
neural_result = {
    'status': 'executed_offline_native_fixture',
    'native_schema': neural.SCHEMA,
    'model_scope': 'external_hand_designed_six_cell_circuit',
    'fixture': {'id': 'neutral_arm_current_v1', 'dt_ms': 0.5,
                'driven_ticks': 120, 'drive_pa': {'arm_input': 900.0},
                'continuation_ticks': 8, 'continuation_drive_pa': {'arm_input': 0.0}},
    'initial_state': initial_neural, 'state': final_neural, 'last_step': last_step,
    'counts': {'cells': len(circuit.cells), 'synapses': len(circuit.synapses),
               'plastic_synapses': sum(s.plastic for s in circuit.synapses.values()),
               'neuron_state_fields': sum(len(v) for v in final_neural['neurons'].values()),
               'connection_state_fields': sum(len(v) for v in final_neural['connections'].values()),
               'parameter_numeric_leaves': numeric_leaves({key: final_neural[key]
                   for key in ('dt_ms', 'cells', 'synapses')}),
               'state_numeric_leaves': numeric_leaves(final_neural)},
    'units': {'dt_ms': 'ms', 'tick': 'simulation_tick', 'time_ms': 'ms',
              'capacitance_pf': 'pF', 'leak_ns': 'nS', 'voltage_mv': 'mV',
              'rest_mv': 'mV', 'threshold_mv': 'mV', 'reset_mv': 'mV',
              'refractory_ms': 'ms', 'refractory_until_tick': 'simulation_tick',
              'spike_count': 'count', 'weight_ns': 'nS', 'conductance_ns': 'nS',
              'minimum_ns': 'nS', 'maximum_ns': 'nS', 'a_plus_ns': 'nS', 'a_minus_ns': 'nS',
              'delay_ms': 'ms', 'decay_ms': 'ms', 'trace_ms': 'ms', 'reversal_mv': 'mV',
              'pre_trace': 'dimensionless_trace', 'post_trace': 'dimensionless_trace',
              'injected_current': 'pA'},
    'catalog_reference': {'schema': 'dios.body_inventory/1', 'json_pointer': '/neural_parameters'},
    'checkpoint_roundtrip_equal': neural_roundtrip,
    'continuation_equal': neural_continuation,
    'checkpoint_method': 'native_save_load_in_isolated_process',
    'checkpoint_sha256': hashlib.sha256(neural_path.read_bytes()).hexdigest(),
    'state_sha256': digest(final_neural),
    'source_pins': source_rows([retained + 'neural_circuit.py']),
    'llm_weights_accessed': False, 'physical_sensor_input': False,
}

affect_path = output / 'affect.json'
affect_state = affect.initial_state()
initial_affect = json.loads(canonical(affect_state))
event = {'id': 'fixture:learning:1', 'source': 'synthetic_fixture',
         'signals': {'novelty': 0.8, 'uncertainty': 0.4, 'blocked_goal': 0.3,
                     'value_goal': 0.7, 'possibility': 0.4},
         'confidence': 0.7, 'elapsed_hours': 0.25, 'energy': 0.8,
         'body': {'fatigue': 0.2, 'comfort': 0.6}, 'autonomy': 'open'}
transition = affect.transition(affect_state, event)
affect.save(affect_state, affect_path)
restored_affect = affect.load(affect_path)
affect_result = {
    'status': 'executed_offline_native_fixture', 'native_schema': affect.SCHEMA,
    'model_scope': 'authored_affective_engineering_state_only',
    'fixture': event, 'initial_state': initial_affect, 'state': restored_affect,
    'transition': transition,
    'counts': {'affect_channels': len(restored_affect['affect']),
               'somatic_channels': len(restored_affect['somatic']),
               'goal_weights': len(restored_affect['goals']),
               'relationship_records': len(restored_affect['relationships']),
               'episodes': len(restored_affect['episodes']), 'history': len(restored_affect['history']),
               'state_numeric_leaves': numeric_leaves(restored_affect)},
    'units': {'affect': 'authored_dimensionless_index_0_to_1',
              'somatic': 'simulated_dimensionless_index_0_to_1',
              'goals': 'authored_dimensionless_weight_0_to_1',
              'confidence': 'authored_appraisal_multiplier_not_epistemic_confidence',
              'clock_hours': 'simulation_hours', 'tick': 'transition_count',
              'half_life_hours': 'authored_simulation_hours'},
    'parameters': {'base': affect.BASE, 'half_life_hours': affect.HALF_LIFE_HOURS,
                   'planning_weights': affect.WEIGHTS,
                   'profiles': affect.spectrum.PROFILES,
                   'base_loadings': affect.spectrum.BASE_LOADINGS,
                   'somatic_base': affect.spectrum.SOMATIC_BASE},
    'catalog_reference': {'schema': 'dios.body_inventory/1', 'json_pointer': '/affect_parameters'},
    'checkpoint_roundtrip_equal': restored_affect == affect_state,
    'checkpoint_method': 'native_save_load_in_isolated_process',
    'checkpoint_sha256': hashlib.sha256(affect_path.read_bytes()).hexdigest(),
    'state_sha256': digest(restored_affect),
    'source_pins': source_rows([retained + 'nasuraya_affective_layer_v01.py',
                               retained + 'nasuraya_emotion_spectrum_v01.py',
                               retained + 'nasuraya_decision_core_v1.py']),
    'plan_disposition': transition['plan']['disposition'],
    'subjective_feeling_claim': False, 'external_message_sent': False,
    'relationships_manufactured': False,
}
affect_result['counts']['parameter_numeric_leaves'] = numeric_leaves(affect_result['parameters'])

# Validate the pinned 48-chromosome contract using its own source comparison,
# expression and checkpoint code. No mutation or native application is called.
contract = traits.contract()
genotype = traits.baseline()
validated_contract = traits.validate_genotype(genotype)
proposal = traits.express(genotype)
genome_path = output / 'genome.json'
traits.save(genome_path, genotype)
restored_genotype = traits.restore(json.loads(genome_path.read_bytes()))
genome_sources = ['examples/nasuraya_genome/' + name for name in
                  ('traits.py', 'chromosomes.py', 'genome48.json', 'contract-v0.1.json')]
genome_sources += ['runtimes/tadash_body/phenotype_v1.json',
    'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json']
genome_result = {
    'status': 'executed_offline_contract_and_proposal',
    'native_schema': genotype['schema'], 'native_version': traits.VERSION,
    'model_scope': 'software_design_contract_not_biological_DNA',
    'contract': contract, 'state': genotype, 'proposal': proposal,
    'counts': {'chromosomes': len(genotype['chromosomes']),
               'pairs': len({row['pair'] for row in contract['chromosomes']}),
               'loci': len(contract['loci']),
               'alleles': sum(len(row) for row in genotype['chromosomes'].values()),
               'state_numeric_leaves': numeric_leaves(genotype)},
    'units': {'loci': {key: row['unit'] for key, row in contract['loci'].items()},
              'capacity': 'dimensionless_software_proxy_not_physiology',
              'revision': 'proposal_revision'},
    'catalog_reference': {'schema': 'dios.body_inventory/1', 'json_pointer': '/genome'},
    'contract_source_comparison_equal': validated_contract == contract,
    'checkpoint_roundtrip_equal': restored_genotype == genotype,
    'checkpoint_method': 'native_checkpoint_restore_in_isolated_process',
    'checkpoint_sha256': hashlib.sha256(genome_path.read_bytes()).hexdigest(),
    'state_sha256': digest(genotype), 'source_pins': source_rows(genome_sources),
    'native_apply_allowed': proposal['compatibility']['native_apply_allowed'],
    'native_body_advanced': proposal['simulated_physiology_proxy']['payload']['native_body_advanced'],
    'mutation_performed': False, 'validated_physical_improvement': False,
}
for path, info in pins.items():
    if hashlib.sha256((root / path).read_bytes()).hexdigest() != info['sha256']:
        raise ValueError('native model changed pinned source bytes')
result = {'models': {'neural': neural_result, 'affect': affect_result, 'genome': genome_result},
          'source_bytes_unchanged': True, 'runtime_utf8_mode': sys.flags.utf8_mode}
# The redirected Windows text stream may be cp1252 even in isolated mode.
# Encode once and write bytes; the parent always receives UTF-8 JSON.
sys.stdout.buffer.write(canonical(result) + b'\n')
'''


def run_models(directory: Path) -> dict:
    """Execute three fixed native fixtures in an empty output directory.

    Returned execution labels mean local source code ran on synthetic inputs.
    They do not promote simulated states into sensor observations, learned LLM
    parameters, calibrated emotion, physical improvement or action authority.
    """
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("native_state_models_require_empty_directory")
    pins, sources = _sources()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dios-fixed-native-models-") as name:
        staging = Path(name)
        for path, raw in sources.items():
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        # Empty package markers make the legacy relative import unambiguous.
        for path in ("examples/__init__.py", "examples/nasuraya_genome/__init__.py"):
            (staging / path).write_bytes(b"")
        encoded_pins = _canonical(pins)
        (staging / "pins.json").write_bytes(encoded_pins)
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-X", "utf8", "-c", _WORKER, str(staging), str(directory.resolve()),
                 hashlib.sha256(encoded_pins).hexdigest()],
                check=False, capture_output=True, timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            digest = hashlib.sha256(error.stderr or b"").hexdigest()
            raise RuntimeError("native_state_worker_timed_out;stderr_sha256=" + digest) from None
        except OSError as error:
            raise RuntimeError("native_state_worker_launch_failed;errno=" + str(error.errno)) from None
        if completed.returncode:
            digest = hashlib.sha256(completed.stderr).hexdigest()
            # Never print the complete -c script, private output path or stderr.
            raise RuntimeError("native_state_worker_failed;returncode=" + str(completed.returncode)
                               + ";stderr_sha256=" + digest)
        try:
            executed = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            digest = hashlib.sha256(completed.stdout).hexdigest()
            raise RuntimeError("native_state_worker_invalid_json;stdout_sha256=" + digest) from None
    report = {
        "schema": "dios.nous.unified-native-state-models.v1",
        "kind": "executed_fixed_offline_native_models",
        "provenance": "pinned_native_source_on_authored_synthetic_inputs",
        **executed,
        "source_verification": "git_blob_sha1_and_sha256_before_import",
        "isolation": "fresh_python_interpreter_isolated_mode",
        "confidence": None, "calibration": "not_measured",
        "execution_permitted": False, "external_actions_taken": 0,
        "model_api_calls": 0, "network_calls": 0,
        "limitations": [
            "Native reduced models, not LLM neurons, weights or feelings.",
            "Physical units identify a toy numerical model, not a measured body.",
            "Affective confidence is an authored multiplier, not evidence confidence.",
            "The genotype is a software contract; its expression is proposal only.",
            "These outputs cannot change evidence truth, authorization or goal commitments.",
            "Roundtrip equality is software continuity, not independent scientific validation.",
            "Hashes detect changed bytes; they are not execution authority or trusted signatures.",
        ],
    }
    report["result_sha256"] = hashlib.sha256(_canonical(report)).hexdigest()
    _canonical(report)
    return report
