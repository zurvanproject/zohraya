# Read-only interoceptive SelfModel adapter

`SelfModel` **does not** create a second mutable body, memory ledger, or a simulated
`integrity` reservoir. It projects the existing native `audit_self_model.assess`
output into concise telemetry and a bounded heuristic drive score. The saved
`UnifiedBody` checkpoint remains the source of truth for physical simulation
and persistence. In particular `integrity=None` means **not observed**, not zero.

```python
# Run from repo root with PYTHONPATH=runtimes/tadash_body
from audit_self_model import assess
from zohraya.self_model import SelfModel

# `body` is an already-restored UnifiedBody, not freshly invented state.
report = SelfModel(agent_id="ZOHRAYA-CORE-01").get_telemetry(assess(body))
```

The output is intentionally read-only: status and `optional_motion_permitted`
are advice to callers, **not** an authorization to bypass the upper controller
or perform motion. Stale evidence is reported explicitly. The reported EMA
recomputes over up to 16 saved error samples and is **not** a persisted global
EMA. All drives are uncalibrated engineering indices, not biological drives,
consciousness evidence, or a subjective experience measurement.

Run offline tests:

```sh
python -m unittest discover -s zohraya/tests -v
```

Hourly Gemini work is a **separate, credentials-gated infrastructure task**.
These tests run only when changes are proposed or manually dispatched; no API
calls or background jobs are implied by this module.
