# Stage 3 retained evidence

Base: PR197 at `8b047811d2814e595ecd2e2f16fee8be6c229732`.
Protocol published at `60ec25fd270f2e83d9865c37235924c0174625a4`.
Final evaluator/model/body sources were published **before first holdout** at
`66d904fb59af636141fc134a94d19d0a51156fe9`, tree
`4e97c4ae7ad36c132d655f0d5fcddaff74bfb841`.
The final source-freeze model envelope is
`13ca6fbbf202fc6c73012a17e9fd337fb63f411721a22eb190f9e1e190ebd78b`;
learned detector fingerprint
`2469dbdcc3738fee188e113d3bc345e4020ed56a6c43155177cadabd0cbbfbcc`.
No held-out updates occurred. Validation rejected promotion.

| Artifact | Meaning |
|---|---|
| `integration-audit.json` | One current morphology authority, actual implementation connections and explicit unresolved services |
| `frozen-model.json` | Unchanged learned parameters, final 18-source evaluator hashes, disjoint whole-stream seeds, rejection status |
| `initial-frozen-model.json` | Original development artifact before unrelated body integration source finalization; parameters exactly equal to final freeze |
| `initial-development.json` | All three predeclared candidates and diagnosis grids; validation and both original/strict DIOS verdicts |
| `development-observer.jsonl.gz` | Prediction-before-reveal records during development and strict correction decision |
| `report.json` | First new held-out known, novel and shifted-noise metrics for eight comparators |
| `predictions.json.gz` | Every held-out prediction and evaluator truth, including all mistakes |
| `observer.jsonl.gz`, `first-observer-audit.json` | Hash-linked prediction commitments, reveals, strict error count; independently checked order for 6,280 predictions |
| `body-report.json` | Actual legacy/current parameters and six-cycle normal/sleep outcomes; conservation and cold repeat |
| `tadash_*.json.gz` | Complete original/derived body execution evidence and transformation receipts |
| `candidate-native-session.json.gz` | Explicit research candidate in the actual current-body session, cognitive projections, replay and stop |
| `validation-summary.json` | Executed checks, concrete development errors/fixes and false-positive/negative counts |
| `*-tests.log.gz` | Full local test transcripts; `initial_failure` is deliberately retained |
| `historical-stage2-verification.json` | Replay of the prior experiment at its actual historical source checkout |
| `holdout-replay-verification.json` | No-fit replay of already-opened stage-3 data, not a second independent test |

Gzip timestamps are zero for reproducible encoding. `report.json` timing is
machine-specific. Reproduction compares categories exactly and numbers with
1e-10 absolute / 1e-9 relative tolerance for Python 3.11/3.12 summation.
Within each observer transcript, hashes must be exact; cross-Python state-byte
hash differences are separately reported. Hashes are consistency checks, not
cryptographic authentication against a hostile local actor.

`selected` in the new experiment is the stage-2 fallback because strict validation
rejected the candidate. The actual runtime default remains `legacy`. Neither
fallback is validated as a robust noisy continuous detector. Location/type scores
count missed detections as errors; intensity MAE includes absent windows. The
candidate improves detection specificity while losing sensitivity/classification.
No result establishes subjective experience, calibrated biological physiology,
independent anatomical mechanics, a service deployment or an LLM connection.

Run from repository root:

```bash
python -m scripts.verify_nasuraya_stage3 --output /tmp/stage3-new-regression
python -m examples.nasuraya_runtime.body_demo --output /tmp/stage3-new-body
python -m examples.nasuraya_runtime.audit --output /tmp/stage3-new-audit.json
```

Read [current architecture and commands](../../../examples/nasuraya_runtime/STAGE3.md)
and [Persian findings](../../research/NASURAYA_STAGE3_RESULTS_2026-11-12_FA.md).
