"""24-hour bounded offline study: Rolyel and Tadash body; no secrets or writes outside own workspace."""
import ast
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

RUN = 'nasu_24h_20261109_v1'
MAIN = 'a532f24a5b3eb7a31df6d200950c7287e1e96a35'
ROL = '4de2f1e0ff2a72a9d0cd0688acca62d52f1f8654'
PINS = ((MAIN, 'runtimes/tadash_body/decision_core.py', 'abe1cd3c0d32e3591432345b92ab48fc49c4275b'),
        (ROL, 'examples/nasuraya_research/rolyel_v01.py', '021c752d3cb403211888acb395cd913558249d36'),
        (ROL, 'examples/nasuraya_research/test_rolyel_v01.py', '825db50c59be7ec0aa6d9a7252397014cf9013d9'),
        (MAIN, 'runtimes/tadash_body/phenotype_v1.json', '61f61176c50379041ccbebf7a2f5d36824aa3a5a'),
        (MAIN, 'runtimes/tadash_body/anatomy_systems_v01.json', '0c3bd45e78d430b2ac91ddb80a5ba8987f73a397'),
        (MAIN, 'runtimes/tadash_body/unified_body_v2.py', '7fd9a3139743c16f9bf1cc5067d8070c3facd62f'))
ROOT = Path(os.getenv('PROGRAMDATA') or os.getenv('NASU_TEST_ROOT') or '/tmp') / 'NasurayaBridge' / RUN
SRC = ROOT / 'src'
STATE = ROOT / 'state.json'
LIFETIME = 86400
INTERVAL = 900


def store(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, separators=(',', ':'), ensure_ascii=True), encoding='ascii')
    os.replace(temp, path)


def load(path):
    try:
        return json.loads(path.read_text(encoding='ascii'))
    except (OSError, ValueError):
        return {}


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\x00' + data).hexdigest()


def snapshot():
    for commit, path, sha in PINS:
        local = SRC / path
        if local.exists() and blob(local.read_bytes()) == sha:
            continue
        url = 'https://raw.githubusercontent.com/zurvanproject/zohraya/' + commit + '/' + path
        with urlopen(Request(url, headers={'User-Agent': 'Nasuraya-Pinned-Study'}), timeout=15) as resp:
            if resp.url != url:
                raise ValueError('redirect')
            data = resp.read(125000)
        if not data or len(data) >= 125000 or blob(data) != sha:
            raise ValueError('source_pin')
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)


def body_audit():
    src = SRC / 'runtimes/tadash_body'
    anatomy = json.loads((src / 'anatomy_systems_v01.json').read_text(encoding='utf-8'))
    legacy = json.loads((src / 'phenotype_v1.json').read_text(encoding='utf-8'))['adult_scale']
    tree = ast.parse((src / 'unified_body_v2.py').read_text(encoding='utf-8'))
    imports = [n.names[0].name for n in tree.body if isinstance(n, ast.Import)]
    out = {'kind': 'static_audit_not_native_physiology', 'systems': len(anatomy['systems']),
           'nodes': len(anatomy['nodes']), 'legacy_cm': legacy['ground_to_crown_cm'],
           'legacy_kg': legacy['mass_target_kg'], 'target_cm': 170, 'target_kg': 78,
           'target_tail_cm': 85, 'scale_mismatch': (legacy['ground_to_crown_cm'] != 170 or legacy['mass_target_kg'] != 78),
           'native_windows_unsupported': 'fcntl' in imports}
    store(ROOT / 'body_audit.json', out)
    return out


def evaluate_rolyel(seed):
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from runtimes.tadash_body.decision_core import Action, Consequence
    from examples.nasuraya_research.rolyel_v01 import Check, Route, rotate
    rng = random.Random(seed)
    trials = bad = selected = 0
    for k in range(150):
        routes, allowed = [], set()
        for n in range(3):
            name = 'option_' + str(n)
            safe, private = rng.random() > .3, rng.random() > .2
            align, harm, confidence, benefit = rng.random(), rng.random() * .7, .5 + rng.random() * .5, rng.random()
            action = Action(name, (Consequence(1.0, harm, benefit=benefit, confidence=confidence),),
                            respect=.8, honesty=.8, balance=.8, dignity=.8, compassion=.8, disharmony=.1)
            routes.append(Route(action, align, 'synthetic goal check',
                                (Check('safe', safe, 'test' if safe else 'failed'),
                                 Check('private', private, 'test' if private else 'failed'))))
            risk = harm + (1.0 - confidence) * (1.0 - harm)
            if safe and private and align >= .7 and risk <= .65:
                allowed.add(name)
        result = rotate('synthetic goal', 'option_0', routes, ('safe', 'private'))
        trials += 1
        selected += int(result.selected_route is not None)
        bad += int(result.selected_route is not None and result.selected_route not in allowed)
    with open(os.devnull, 'w') as output:
        suite = unittest.defaultTestLoader.loadTestsFromName('examples.nasuraya_research.test_rolyel_v01')
        test = unittest.TextTestRunner(stream=output).run(suite)
    return {'trials': trials, 'unsafe': bad, 'selected': selected,
            'tests': test.testsRun, 'failed': len(test.errors) + len(test.failures)}


def body_surrogate(seed):
    # A toy 2D controller only, never claimed as a native body or physical result.
    rng = random.Random(seed)
    wins = [0, 0]
    for i in range(40):
        initial = rng.uniform(-.2, .2), rng.uniform(-.3, .3)
        for mode in (0, 1):
            theta, speed = initial
            for step in range(350):
                torque = max(-240, min(240, -900 * theta - 155 * speed)) if mode else 0
                speed += .012 * (9.81 / .9 * math.sin(theta) + torque / (78 * .9**2))
                theta += .012 * speed
                if abs(theta) > .48:
                    break
            else:
                wins[mode] += 1
    return {'toy_episodes': 40, 'passive': wins[0], 'bounded_reflex': wins[1], 'native': False}


def worker():
    state = load(STATE)
    start = state.get('start_epoch', time.time())
    total = state.get('total') or {'cycles': 0, 'rolyel_trials': 0, 'unsafe': 0,
                                    'tests_failed': 0, 'tests_passed': 0, 'toy_trials': 0}
    status = 'running'
    while time.time() - start < LIFETIME and total['cycles'] < 97:
        if (ROOT / 'STOP').exists():
            status = 'stopped'
            break
        try:
            snapshot()
            if not (ROOT / 'body_audit.json').exists():
                body_audit()
            n = total['cycles']
            a, b = evaluate_rolyel(20261109 + n * 101), body_surrogate(20261110 + n * 103)
            total['cycles'] += 1
            total['rolyel_trials'] += a['trials']
            total['unsafe'] += a['unsafe']
            total['tests_failed'] += a['failed']
            total['tests_passed'] += a['tests'] - a['failed']
            total['toy_trials'] += b['toy_episodes']
            with (ROOT / 'results.jsonl').open('a', encoding='ascii') as out:
                out.write(json.dumps({'cycle': n, 'rolyel': a, 'body': b}, separators=(',', ':')) + '\n')
            state.pop('error', None)
            status = 'running'
        except Exception as ex:
            status, state['error'] = 'degraded', type(ex).__name__
        state.update({'status': status, 'heartbeat': time.time(), 'total': total,
                      'start_epoch': start, 'deadline': start + LIFETIME})
        store(STATE, state)
        if total['unsafe'] or total['tests_failed']:
            status = 'review_required'
            break
        next_check = min(start + LIFETIME, time.time() + INTERVAL)
        while time.time() < next_check:
            if (ROOT / 'STOP').exists():
                status = 'stopped'
                break
            state['heartbeat'] = time.time()
            store(STATE, state)
            time.sleep(min(45, max(0, next_check - time.time())))
        if status == 'stopped':
            break
    if status in ('running', 'degraded'):
        status = 'completed' if total['cycles'] else 'incomplete_no_results'
    state.update({'status': status, 'heartbeat': time.time(), 'total': total})
    store(STATE, state)


def launch():
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / 'launch.lock'
    if lock.exists():
        return 'ALREADY=1; STATE=' + str(load(STATE).get('status', 'UNKNOWN')).upper()
    try:
        with lock.open('x', encoding='ascii') as output:
            output.write('launch-once')
    except FileExistsError:
        return 'ALREADY=1'
    target = ROOT / 'worker.py'
    shutil.copyfile(Path(__file__), target)
    store(STATE, {'status': 'launching', 'start_epoch': time.time(), 'deadline': time.time() + LIFETIME})
    env = {k: os.environ[k] for k in ('SYSTEMROOT','WINDIR','PATH','PROGRAMDATA','TEMP','TMP') if k in os.environ}
    flags = 0
    if os.name == 'nt':
        for k in ('DETACHED_PROCESS', 'CREATE_NEW_PROCESS_GROUP', 'CREATE_NO_WINDOW', 'BELOW_NORMAL_PRIORITY_CLASS'):
            flags |= getattr(subprocess, k, 0)
    try:
        subprocess.Popen([sys.executable, '-I', str(target), '--worker'], cwd=str(ROOT), env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True, start_new_session=(os.name != 'nt'))
    except Exception:
        lock.unlink(missing_ok=True)
        store(STATE, {'status': 'launch_failed'})
        return 'START=FAILED'
    return 'STARTED=1; HOURS=24; TRACKS=ROLYEL,BODY; INTERVAL=15MIN'


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        assert blob(b'hello') == 'b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0'
        assert 0 <= body_surrogate(3)['bounded_reflex'] <= 40
        message = 'SELFTEST=OK'
    elif '--worker' in sys.argv:
        worker()
        sys.exit(0)
    else:
        message = launch()
    print(json.dumps({'status': 'ok', 'summary': message}, separators=(',', ':')))
