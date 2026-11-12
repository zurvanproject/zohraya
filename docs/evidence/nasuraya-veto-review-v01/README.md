# Veto-review evidence

All events are source-pinned, offline software simulation. Original baseline:
PR196 `349860caa796ea388baaf0d3d420361316756818`. Research implementation and
acceptance criteria are in [the design](../../research/NASURAYA_VETO_REVIEW_DESIGN_2026-11-12.md).

- `summary.json`: parameters, ten scenarios, actual request/execution counts,
  and complete hot/cold comparison outcomes.
- `actual_walks` counts native cycles whose selected/executed action is `walk`;
  it does not count completed footfalls or establish gait safety.
- `traces.json`: readable per-event observations, proposed/executed actions,
  reasons, retained veto count, and probe budget.
- `full-results.json.gz`: complete receipts and semantic final snapshots for
  both policies. The runner asserts exact hot/cold equality before retaining
  the single identical representation for each pair; no hash fields are removed.
- `runtime-contracts.txt`: 39 successful tests, including 22 new review contracts.
- `interoception-regressions.txt`: 33 successful inherited tests.
- `dios-regressions.txt`: 177 successful inherited tests.
- `agent-regressions.txt`: 60 discovered; 50 successful, 10 optional SDK skips.
- `native-regressions.txt`: 25 successful inherited body-loop tests.
- `initial-failure.txt`: fixture-journal, JSON-boundary and initialization-pairing
  failures, their causes, and corrections. Expectations and safety checks were
  not weakened to make these runs pass.
- `manifest.json`: hashes of retained evidence and runtime source identity.
- `ci-code-head.json`: successful Linux/Windows CI receipt for the code commit,
  including explicit platform skips. Later commits add evidence/docs only.

Reproduction creates fresh SQLite sessions and immutable projections in the
requested output directory. Those disposable runtime stores are not production
checkpoints. The complete generated stores are reproducible from the runner;
the smaller inspected evidence is committed here.

```bash
python -m unittest examples.nasuraya_runtime.test_session examples.nasuraya_runtime.test_veto_review -v
python -m examples.nasuraya_runtime.veto_experiment run --output /tmp/new-veto-run
```

Native evaluation requires Linux. Portable policy contracts also run on Windows;
native tests are explicitly skipped there. Repository CI does not run the entire
ten-case measurement, which is retained from the local Linux execution. See the
PR's exact-head CI links for platform-specific status.
