"""Version-bound, finite MuJoCo integration/controller snapshots at settled boundaries.

JSON and hashes detect accidental drift; they are not an authentication boundary
against a writer able to replace both payload and digest. No pickle is loaded.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
import mujoco
from .resize import SMALL

SCHEMA = 'nasuraya-articulated-checkpoint/1'
GEOMETRY_SCHEMA = 'nasuraya-articulated-checkpoint/2'
STATE_SPEC = mujoco.mjtState.mjSTATE_INTEGRATION


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_contract(*, model_dir=SMALL, geometry_support=False):
    files = [Path(__file__).with_name(n) for n in
             ('checkpoint.py', 'stepping.py', 'balance.py', 'resize.py', 'evaluate.py', 'build.py')]
    model_dir = Path(model_dir)
    if geometry_support:
        validate_geometry_profile(model_dir)
        files += [Path(__file__).with_name(n) for n in ('support_geometry.py', 'canon_trial.py')]
    elif model_dir.resolve() != SMALL.resolve():
        raise ValueError('legacy checkpoint requires the v02 model')
    files += [model_dir/'nasuraya.xml', model_dir/'robot.yaml']
    return dict(files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                packages={n: importlib.metadata.version(n) for n in ('mujoco', 'numpy', 'scipy', 'osqp', 'PyYAML')})


def validate_geometry_profile(model_dir):
    from .canon_trial import CANDIDATE
    if Path(model_dir).resolve() != CANDIDATE.resolve():
        raise ValueError('geometry checkpoint requires the explicit v03 model')


def model_digest(model):
    """Hash compiled physical properties, including configured dt and friction."""
    buffer = np.zeros(mujoco.mj_sizeModel(model), dtype=np.uint8)
    mujoco.mj_saveModel(model, None, buffer)
    return hashlib.sha256(buffer.tobytes()).hexdigest()


def geometry_contract(model, model_dir, parameters):
    validate_geometry_profile(model_dir)
    if set(parameters) != {'stride', 'timing', 'friction', 'dt', 'push', 'com_bias_x_m'}:
        raise ValueError('complete geometry checkpoint parameters required')
    for key, value in parameters.items():
        if type(value) not in (int, float) or not np.isfinite(value):
            raise ValueError('finite checkpoint parameters required')
    expected = mujoco.MjModel.from_xml_path(str(Path(model_dir)/'nasuraya.xml'))
    expected.opt.timestep = parameters['dt']
    expected.geom_friction[:, 0] = parameters['friction']
    actual = model_digest(model)
    if actual != model_digest(expected):
        raise ValueError('compiled body differs from model source and parameters')
    return dict(source=source_contract(model_dir=model_dir, geometry_support=True),
                compiled_model_sha256=actual, geometry_support=True)


def integration_state(model, data):
    state = np.empty(mujoco.mj_stateSize(model, STATE_SPEC))
    mujoco.mj_getState(model, data, state, STATE_SPEC)
    return state


def make_checkpoint(model, data, controller, *, parameters, feet, previous_com,
                    standing_height, next_step, ticks, model_dir=SMALL, geometry_support=False):
    contract = (geometry_contract(model, model_dir, parameters) if geometry_support
                else source_contract(model_dir=model_dir))
    payload = dict(schema=GEOMETRY_SCHEMA if geometry_support else SCHEMA,
        contract=contract, parameters=parameters,
        integration=integration_state(model, data).tolist(), state_spec=int(STATE_SPEC),
        qpos=data.qpos.tolist(), qvel=data.qvel.tolist(), time=float(data.time),
        feet=feet.tolist(), previous_com=previous_com.tolist(), standing_height=float(standing_height),
        next_step=next_step, ticks=ticks,
        controller={name: getattr(controller, name).tolist() if isinstance(getattr(controller, name), np.ndarray)
                    else getattr(controller, name) for name in
                    ('anchors', 'com0', 'rot0', 'q0', 'prev', 'previous_solution', 'load_fractions',
                     'max_residual', 'solves', 'inaccurate', 'control_dt')})
    if geometry_support:
        from .support_geometry import support_bounds
        bounds = support_bounds(model)
        if not np.array_equal(controller.support_bounds, bounds):
            raise ValueError('controller support geometry differs from model')
        payload['controller']['support_bounds'] = bounds.tolist()
    return dict(value=payload, sha256=digest(payload))


def restore_checkpoint(checkpoint, model, data, parameters, *, model_dir=SMALL, geometry_support=False):
    from .stepping import ContactController, contact_state
    if not isinstance(checkpoint, dict) or set(checkpoint) != {'value', 'sha256'}:
        raise ValueError('checkpoint envelope required')
    p = checkpoint['value']
    if not isinstance(p, dict):
        raise ValueError('checkpoint payload required')
    contract = (geometry_contract(model, model_dir, parameters) if geometry_support
                else source_contract(model_dir=model_dir))
    expected_schema = GEOMETRY_SCHEMA if geometry_support else SCHEMA
    if (digest(p) != checkpoint['sha256'] or p.get('schema') != expected_schema
            or p.get('contract') != contract or p.get('parameters') != parameters
            or p.get('state_spec') != int(STATE_SPEC)):
        raise ValueError('checkpoint integrity, source, model or parameter mismatch')
    def array(value, shape):
        a = np.asarray(value, dtype=float)
        if a.shape != shape or not np.isfinite(a).all():
            raise ValueError('invalid checkpoint array')
        return a
    def scalar(value, low, high):
        if type(value) not in (int, float) or not np.isfinite(value) or not low <= value <= high:
            raise ValueError('invalid finite checkpoint scalar')
        return value
    def count(name):
        if type(p.get(name)) is not int or not 0 <= p[name] <= 10000000:
            raise ValueError('invalid checkpoint counter')
        return p[name]
    values = array(p['integration'], (mujoco.mj_stateSize(model, STATE_SPEC),))
    qpos = array(p['qpos'], (model.nq,)); qvel = array(p['qvel'], (model.nv,))
    feet = array(p['feet'], (2, 3)); previous_com = array(p['previous_com'], (3,))
    height = scalar(p['standing_height'], 0., 3.)
    time = scalar(p['time'], 0., 10000.)
    if height == 0. or height == 3. or time == 10000.:
        raise ValueError('invalid checkpoint time or height')
    next_step, ticks = count('next_step'), count('ticks')
    # Validate on scratch data first. A rejected receipt must not move the caller's body.
    restored = mujoco.MjData(model)
    mujoco.mj_setState(model, restored, values, STATE_SPEC)
    mujoco.mj_forward(model, restored)
    mujoco.mj_setState(model, restored, values, STATE_SPEC)
    if (not np.array_equal(restored.qpos, qpos) or not np.array_equal(restored.qvel, qvel)
            or float(restored.time) != time):
        raise ValueError('checkpoint fields disagree with integration state')
    if (max(abs(restored.qvel)) >= .05 or restored.qpos[2] < .8*height
            or contact_state(model, restored)[1] or min(contact_state(model, restored)[0]) <= 1):
        raise ValueError('checkpoint is not a settled double-support boundary')
    controller = ContactController(model, restored, geometry_support=geometry_support)
    shapes = dict(anchors=(2, 3), com0=(3,), rot0=(3, 3), q0=(model.nq,),
                  prev=(18, model.nv), previous_solution=(model.nv+12,), load_fractions=(2,))
    c = p['controller']
    if not isinstance(c, dict):
        raise ValueError('checkpoint controller required')
    for name, shape in shapes.items():
        value = c[name]
        if value is None and name in ('prev', 'previous_solution', 'load_fractions'):
            setattr(controller, name, None)
        else:
            setattr(controller, name, array(value, shape))
    if geometry_support:
        bounds = array(c.get('support_bounds'), (2, 4))
        if not np.array_equal(bounds, controller.support_bounds):
            raise ValueError('checkpoint support bounds differ from model geometry')
        controller.support_bounds = bounds.copy()
    if c['control_dt'] != .005:
        raise ValueError('invalid controller settings')
    scalar(c['max_residual'], 0., .01)
    for name in ('solves', 'inaccurate'):
        if type(c[name]) is not int or not 0 <= c[name] <= 10000000:
            raise ValueError('invalid controller count')
        setattr(controller, name, c[name])
    controller.max_residual = c['max_residual']
    mujoco.mj_setState(model, data, values, STATE_SPEC)
    mujoco.mj_forward(model, data)
    # Keep original warmstart and inputs, exactly, after recomputing derived contacts.
    mujoco.mj_setState(model, data, values, STATE_SPEC)
    return controller, feet, previous_com, height, next_step, ticks
