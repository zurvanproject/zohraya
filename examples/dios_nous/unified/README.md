# Unified DIOS research interface

This package composes existing source-pinned components in an executable offline research episode. It does not connect the desktop ChatGPT shortcuts to a local model, give access to language-model weights, authenticate remote observations, or execute actions.

From the repository root (Python3.11+, standard library):

```sh
python -m examples.dios_nous unified-demo --output-dir /tmp/dios-unified-example
python -m examples.dios_nous unified-catalogue
python -m unittest discover -s examples/dios_nous -v
python -m examples.dios_nous.unified.evaluate --split dev --output /tmp/dios-unified-dev.json
python -m examples.dios_nous.unified.evaluate --split holdout --output /tmp/dios-unified-regression.json
```

Use a new empty directory/output filename. On Windows use an ordinary writable Windows path. The demo's explicit default evaluation clock is2026-11-12T08:00:00Z, so frozen public reports do not appear live. Set `--now-utc` to another aware UTC timestamp when inspecting their age. The clock is caller supplied, not an attested time source.

`snapshot.json` contains actual synthetic cognitive results, pinned atlas output, provenance, units, parameter catalogues, frozen public reports, missing data and workload advice. The demo includes a goal-stop test, so its final goal is null and workload state HALTED. The earlier revised goal remains in historical results. Read the saved JSON to display it; rerunning the episode is a new stateful experiment, not a dashboard refresh.

The body catalogue keeps native195kg physiology, visual78kg target and separate78kg MuJoCo mechanics distinct. It includes22 normalized export fields,195 phenotype definition leaves,56 allele definitions across28 loci,59 affect/somatic/goal definitions,31 neural definitions and35 regional proxy fields. Counts overlap semantically and must not be summed as independent cognitive abilities. The pinned atlas builder enumerates12systems/97nodes; these are not97 independent physiological solvers.

`body.project_native_snapshot(..., model_id=body.MODEL)` projects the existing software snapshot into a closed bounded export; `body.normalize_native(..., now_s=...)` checks its fields, digest and five-simulated-second TTL. Model identity remains caller declared. Checksums establish consistency, not trusted origin. Optional stock values are not covered by the original native observation digest. Missing/stale values remain null. See the body module's exact export contract.

`coordinator.workload_from_export()` maps sympathetic/fatigue/energy indices into declared workload inputs (ceil pressure/fatigue, floor energy after multiplying by1000). The initial state is UNKNOWN. Two safe samples are required for recovery; `request_stop()` stops independently of sample time and remains stopped after restore. This authored controller cannot change evidence, goals, source provenance or permission, and has no demonstrated physiological or subjective benefit.

`evidence.snapshot()` parses exact frozen owner-account reports, never arbitrary untrusted server output. Receipt freshness300seconds, source authentication, liveness and permission are separate fields. New receipts need a reviewed source-manifest update. Ritual status is acquisition with zero independent delayed recall passes. Visual state is plan-only; it does not render, authenticate a human reviewer or prove provider approval.

The evaluator compares adherence to authored recovery rules against always-continue and stateless-threshold baselines. Its first procedural holdout is frozen before execution; subsequent runs are regression. A better score here is not evidence of better real-world performance or awareness. Existing cognitive equal-information baseline results remain a tie.
