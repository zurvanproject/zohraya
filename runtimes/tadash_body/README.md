# Tadash Reflection Cycle 0.1

Read `REPORT_FA.txt` for Persian findings and `REFLECTION_CYCLE.md` for the API,
provenance contract, persistence limits and reproduction instructions.

From this directory, Linux and Python 3.11+ (standard library):

```sh
python3 run_tests.py --reflection --output /tmp/tadash-reflection-check
```

`evidence/` in the outer bundle holds frozen baseline/comparison records, logs,
and the completed demonstration. Its `final_validation/reflection_demo/` folder
contains resumable SQLite experience ledgers. Use a new output directory for a
fresh demo; never replace an existing user's checkpoint with generated defaults.
The original source provenance is retained; the additive intervention's source
inventory is `REFLECTION_PROVENANCE.json`.
