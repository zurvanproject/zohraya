#!/usr/bin/env python3
"""Nasuraya Bridge v2 fixed, bounded, unprivileged jobs. No general shell.

Only one of 'audit', 'inventory', 'sources' is accepted. Paths and domains are
constants; no arbitrary URLs, file paths, or commands are accepted from GitHub.
"""
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
import secrets
import urllib.parse

REPO = Path('/var/lib/nasuraya/zohraya')
ATLAS = REPO / 'runtimes/tadash_body/anatomy_systems_v01.json'
MISSION = REPO / 'missions/fullbody_online_20261115.json'
PINS = {
    ATLAS: 'f0a8f47de3b23d15f257b56767308b82cb4f41cd765232599e9343631397b64b',
    MISSION: '28fcee33c5dd2205f787664f04920086693d8ab6931efd13cf9a5c6da1d86bef',
}
TARGET = {'systems': 12, 'nodes': 97, 'routes': 31}
# Exactly four fixed documentation pages; no crawler or asset download.
SOURCES = {
    'nlm_vhp': 'https://www.nlm.nih.gov/research/visible/visible_human.html',
    'nih_3d': 'https://3d.nih.gov/terms',
    'opensim': 'https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53089741',
    'mujoco': 'https://mujoco.readthedocs.io/en/stable/',
}
MAX_SAMPLE = 16384
GETENT_TIMEOUT = 4
SOCKET_TIMEOUT = 5
HOST_DEADLINE_SECONDS = 12
REPORTS = Path('/var/lib/nasuraya/bridge-v2-reports')


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ensure_user():
    if os.geteuid() == 0:
        raise RuntimeError('ROOT_NOT_ALLOWED')


def checked_file(path, expected):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('PIN_FILE_MISSING_OR_SYMLINK')
    if path.stat().st_size > 2_000_000:
        raise RuntimeError('PIN_FILE_TOO_LARGE')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError('PIN_MISMATCH')
    return data


def inventory():
    contents = {str(path): checked_file(path, sha) for path, sha in PINS.items()}
    atlas = json.loads(contents[str(ATLAS)])
    mission = json.loads(contents[str(MISSION)])
    observed = {key: len(atlas.get(key, [])) for key in TARGET}
    if observed != TARGET:
        raise RuntimeError('ANATOMY_COUNTS_MISMATCH')
    phenotype = atlas.get('baseline_contract', {}).get('phenotype_contract', {})
    morph = mission.get('morphology_constraints', {})
    if (phenotype.get('horns'), phenotype.get('toes_per_foot'), phenotype.get('digitigrade')) != (2, 3, True):
        raise RuntimeError('PHENOTYPE_LOCK_MISMATCH')
    if (morph.get('target_mass_kg'), morph.get('ground_to_crown_cm'), morph.get('tail_centerline_cm')) != (78, 170, 85):
        raise RuntimeError('MISSION_LOCK_MISMATCH')
    return {'state': 'PINNED_INVENTORY_OK', 'counts': observed, 'unverified_requirements': 97 * 14,
            'body_validated': False, 'body_modified': False, 'memory_modified': False}


def audit():
    ensure_user()
    stat = os.statvfs('/var/lib/nasuraya')
    free = int(stat.f_bavail * stat.f_frsize)
    return {'state': 'AUDIT_OK', 'utc': utc(), 'loadavg_1m': round(os.getloadavg()[0], 3),
            'free_bytes': free, 'root': False, 'body_modified': False,
            'memory_modified': False, 'service_modified': False}


def resolve_public_ips(host):
    # getent is capped by a process timeout. No network-related command text comes from a user.
    proc = subprocess.run(['/usr/bin/getent', 'ahosts', host], capture_output=True, text=True,
                          timeout=GETENT_TIMEOUT, check=False)
    if proc.returncode != 0:
        raise RuntimeError('DNS_RESOLUTION_FAILED')
    candidates = sorted({line.split()[0] for line in proc.stdout.splitlines() if line.split()})
    if not candidates:
        raise RuntimeError('DNS_EMPTY')
    ips = []
    for candidate in candidates:
        ip = ipaddress.ip_address(candidate)
        if not ip.is_global:
            raise RuntimeError('DNS_NONPUBLIC_ADDRESS_BLOCKED')
        ips.append(str(ip))
    return ips


def probe_one(name, url):
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
    record = {'id': name, 'url': url, 'checked_utc': utc(), 'dns': 'NOT_CHECKED',
              'tls': 'NOT_CHECKED', 'https': 'NOT_CHECKED', 'anatomy_measured': False,
              'asset_license_verified': False}
    try:
        ips = resolve_public_ips(parsed.hostname)
        record['dns'] = 'PUBLIC_OK'
        record['resolved_ip_count'] = len(ips)
    except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as exc:
        record['dns'] = 'FAILED'
        record['error_type'] = type(exc).__name__
        return record
    try:
        deadline = time.monotonic() + HOST_DEADLINE_SECONDS
        # Connect to the checked public IP, not a newly resolved hostname.
        with socket.create_connection((ips[0], 443), timeout=SOCKET_TIMEOUT) as sock:
            sock.settimeout(min(SOCKET_TIMEOUT, max(0.1, deadline - time.monotonic())))
            with ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname) as tls:
                tls.settimeout(min(SOCKET_TIMEOUT, max(0.1, deadline - time.monotonic())))
                cert = tls.getpeercert(binary_form=True)
                record['tls'] = 'VERIFIED'
                record['peer_cert_sha256'] = hashlib.sha256(cert).hexdigest()
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
                request = ('GET ' + path + ' HTTP/1.1\r\nHost: ' + parsed.hostname +
                           '\r\nUser-Agent: Zohraya-BridgeV2-SourceAudit/1\r\n'
                           'Accept: text/html\r\nAccept-Encoding: identity\r\n'
                           'Connection: close\r\n\r\n').encode('ascii')
                tls.sendall(request)
                received = bytearray()
                # Header is capped; sample cannot exceed fixed size. No redirect follow.
                while b'\r\n\r\n' not in received and len(received) <= 8192:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('HOST_DEADLINE_EXCEEDED')
                    tls.settimeout(min(SOCKET_TIMEOUT, max(0.1, deadline - time.monotonic())))
                    chunk = tls.recv(2048)
                    if not chunk:
                        break
                    received.extend(chunk)
                if b'\r\n\r\n' not in received or len(received) > 8192 + 2048:
                    raise RuntimeError('HTTP_HEADERS_INVALID_OR_TOO_LARGE')
                headers, body = bytes(received).split(b'\r\n\r\n', 1)
                line = headers.split(b'\r\n', 1)[0]
                parts = line.split()
                if len(parts) < 2 or not parts[0].startswith(b'HTTP/'):
                    raise RuntimeError('HTTP_STATUS_INVALID')
                status = int(parts[1])
                record['http_status'] = status
                while len(body) < MAX_SAMPLE:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('HOST_DEADLINE_EXCEEDED')
                    tls.settimeout(min(SOCKET_TIMEOUT, max(0.1, deadline - time.monotonic())))
                    chunk = tls.recv(min(2048, MAX_SAMPLE - len(body)))
                    if not chunk:
                        break
                    body += chunk
                sample = body[:MAX_SAMPLE]
                record['https'] = 'REACHABLE' if 200 <= status < 300 else 'HTTP_ERROR_OR_REDIRECT'
                record['sample_bytes'] = len(sample)
                record['raw_sample_sha256'] = hashlib.sha256(sample).hexdigest()
                record['hash_scope'] = 'limited_raw_http_body_sample_not_full_dataset'
    except (OSError, ssl.SSLError, RuntimeError, ValueError) as exc:
        if record['tls'] != 'VERIFIED':
            record['tls'] = 'FAILED'
        record['https'] = 'FAILED'
        record['error_type'] = type(exc).__name__
    return record


def sources():
    ensure_user()
    records = [probe_one(name, url) for name, url in SOURCES.items()]
    os.umask(0o077)
    if REPORTS.is_symlink():
        raise RuntimeError('REPORTS_SYMLINK_BLOCKED')
    REPORTS.mkdir(mode=0o700, parents=False, exist_ok=True)
    if REPORTS.stat().st_uid != os.geteuid():
        raise RuntimeError('REPORTS_OWNERSHIP_MISMATCH')
    report = {'state': 'SOURCE_AUDIT_COMPLETE', 'utc': utc(), 'sources': records,
              'body_modified': False, 'memory_modified': False,
              'note': 'Only bounded documentation samples; no anatomy, physics or license validation.'}
    raw = (json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    name = 'sources-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4) + '.json'
    path = REPORTS / name
    with path.open('xb') as f:
        f.write(raw)
    # Keep the GitHub public comment short; full evidence remains on Ubuntu.
    summary = [{'id': r['id'], 'dns': r['dns'], 'tls': r['tls'], 'https': r['https'],
                'http': r.get('http_status'), 'error': r.get('error_type')}
               for r in records]
    return {'state': 'SOURCE_AUDIT_COMPLETE', 'utc': report['utc'],
            'sources': summary, 'report_path': str(path),
            'report_sha256': hashlib.sha256(raw).hexdigest(),
            'body_modified': False, 'memory_modified': False}


def main(args):
    if len(args) != 1 or args[0] not in ('audit', 'inventory', 'sources'):
        raise RuntimeError('UNSUPPORTED_FIXED_ACTION')
    action = args[0]
    ensure_user()
    if action == 'audit':
        result = audit()
    elif action == 'inventory':
        result = inventory()
    else:
        result = sources()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception as exc:
        print('BRIDGE_V2_FAILED;reason=' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)