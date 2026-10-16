"""Opt-in local DecisionCore -> Sentinel -> ReflectionCycle experience adapter.

Trusted code/interpreter/configuration must precede startup. Sequential pilot;
not an OS sandbox, live model API, or global agent-tool interception.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

from visual_status import check_sources, observe, read_file, parse_json, render

NATIVE = Path(__file__).resolve().parents[2] / 'runtimes/tadash_body'
IDENTIFIER = re.compile(r'[a-zA-Z0-9_.:-]{1,64}\Z')
MAX_CYCLES = 32


def modules():
    # Called only after the caller-configured deployment manifest is checked.
    sys.path.insert(0, str(NATIVE))
    from reflection_cycle import ReflectionCycle, InterruptedExecution
    from sentinel import Sentinel
    from time_mining import validate_task, digest
    return ReflectionCycle, InterruptedExecution, Sentinel, validate_task, digest


def trusted(root, manifest, expected):
    try:
        return bool(Path(root).resolve() == NATIVE.parents[1].resolve()
                    and re.fullmatch(r'[0-9a-f]{64}', expected) and check_sources(root, manifest, expected))
    except Exception:
        return False


def initialize(root, manifest, expected, directory):
    """Explicit fresh initialization only; never called as a run fallback."""
    if not trusted(root, manifest, expected):
        raise ValueError('deployment integrity')
    ReflectionCycle, _, Sentinel, _, _ = modules()
    directory = Path(directory)
    directory.mkdir(parents=False, exist_ok=False)
    guard = Sentinel(root, manifest, expected, directory / 'cache', directory / 'alerts.sqlite')
    guard.close()
    with ReflectionCycle(directory / 'experience.sqlite'):
        pass


class Meter:
    def __init__(self, engine):
        self.engine = engine
        self.calls = 0
        self.ticks = 0
        self.receipt_sha256 = None

    def path(self, task):
        return self.engine.path(task)

    def execute(self, *args, **kwargs):
        self.calls += 1
        self.ticks = None  # An interrupted tool may have effects; never invent zero.
        self.receipt_sha256 = None
        result = self.engine.execute(*args, **kwargs)
        self.ticks = result['actual_ticks']
        self.receipt_sha256 = result['receipt']['sha256']
        return result


class GuardedCycle:
    def __init__(self, root, manifest, expected, directory):
        self.root = Path(root)
        self.manifest = Path(manifest)
        self.expected = expected
        self.directory = Path(directory)
        self.guard = self.engine = self.meter = None
        self.startup_error = None
        if not trusted(root, manifest, expected):
            self.startup_error = 'deployment_integrity'
            return
        try:
            # Existing stores are mandatory. No implicit replacement of a lost
            # audit/experience DB. Concurrent path replacement is out of scope.
            for name in ('alerts.sqlite', 'experience.sqlite'):
                read_file(self.directory / name, 16 * 1024 * 1024)
            cache = self.directory / 'cache'
            if not cache.is_dir() or cache.is_symlink():
                raise ValueError('existing cache required')
            ReflectionCycle, self.InterruptedExecution, Sentinel, self.validate_task, self.digest = modules()
            self.engine = ReflectionCycle(self.directory / 'experience.sqlite')
            self.guard = Sentinel(root, manifest, expected, cache, self.directory / 'alerts.sqlite')
            self.meter = Meter(self.guard.engine)
            self.guard.engine = self.meter
        except Exception:
            self.startup_error = 'store_unavailable'
            self.close()

    def close(self):
        for obj in (self.guard, self.engine):
            if obj is not None:
                obj.close()
        self.guard = self.engine = None

    def snapshot(self, status=None):
        snapshot = observe(self.root, self.manifest, self.expected, self.directory / 'alerts.sqlite')
        if status in {'store_unavailable', 'audit_unavailable', 'sentinel_unavailable',
                      'experience_unavailable', 'unresolved_execution', 'cycle_capacity'}:
            # A readable journal alone cannot make a failed admission/completion
            # audit look healthy. Preserve any already observed stop/latch.
            snapshot['checks']['audit'] = 'fail' if snapshot['checks']['audit'] == 'fail' else 'unknown'
            snapshot['audit'] = dict(latched=snapshot['audit']['latched'], events=None,
                                     warnings=None, capacity_stop=snapshot['audit']['capacity_stop'], recent=[])
            snapshot['reasons'].append('audit_unavailable')
            if snapshot['state'] != 'blocked':
                snapshot['state'] = 'unknown'
        return snapshot

    def result(self, status, **fields):
        return dict(status=status, current_tool_calls=self.meter.calls if self.meter else 0,
                    current_native_ticks=self.meter.ticks if self.meter else 0,
                    snapshot=self.snapshot(status), **fields)

    def request(self, envelope, at_utc=None):
        # This closed external contract cannot change scores, source locators,
        # callbacks, paths, available tools, or expected outcomes.
        if not isinstance(envelope, dict) or set(envelope) != {'id', 'goal', 'task'}:
            raise ValueError('request contract')
        if not isinstance(envelope['id'], str) or not IDENTIFIER.fullmatch(envelope['id']):
            raise ValueError('bounded id')
        if envelope['goal'] not in ('result', 'reproduce'):
            raise ValueError('goal contract')
        task = self.validate_task(envelope['task'])
        candidates = []
        for action in ('get', 'reproduce'):
            fresh_required = envelope['goal'] == 'reproduce'
            candidates.append(dict(id=action,
                score=dict(respect=1., honesty=1., balance=1., dignity=1., compassion=1.,
                    disharmony=0., evidence_confidence=1.,
                    consequences=[dict(probability=1., harm=0., benefit=1.,
                        cost=.1 if action == 'get' else .3, confidence=1.)]),
                claims=[], requires_evidence=[], requires_tools=['guarded_evidence'],
                violates_goals=['fresh_execution'] if fresh_required and action == 'get' else [],
                expected_outcome=dict(status='completed')))
        # Preserve the original decision clock on an identical completed replay.
        return dict(id=envelope['id'], context='guarded-native-evidence-v03',
            topic=self.digest(task), goal=envelope['goal'],
            goals=[dict(id='fresh_execution', required=envelope['goal'] == 'reproduce')],
            at_utc=at_utc or datetime.now(timezone.utc).isoformat(), evidence=[],
            tools={'guarded_evidence': 'ok'}, actions=candidates,
            execution=dict(task=task, deployment_manifest_sha256=self.expected))

    def run(self, envelope):
        if self.meter:
            self.meter.calls = self.meter.ticks = 0
            self.meter.receipt_sha256 = None
        if self.startup_error:
            return self.result(self.startup_error)
        if not trusted(self.root, self.manifest, self.expected):
            return self.result('deployment_integrity')
        # If either store disappears after startup, do not use a surviving open
        # connection as permission to keep running into an unlinked database.
        try:
            for name in ('alerts.sqlite', 'experience.sqlite'):
                read_file(self.directory / name, 16 * 1024 * 1024)
            records = self.engine.export()['decisions']
            if any(r['status'] == 'running' or (r['actual_outcome'] or {}).get('status') in
                   {'audit_unavailable', 'sentinel_unavailable'} for r in records):
                return self.result('unresolved_execution')
            input_id = envelope.get('id') if isinstance(envelope, dict) else None
            if len(records) >= MAX_CYCLES and not any(r['id'] == input_id for r in records):
                return self.result('cycle_capacity')
        except Exception:
            return self.result('store_unavailable')
        try:
            # Validate first, so untrusted IDs never become log text/locators.
            request = self.request(envelope)
            old = self.engine.get(request['id'])
            if old:
                request['at_utc'] = old['request']['at_utc']
        except Exception:
            # Persist only a fixed invalid-request marker, never the payload.
            try:
                self.guard.execute(dict(kind='invalid', task={}))
            except Exception:
                return self.result('audit_unavailable')
            return self.result('invalid_request')

        def executor(candidate):
            try:
                outcome = self.guard.execute(dict(kind=candidate['id'], task=request['execution']['task']))
                if not outcome['allowed']:
                    return dict(status='denied', alarm_code=outcome['alarm']['code'])
                value = outcome['result']
                return dict(status='completed', mode=value['mode'], actual_ticks=value['actual_ticks'],
                    receipt_sha256=value['receipt']['sha256'], receipt_valid=value['receipt']['payload']['result']['valid'])
            except (sqlite3.DatabaseError, OSError):
                return dict(status='audit_unavailable', tool_calls=self.meter.calls,
                            actual_ticks=self.meter.ticks, receipt_sha256=self.meter.receipt_sha256)
            except Exception:
                return dict(status='sentinel_unavailable', tool_calls=self.meter.calls,
                            actual_ticks=self.meter.ticks, receipt_sha256=self.meter.receipt_sha256)

        witness = dict(id='guard-return:' + request['id'], kind='observed',
            source_ref='runtime://Sentinel.execute', locator='cycle/' + request['id'],
            source_sha256=hashlib.sha256(read_file(Path(__file__).with_name('sentinel.py'), 128 * 1024)).hexdigest(),
            claim=dict(key='verification', value='actual guarded callback return or caught failure'))
        try:
            record = self.engine.execute(request, executor, verified=True, evidence=[witness],
                reason='actual local guarded callback; no external producer authentication')
        except self.InterruptedExecution:
            return self.result('unresolved_execution')
        except (sqlite3.DatabaseError, OSError):
            return self.result('experience_unavailable')
        except ValueError:
            return self.result('conflicting_request')
        if record['selected_action'] is None:
            return self.result('abstained', record_id=record['id'])
        return self.result(record['actual_outcome']['status'], record_id=record['id'],
            selected_action=record['selected_action'], completed_replay=bool(old and old['status'] == 'complete'),
            outcome=deepcopy(record['actual_outcome']), feedback=deepcopy(record['feedback']),
            recalled_feedback_ids=record['recalled_feedback_ids'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--directory', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--initialize', action='store_true')
    group.add_argument('--request')
    parser.add_argument('--output', help='fresh output directory for result and visual snapshot')
    args = parser.parse_args()
    if args.initialize:
        initialize(args.repo_root, args.manifest, args.expected_manifest_sha256, args.directory)
        print(json.dumps(dict(status='initialized')))
        return 0
    if not args.output:
        parser.error('--output required for an execution')
    output = Path(args.output)
    # Reserve evidence storage before admitting any tool effect.
    output.mkdir(parents=False, exist_ok=False)
    try:
        request = parse_json(read_file(args.request, 64 * 1024))
    except Exception:
        request = None
    cycle = GuardedCycle(args.repo_root, args.manifest, args.expected_manifest_sha256, args.directory)
    try:
        result = cycle.run(request)
    finally:
        cycle.close()
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'index.html').write_text(render(result['snapshot']))
    print(json.dumps({k: result[k] for k in ('status', 'current_tool_calls', 'current_native_ticks')}))
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
