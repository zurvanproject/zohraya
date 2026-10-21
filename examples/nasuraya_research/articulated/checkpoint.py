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
STATE_SPEC = mujoco.mjtState.mjSTATE_INTEGRATION


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_contract():
    files = [Path(__file__).with_name(n) for n in
             ('checkpoint.py', 'stepping.py', 'balance.py', 'resize.py', 'evaluate.py', 'build.py')]
    files += [SMALL/'nasuraya.xml', SMALL/'robot.yaml']
    return dict(files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                packages={n: importlib.metadata.version(n) for n in ('mujoco', 'numpy', 'scipy', 'osqp', 'PyYAML')})


def integration_state(model, data):
    state = np.empty(mujoco.mj_stateSize(model, STATE_SPEC))
    mujoco.mj_getState(model, data, state, STATE_SPEC)
    return state


def make_checkpoint(model, data, controller, *, parameters, feet, previous_com,
                    standing_height, next_step, ticks):
    payload = dict(schema=SCHEMA, contract=source_contract(), parameters=parameters,
        integration=integration_state(model, data).tolist(), state_spec=int(STATE_SPEC),
        qpos=data.qpos.tolist(), qvel=data.qvel.tolist(), time=float(data.time),
        feet=feet.tolist(), previous_com=previous_com.tolist(), standing_height=float(standing_height),
        next_step=next_step, ticks=ticks,
        controller={name: getattr(controller, name).tolist() if isinstance(getattr(controller, name), np.ndarray)
                    else getattr(controller, name) for name in
                    ('anchors', 'com0', 'rot0', 'q0', 'prev', 'previous_solution', 'load_fractions',
                     'max_residual', 'solves', 'inaccurate', 'control_dt')})
    return dict(value=payload, sha256=digest(payload))


def restore_checkpoint(checkpoint, model, data, parameters):
    from .stepping import ContactController, contact_state
    if not isinstance(checkpoint, dict) or set(checkpoint) != {'value', 'sha256'}:
        raise ValueError('checkpoint envelope required')
    p = checkpoint['value']
    if (digest(p) != checkpoint['sha256'] or p.get('schema') != SCHEMA
            or p.get('contract') != source_contract() or p.get('parameters') != parameters
            or p.get('state_spec') != int(STATE_SPEC)):
        raise ValueError('checkpoint integrity, source, model or parameter mismatch')
    def array(value, shape):
        a = np.asarray(value, dtype=float)
        if a.shape != shape or not np.isfinite(a).all():
            raise ValueError('invalid checkpoint array')
        return a
    def count(name):
        if type(p.get(name)) is not int or not 0 <= p[name] <= 10000000:
            raise ValueError('invalid checkpoint counter')
        return p[name]
    values = array(p['integration'], (mujoco.mj_stateSize(model, STATE_SPEC),))
    qpos = array(p['qpos'], (model.nq,)); qvel = array(p['qvel'], (model.nv,))
    feet = array(p['feet'], (2, 3)); previous_com = array(p['previous_com'], (3,))
    if not 0 < p['standing_height'] < 3 or not 0 <= p['time'] < 10000:
        raise ValueError('invalid checkpoint time or height')
    next_step, ticks = count('next_step'), count('ticks')
    mujoco.mj_setState(model, data, values, STATE_SPEC)
    mujoco.mj_forward(model, data)
    # Recompute derived geometry but preserve the exact saved warmstart/control state.
    mujoco.mj_setState(model, data, values, STATE_SPEC)
    if (not np.array_equal(data.qpos, qpos) or not np.array_equal(data.qvel, qvel)
            or float(data.time) != p['time']):
        raise ValueError('checkpoint fields disagree with integration state')
    if (max(abs(data.qvel)) >= .05 or data.qpos[2] < .8*p['standing_height']
            or contact_state(model, data)[1] or min(contact_state(model, data)[0]) <= 1):
        raise ValueError('checkpoint is not a settled double-support boundary')
    controller = ContactController(model, data)
    shapes = dict(anchors=(2, 3), com0=(3,), rot0=(3, 3), q0=(model.nq,),
                  prev=(18, model.nv), previous_solution=(model.nv+12,), load_fractions=(2,))
    c = p['controller']
    for name, shape in shapes.items():
        value = c[name]
        if value is None and name in ('prev', 'previous_solution', 'load_fractions'):
            setattr(controller, name, None)
        else:
            setattr(controller, name, array(value, shape))
    if c['control_dt'] != .005 or not 0 <= c['max_residual'] <= .01:
        raise ValueError('invalid controller settings')
    for name in ('solves', 'inaccurate'):
        if type(c[name]) is not int or not 0 <= c[name] <= 10000000:
            raise ValueError('invalid controller count')
        setattr(controller, name, c[name])
    controller.max_residual = c['max_residual']
    return controller, feet, previous_com, p['standing_height'], next_step, ticks
