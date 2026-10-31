"""Stage-3 single-turn closed research loop: decide -> native probe -> replan.

One explicit invocation runs at most ONE allowlisted synthetic experiment.
It never schedules further work, modifies the model, or calls an API.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from . import engine, worker, goal_governor as governor

SCHEMA = 'nasuraya-stage3-one-experiment-cycle/1'
ALLOWED = frozenset({'rare_slow_breath'})
MAX_WALL_SECONDS = 130


def strict_int(value, expected, name):
    if type(value) is not int or value != expected:
        raise ValueError(name + ' is not verified')


def checked_proposal(workspace: Path, run_id: str):
    evidence = governor.verified_network(workspace, run_id)
    candidate = governor.strict_load(workspace / 'stage3-goal.json')
    actual = governor.propose(evidence)
    if candidate != actual or candidate.get('decision_sha256') != governor.digest(
            {k: v for k, v in candidate.items() if k != 'decision_sha256'}):
        raise ValueError('stage3 decision does not match verified native network receipts')
    return evidence, candidate


def pick_next(summary: dict):
    """Only a recommendation, not an actuator or an executed second experiment."""
    if not isinstance(summary, dict) or summary.get('validation_passed') is not True:
        raise ValueError('invalid experiment evidence')
    strict_int(summary.get('cases'), 24, 'case count')
    strict_int(summary.get('native_cycles'), 24, 'native cycle count')
    if summary.get('api_calls') != 0 or summary.get('physical_actuator_calls') != 0:
        raise ValueError('paid or physical actuator effect not permitted')
    if summary.get('learning_updates') != 0 or summary.get('weights_unchanged') is not True:
        raise ValueError('unexpected model update')
    rare = summary.get('slow_breath_events')
    if type(rare) is not int or not 0 <= rare <= 24:
        raise ValueError('rare-event count invalid')
    if summary.get('conclusion') != ('observed_taxonomy_limitation' if rare else 'no_slow_breath_in_challenge'):
        raise ValueError('rare-event conclusion inconsistent')
    for field in ('brier','pooled_brier'):
        value = summary.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2:
            raise ValueError('invalid Brier metric')
    if rare:
        if summary.get('exact_slow_breath_predictions') != 0 or summary.get('exact_slow_breath_recall') != 0:
            raise ValueError('four-category native forecast cannot claim exact rare recall')
        return dict(id='test_five_class_action_taxonomy',
            title='آزمایش پیش‌بینی پنج‌دسته‌ای با برچسب مستقل تنفس آهسته',
            reason='Native rare slow_breath occurred but the four-way classifier can only call it other.',
            proposal='Prepare a separate five-way forecaster and independent holdout; do not modify the native body.',
            criterion='No regression in overall Brier and independently measured slow_breath recall.',
            automatically_executed=False)
    if summary.get('exact_slow_breath_recall') is not None:
        raise ValueError('zero-event recall must be null, not zero')
    return dict(id='improve_rare_event_challenge',
        title='ساخت آزمون حساس‌تر برای مشاهدهٔ رخداد نادر تنفس آهسته',
        reason='No slow_breath event occurred in the new targeted native trials.',
        proposal='Freeze a broader, independently specified rare-event coverage protocol.',
        criterion='Observe genuine native rare outcomes with receipts before estimating rare-action recall.',
        automatically_executed=False)


def run(workspace: Path, run_id: str, output: Path, root: Path | None = None):
    workspace = Path(workspace).resolve()
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    output = Path(output).resolve()
    if not output.is_relative_to(workspace) or root.is_relative_to(workspace) or workspace.is_relative_to(root):
        raise ValueError('output must be outside source and inside the network workspace')
    if (workspace / 'STOP').exists():
        raise RuntimeError('stage3 stopped before claim')
    evidence, proposal = checked_proposal(workspace, run_id)
    chosen = proposal.get('chosen')
    if not isinstance(chosen, dict) or chosen.get('id') not in ALLOWED:
        raise ValueError('only the explicitly allowed rare-breath research probe can execute')
    training_file = workspace / run_id / 'self_model' / 'self_model' / 'training.json'
    if not training_file.is_file() or training_file.is_symlink():
        raise ValueError('verified native training file missing')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    # The exclusive output directory and claim survive a crash. No implicit restart.
    governor_path = root / 'nasuraya_agent_network' / 'stage3_cycle.py'
    claim = dict(schema=SCHEMA, run_id=run_id, decision_sha256=proposal['decision_sha256'],
                 network_report_sha256=evidence['report_sha256'],
                 stage3_implementation_sha256=sha256(governor_path.read_bytes()).hexdigest(),
                 begun_at=datetime.now(timezone.utc).isoformat(),
                 max_experiments=1, max_wall_seconds=MAX_WALL_SECONDS,
                 no_auto_retry=True, api_budget_usd=0, model_updates_allowed=False)
    (output/'claim.json').write_text(json.dumps(claim, sort_keys=True, indent=2)+'\n')
    start = time.monotonic()
    log = output / 'native-probe.log'
    with tempfile.TemporaryDirectory(prefix='native-source-', dir=output) as tmp:
        source = Path(tmp) / 'snapshot'
        source.mkdir()
        copied_hash = engine.copy_snapshot(root, source)
        if copied_hash != evidence['source_sha256']:
            raise ValueError('native source does not match previous five-worker network evaluation')
        env = {'PATH': os.defpath, 'HOME': str(output), 'TMPDIR': str(output),
               'PYTHONPATH': str(source), 'PYTHONDONTWRITEBYTECODE':'1',
               'PYTHONNOUSERSITE':'1', 'LANG':'C.UTF-8', 'LC_ALL':'C.UTF-8'}
        command = [sys.executable, '-I', str(Path(worker.__file__).resolve()), str(source),
                   '-m', 'examples.nasuraya_body_loop', 'rare-action-probe',
                   '--training-file', str(training_file), '--output-dir', str(output/'probe')]
        with log.open('xb') as stream:
            proc = subprocess.Popen(command, cwd=source, env=env, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
            interrupted = None
            try:
                while proc.poll() is None:
                    if (workspace / 'STOP').exists():
                        interrupted = 'stopped'; break
                    if time.monotonic() - start >= MAX_WALL_SECONDS:
                        interrupted = 'time_limit'; break
                    if log.stat().st_size > worker.MAX_LOG:
                        interrupted = 'log_limit'; break
                    time.sleep(.03)
            finally:
                worker.stop_group(proc)
    raw = log.read_bytes()
    if (interrupted is not None or proc.returncode != 0
            or b'NASURAYA_NETWORK_DENIED=1\n' not in raw):
        raise RuntimeError('bounded native experiment blocked or failed: '+
                           str(interrupted or proc.returncode))
    summary = governor.strict_load(output / 'probe' / 'summary.json')
    selected = pick_next(summary)
    result = dict(schema=SCHEMA, completed=True, run_id=run_id,
                  executed_goal_id=chosen['id'], decision_sha256=proposal['decision_sha256'],
                  network_report_sha256=evidence['report_sha256'],
                  fresh_native_cycles=summary['native_cycles'],
                  probe_summary_sha256=governor.digest(summary),
                  native_source_sha256=copied_hash,
                  native_log_sha256=sha256(raw).hexdigest(),
                  observed_slow_breath=summary['slow_breath_events'],
                  experiment_conclusion=summary['conclusion'],
                  next_goal=selected,
                  next_goal_execution=False, automatic_model_updates=False,
                  model_api_calls=0, physical_actuator_calls=0,
                  scope='finite exploratory synthetic native experiment and one evidence-based replan; '
                        'not independent-world validation or phenomenological consciousness')
    result['result_sha256']=governor.digest(result)
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,
                                                indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (output/'REPORT_FA.md').write_text(
        '# چرخهٔ سوم ناسورایا: تصمیم، آزمایش، بازبینی\n\n'
        +f"هدف اجراشده: {chosen['title']}\n\n"
        +f"چرخه‌های واقعی بدن نرم‌افزاری: {summary['native_cycles']}\n\n"
        +f"موارد تنفس آهستهٔ واقعی در آزمایش: {summary['slow_breath_events']}\n\n"
        +f"Brier مدل زمینه‌مند: {summary['brier']:.6f}؛ مدل تجمیعی: {summary['pooled_brier']:.6f}\n\n"
        +f"نتیجه: {summary['conclusion']}\n\n"
        +f"هدف پیشنهادی بعدی: {selected['title']}\n\n"
        +'هدف بعدی اجرا نشده. نه ادغام در main انجام شده و نه پول API مصرف شده است.\n'
        +'شرایط پژوهش مصنوعی و هدفمند بودند؛ این آزمایش اثبات خودآگاهی نیست.\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description='One verified offline experiment, then a new unexecuted proposal')
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(args.workspace,args.run_id,args.output)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))


if __name__=='__main__':
    main()
