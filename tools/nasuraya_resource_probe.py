"""Bounded, local-only Nasuraya server resource + latency probe (Python 3.12+).

No network calls, credentials, identifying host details, paths, process names,
or network addresses are read or printed. Nothing is installed or changed.
"""
import ctypes
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import time


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
        ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]


def memory_gib():
    if os.name == 'nt':
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return [round(status.ullTotalPhys / 2**30, 2),
                    round(status.ullAvailPhys / 2**30, 2)]
    elif os.name == 'posix':
        try:
            data = {}
            with open('/proc/meminfo', 'r', encoding='ascii') as handle:
                for line in handle:
                    k, _, v = line.partition(':')
                    if k in ('MemTotal', 'MemAvailable'):
                        data[k] = int(v.strip().split()[0])
            if len(data) == 2:
                return [round(data['MemTotal'] / 2**20, 2),
                        round(data['MemAvailable'] / 2**20, 2)]
        except (OSError, ValueError, IndexError):
            pass
    return None


def benchmark(fn, repeats=3):
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(timings), 2)


def cpu_task():
    value = b'nasuraya-performance-baseline' * 1024
    for _ in range(12000):
        value = hashlib.sha256(value).digest() + value[:1024]
    return value


def json_task():
    payload = [{'i': i, 'state': 'synthetic', 'value': i % 7} for i in range(800)]
    for _ in range(20):
        payload = json.loads(json.dumps(payload, separators=(',', ':')))
    return payload


def sqlite_task():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE t (i INTEGER PRIMARY KEY, v TEXT)')
        db.executemany('INSERT INTO t (i,v) VALUES (?,?)',
                       ((i, 'synthetic') for i in range(5000)))
        return db.execute('SELECT COUNT(*) FROM t').fetchone()[0]


def report():
    return {
        'schema': 'nasuraya-resource-baseline/1',
        'scope': 'read_only_local_synthetic',
        'os_family': platform.system(),
        'architecture': platform.machine(),
        'python': platform.python_version(),
        'logical_cpus': os.cpu_count(),
        'memory_gib_total_available': memory_gib(),
        'gpu': 'not_measured',
        'median_ms_3_runs': {
            'cpu_sha256': benchmark(cpu_task),
            'json_roundtrip': benchmark(json_task),
            'sqlite_in_memory_5000_rows': benchmark(sqlite_task),
        },
        'limitations': 'No measurement of actual Nasuraya, AI model, network or API latency; not a hardware upgrade',
    }


if __name__ == '__main__':
    print(json.dumps(report(), ensure_ascii=False, sort_keys=True))
