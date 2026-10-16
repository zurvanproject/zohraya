"""Opt-in admission interpolation reconstructed from the verified native ledger.

No new memory store, execution authority, model weights or native guard edits.
The manually specified duration-invariance assumption is deliberately narrow.
"""
import json
import math
import sqlite3

from .monitor import SelfModel, context, forecast, POLICY, digest
from .regulation import KnowledgeView
from .embodied_learning import choose


def family(observation, request):
    return context(observation, dict(request, duration_s='duration-family-v1'))


class DurationMemory:
    def __init__(self, model):
        if not isinstance(model, SelfModel):
            raise TypeError('verified SelfModel required')
        self.model = model

    def state(self):
        try:
            return self._state()
        except (KeyError, TypeError, IndexError, sqlite3.DatabaseError) as exc:
            raise ValueError('invalid verified native ledger') from exc

    def _state(self):
        # Verify and read in one SQLite snapshot, not an unverified export.
        with self.model.connection() as db:
            db.execute('BEGIN')
            verified = self.model._verify(db)
            groups = {}
            for intent, result in db.execute('SELECT intent,result FROM episodes ORDER BY rowid'):
                if result is None:
                    continue
                i, r = json.loads(intent), json.loads(result)
                if not r['learned']:
                    continue
                if not r['receipt']['owner']['physical_model_valid']:
                    raise ValueError('invalid physical effects cannot support transfer')
                key = family(i['before'], i['request'])
                g = groups.setdefault(key, dict(success=0, failure=0, durations=[]))
                g['success' if r['admitted'] else 'failure'] += 1
                g['durations'].append(i['request']['duration_s'])
        return dict(verified=verified, groups=groups)

    def predict(self, observation, request, *, pool=True):
        duration = request['duration_s']
        if (type(duration) not in (int, float) or not math.isfinite(duration)
                or not .1 <= duration <= 1.):
            raise ValueError('bounded finite duration required')
        s = self.state()
        if s['verified']['pending']:
            raise ValueError('unresolved native outcome blocks transfer')
        exact = forecast(s['verified']['counts'], context(observation, request))
        p = dict(exact, evidence='exact_context', duration_bounds=None,
                 memory_sha256=digest(s))
        if not pool or exact['samples'] >= POLICY['min_samples'] or request['requested'] != 'walk':
            return p
        g = s['groups'].get(family(observation, request))
        if not g:
            return dict(p, evidence='unseen_family')
        durations = sorted(set(g['durations']))
        low, high = durations[0], durations[-1]
        n = g['success'] + g['failure']
        if len(durations) < 2 or not low <= duration <= high:
            return dict(p, evidence='outside_supported_duration_hull')
        if n < POLICY['min_samples'] or (g['success'] and g['failure']):
            return dict(p, evidence='insufficient_or_conflicting_transfer_evidence')
        return dict(p, samples=n, successes=g['success'], failures=g['failure'],
                    probability=(g['success']+1)/(n+2),
                    evidence='bounded_duration_interpolation', duration_bounds=[low, high],
                    kind='pooled Beta(1,1) software admission mean; authored invariance assumption')

    def advise(self, observation, request, *, pool=True):
        # Existing bodily protection keeps precedence. This method cannot act.
        if request['requested'] != 'walk':
            raise ValueError('walk-candidate advisory only')
        s = self.state()['verified']
        base = choose(s, observation, request, arm='B', practice=False)
        prediction = self.predict(observation, request, pool=pool)
        report = SelfModel.inspect(KnowledgeView(s), observation, request)
        immutable_reasons = [x for x in report['reasons'] if x not in
                             ('insufficient_context_experience', 'low_observed_self_efficacy')]
        ready = (prediction['samples'] >= POLICY['min_samples'] and
                 prediction['probability'] >= POLICY['continue_threshold'])
        action = base['action']
        if not immutable_reasons:
            action = 'walk' if ready else 'observe'
        return dict(action=action, prediction=prediction, native_reasons=immutable_reasons,
                    authority='advisory_only_existing_native_cycle_required')
