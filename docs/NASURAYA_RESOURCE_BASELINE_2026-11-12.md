# Nasuraya performance baseline, 2026-11-12

## Why
A faster server does not necessarily make ChatGPT or remote model APIs faster.
Before paying for larger VPS hardware or enabling parallel agent execution,
measure separately: (1) local CPU and memory, (2) local Python + SQLite,
(3) network/API latency, and (4) actual task end-to-end time.

## What this branch provides
`tools/nasuraya_resource_probe.py` is a local, read-only Python 3.12+
resource and microbenchmark probe, with zero additional packages.
Run manually from a trusted checkout:

```powershell
python tools/nasuraya_resource_probe.py
```

The single JSON output reports OS family, architecture, Python version,
logical CPU count, approximate total/available physical RAM and median
wall-clock times for three fixed synthetic workloads (CPU SHA256, JSON
roundtrip, in-memory SQLite). No process list, host name, IP address,
personal file, token, password, disk content, or network call is involved.

This is a baseline probe, **not** a live server deployment and **not** a
measurement of actual model/inference/network latency. The script does not
detect GPU, alter configuration, spend money, start a service or touch data
other than in-memory synthetic SQLite rows.

## Safe follow-up, in order
1. Operator runs the probe once during a quiet server interval; record the
   JSON with timestamp in a non-public operator-approved location if desired.
2. Measure representative Nasuraya workloads (not the synthetic tasks)
   using per-stage timings: queue wait, GitHub polling, model/API wait,
   Python compute, simulation, SQLite commit, and serialization.
3. Compare before/after wall time, p50/p95, errors, RAM peak and CPU saturation.
   Repeat three times and keep the original safe baseline.
4. Tune concurrency only for independent tasks; enforce memory budget,
   bounded queue, deadlines, idempotency and rollback for writes.
5. Upgrade VPS CPU/RAM **only if** measured bottlenecks justify the cost.
   Consider GPU only if a specific local GPU-capable inference/graphics
   workload and compatible environment are demonstrated.

## Limitations
- The v2 Windows bridge reported remote Python 3.12 and job capability
  previously, but its existing permission boundary does not authorize
  arbitrary remote code execution or provisioning.
- The current VPS hardware is unknown until a trusted operator measures it.
- Windows Server 2012 R2 is past extended-security-update support as of
  October 2026; consider a supported host OS before expanding exposure.
- This branch must not auto-deploy or merge without explicit review.
