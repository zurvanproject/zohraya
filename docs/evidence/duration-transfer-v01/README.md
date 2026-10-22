# Duration-transfer evidence

`results.json` is the second complete evaluation; `results-run01.json` is the
first. Their bytes match. Each run measured 126 new whole-body outcomes, apart
from declared internal fixture preparation warmups. These are deterministic
software fixtures, not independent physical subjects.

`validation.json` records the 135 distinct passing tests, source versions,
separate execution/readback amendments and interpretation limits. Final new
test coverage comprises seven tests in `new-tests.txt` and one additional cold
inspection regression in `cold-inspection-test.txt`. `initial-test-failure.txt`
retains a superseded unsuccessful run. See `attempt-notes.json` for the initial
offline warmup oversight, its correction and the negative adaptation result.

`offline-verification.json` rechecked all second-run native checkpoints,
receipts, frozen holdout predictions, policy effects and cold reports while
both `UnifiedBody.cycle` and `PersistentEmbodiment.cycle` were forbidden.
`offline-verification-run01.json` uses that same strict check on the first run.
The hashes detect corruption under a trusted host, not hostile rewriting.

The complete synthetic SQLite ledgers, prospective prediction records and
native checkpoints are in the companion evidence ZIP described by
`checkpoint-archive.json`. `receipt-manifest.json` hashes every data file.
No private/canonical user checkpoint, credentials or model weights are included.
The CI `duration-transfer-evidence` artifact regenerates the complete dataset.

To reproduce from this repository checkout:

```sh
python3 -m examples.nasuraya_self_model.run_duration_transfer evaluate --output /tmp/NEW-transfer
python3 -m examples.nasuraya_self_model.verify_duration_transfer --output /tmp/NEW-transfer
```

To inspect the companion ZIP without a new body action, extract it and use its
`receipts/` directory as `--output` for the verifier. Runtime source hashes in
the checkpoints must match this branch. The verifier prepares only the two
declared legacy defaults; its body/owner action methods remain prohibited.
