## What actually ran

On Linux, the existing `native_snapshot.snapshot()` and
`body_observer.observe_native_body()` read a newly initialized native simulation
at time zero. The input was authored defaults, never saved user body data.
Forty-five source files were fetched at main commit
`a532f24a5b3eb7a31df6d200950c7287e1e96a35`, checked against exact Git blob hashes,
and copied into a disposable directory. The source files in the checkout were
also reconstructed byte-for-byte after verifying their existing Git index hashes.
No native source code was changed.

The standard synthetic fixture helpers execute a seven-second warm-up, so they
were deliberately not called. Instead, the existing memory/renal/persistent
constructors and `UnifiedBody.migrate()` initialized the model without stepping.
Ten cycle, step and affect-transition entrypoints were guarded to fail if called.
All guard call counts remained zero, simulated time and revision remained zero,
and the complete before/after native checkpoints were equal within the run.

`native-readout.json` contains the executed readout, source hashes, six sensory
features, simulated foot coordinates, sixteen minimum-state fields and six
finite stocks. `native-export.json` is the closed export accepted by DIOS. These
are actual software readouts of initial simulation state, not physical sensors,
live user physiology, or an experiment executing physiological dynamics.

## Reproduction

On Linux with the pinned original repository sources present:

```sh
python -m examples.dios_nous.unified.native_readout --output receipt.json --export-output native-export.json
python -m unittest discover -s examples/dios_nous -p test_unified_native_readout.py -v
```

Output files must not already exist. That check happens before the worker is
started. The worker uses isolated Python `-I -S`; both the public entrypoint and
the internal worker copy only verified source bytes before initialization. A
regression test invokes the internal CLI with existing caller default files and
verifies both remain unchanged. Windows uses the exported JSON and does not
import or execute the Linux native runtime.

## Recorded failures and limits

The first import attempt failed because the initial materialization filter
omitted `run_balance_checks.py`, which provides native audit classes. Fetching
that original pinned dependency fixed the import; no substitute was written.
An initial command also exceeded the shell argument-size limit before any native
process began. These attempts are recorded in `native-readout-attempts.json`.

A test initially assumed identical full checkpoint hashes across fresh Python
processes. That assertion failed. Two actual checkpoint comparisons found one
non-hash difference: the ordering of
`payload.owner.payload.owner.payload.runtime_dictionary_orders.brain:source_sequences`.
The native cognitive workspace constructs the dictionary from a set of source
names; the renal checkpoint intentionally records dictionary iteration order.
Five dependent hashes consequently differ. Exact paths and values are preserved
in `native-readout-checkpoint-diff.json`.

No native physics or serializer was edited, and no hash-seed workaround was
introduced. The corrected regression checks full checkpoint equality within each
run, and across fresh processes checks the observed body digest, minimum state,
and finite stocks. Fresh checkpoint bit identity is explicitly not claimed.
This correction was made after seeing the failure and is not an independent or
preregistered scientific result. The final focused suite passed six tests.

The 195 kg legacy physiological model remains distinct from the 78 kg visual
target and separate MuJoCo mechanics. Source integrity does not authenticate an
arbitrary supplied export. No server action, paid API, neural training, model
weight update, physical action, or subjective experience is established here.
