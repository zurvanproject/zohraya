# Shared-session evidence

`result.json` contains the actual workshop, normal native and sleep native demo
receipts. `summary.json` contains a compact derived view. Full semantic snapshots
and provenance are retained as `*-snapshot.json.gz` (standard gzip). Original model execution reports retain
raw checkpoint-byte hashes in `*-fixed-models-report.json`.

Test logs preserve the first failures, second failure and passing final checks.
The initial failed assumptions were not discarded:

1. Original receipt used a tuple; JSON replay used a list. Normalize the return
   value to the persisted JSON form.
2. The inherited affect serializer produced differing byte hashes for identical
   semantic state. Retain the raw report and use canonical state identity for
   shared snapshots. Do not modify pinned source code to hide the difference.
3. Affect intensity values did not change in the tested episode. Retain that
   finding; verify actual somatic feedback and affect checkpoint evolution.
4. Sleep veto applies to walk, not the initial observe. Exercise the actual walk
   request and retain its protection outcome.
5. DIOS's outward stance was PROVISIONAL_DISSENT. Consume its underlying evidence
   verdict rather than matching a presentation label.
6. Review exposed a scope error: success of observe must not clear walk's veto.
   Separate action claims and verify continuing deferral after successful observe
   and reopening.
7. First GitHub Windows CI stopped before execution: Git changed line endings
   in the pinned native manifest. Mark the imported native tree `-text` so Git
   preserves its exact bytes. Keep all checksum checks; do not normalize or
   regenerate pinned hashes to bypass this failure.
8. The next Windows run passed the contracts but exposed retained SQLite handles
   during cleanup. SQLite's transaction context does not close its connection.
   Explicitly close the creation connection and cover decoder-validation failures
   with the constructor's close path; close the test's corruption connection too.

These are integration fixtures, not another held-out sensory experiment.
Existing PR195 accuracy/calibration results are unchanged and should not be
extrapolated to a continuous stream. No production service was contacted.
