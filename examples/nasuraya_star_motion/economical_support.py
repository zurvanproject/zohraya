"""Opt-in one-tick fuel-aware stand controller over unchanged native dynamics.

CoordinatedSupport remains the fallback. Prediction clones spend computation,
not the owning body's stocks. This controller is not enabled by default.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from coordinated_support import CoordinatedSupport
from posture_step import PostureLoop, checksum

POLICY = dict(scales=[.75, .5, .25, 0.], max_position_regret_m=.001,
              max_speed_regret_m_s=.003, minimum_fuel_gain_J=.01)


class EconomicalSupport(CoordinatedSupport):
    def step(self, e):
        eligible = (e.command == 'stand' and self.state.phase == 'double_support'
                    and self.state.swing is None and not self.state.reflex_recovery)
        if not eligible:
            return super().step(e)
        before = self.checkpoint()
        ordinary = deepcopy(self)
        baseline = CoordinatedSupport.step(ordinary, e)
        selected = None
        probes = 1
        best_cost = baseline['ledger']['fuel_used_J']
        if baseline['balance']['model_valid']:
            target = baseline['posture']['target_com_m']
            position_bound = math.dist(ordinary.state.com_m, target) + POLICY['max_position_regret_m']
            speed_bound = math.hypot(*ordinary.state.velocity_m_s) + POLICY['max_speed_regret_m_s']
            baseline_support = baseline['contact']['joint_support_fraction']
            for scale in POLICY['scales']:
                trial = deepcopy(self)
                frame = trial._integrate_once(e, scale)
                probes += 1
                eligible_frame = (frame['balance']['model_valid']
                    and frame['contact']['joint_support_fraction'] >= min(.999, baseline_support)
                    and frame['balance']['capture_margin_m'] >= 0
                    and trial.state.phase == ordinary.state.phase
                    and trial.state.swing == ordinary.state.swing
                    and trial.state.walk_steps == ordinary.state.walk_steps
                    and trial.state.protective_steps == ordinary.state.protective_steps
                    and math.dist(trial.state.com_m, target) <= position_bound
                    and math.hypot(*trial.state.velocity_m_s) <= speed_bound)
                cost = frame['ledger']['fuel_used_J']
                if eligible_frame and cost < best_cost - POLICY['minimum_fuel_gain_J']:
                    selected, best_cost = scale, cost
        if self.checkpoint() != before:
            raise AssertionError('prediction mutated owner')
        frame = (CoordinatedSupport.step(self, e) if selected is None
                 else self._integrate_once(e, selected))
        frame['posture']['economical_governor'] = dict(
            acceleration_scale=selected, adjusted=selected is not None,
            candidate_probes=probes, predicted_fuel_J=best_cost,
            scope='same-model one-tick stand prediction; no gait or flight claim')
        return frame


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def checkpoint(body):
    payload = dict(schema='nasuraya-economical-support/1', source=source_hash(),
                   policy=deepcopy(POLICY), native=body.checkpoint())
    return dict(payload=payload, sha256=checksum(payload))


def restore(envelope):
    p = envelope['payload']
    if (set(envelope) != {'payload', 'sha256'} or envelope['sha256'] != checksum(p)
            or p['schema'] != 'nasuraya-economical-support/1'
            or p['source'] != source_hash() or p['policy'] != POLICY):
        raise ValueError('economical controller integrity/source/policy mismatch')
    body = PostureLoop.restore(p['native'])
    body.__class__ = EconomicalSupport
    return body
