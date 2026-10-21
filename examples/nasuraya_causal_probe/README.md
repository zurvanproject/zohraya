# Causal access and recurrence probe

Runs preregistered interventions on two existing retained mechanisms: the V07
symbolic workspace and the six-cell LIF circuit. No language-model/API internals
are accessed. This is not a phenomenal-consciousness detector.

Read [the Persian report](../../docs/nasuraya-causal-access-probe-v01-fa.md) for
methods, pre-analysis amendments, all results and limitations.

```
python3 -m unittest examples.nasuraya_causal_probe.test_study -v
python3 -m examples.nasuraya_causal_probe.run --output /tmp/NEW-causal
python3 -m examples.nasuraya_causal_probe.verify --directory /tmp/NEW-causal
```

The output directory is exclusively created; each intent precedes its native
execution in SQLite. Raw receipts, checkpoints and neural traces are gzip JSON.
Offline verification patches both native step methods to reject execution.
A second run can be compared with `verify --directory FIRST --compare SECOND`.
All native sources and official/user checkpoints remain unchanged.

The broadcast-cut score of zero denotes `no_shared_access`, not 24 incorrect
classifications. Circuit seed labels repeat identical inputs: report 3/8 unique
recurrence effects, not 9 independent observations out of 24. The perturbation
probe did not demonstrate multicell propagation at the frozen settings.
