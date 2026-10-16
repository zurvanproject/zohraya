# Native embodied learning Sprint 01

`results.json` retains all 81 native outcomes (three initial training probes are
separate). The protocol was frozen before execution. Adaptation and held-out
metrics, source equality, cold restore and limitations are explicit.

The full synthetic checkpoint bundle contains `native-receipts.zip`: 82 SQLite
files and 81 prospective prediction JSON files. `receipt-manifest.json` records
every member; `checkpoint-archive.json` records the archive hash. No private/user
body state, API secret or language-model weights are present.

`verify_sprint` reopens all 81 journals with native cycle execution forbidden,
checks the exact prospective decisions, receipts and metrics, and deduplicates
the completed events. To regenerate rather than inspect, run `run_sprint evaluate`
with a new destination. That executes new simulated actions.

The native sources are unchanged. A and C have equal requested-walk admissions;
C improves admission prediction on a held-out state in a learned context. No gain
is demonstrated on an unseen duration, physical gait quality or consciousness.
