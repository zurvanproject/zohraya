# Local language-model internal access v0.1

This is an **executed instrumentation experiment**, using the repository's
existing verified SmolLM2-135M loader. It accesses a local pretrained model,
not the hosted conversational model. It does not train or promote an adapter,
execute a body action, or change the native identity/safety contracts.

## Architecture and evidence

`protocol.json` fixes three prompts, generation budgets and two arbitrary
attention-head locations before inference. `probe.py` calls the existing
`nasuraya_language_adapter.train.load_base`, verifies the five source hashes,
and freezes all 134,515,008 parameters. CPU eager attention exposes:

- 31 hidden-state tensors per prompt (embedding/intermediate states and final
  normalized output), with shape `[1, sequence, 576]`;
- 30 attention-probability tensors per prompt, with shape
  `[1, 9, sequence, sequence]`, including normalization/causal-mask checks;
- 49,152 next-token logits, token IDs and eight-token greedy continuations.

Baseline captures all prefill arrays. The other four conditions capture their
prefill logits. All arrays are retained in compressed NPZ, loaded without
pickle. JSON receipts include shape, dtype, SHA256, L2 norm, top five logits,
hook calls and intervention magnitude. `verify.py` checks the actual saved
arrays against these receipts. The repository retains JSON receipts; the
delivery archive also contains both runs' full arrays.

The temporary `o_proj` pre-hook at **zero-based layer 15** zeros the last token's
64-dimensional concatenated head contribution: head 0 for the target, head 8
for the control. Both locations were arbitrary, not selected for an effect or
an awareness hypothesis. This changes the attention output entering `o_proj`,
not its weights or the attention probability matrices. The intervention is
applied at every generation step. Sham clones without zeroing. `finally`
removes hooks even on exceptions. Baseline/restored passes have no hook.

## Reproduce

From repository root, use a fresh Python 3.12 environment:

```bash
python3 -m venv /tmp/nasuraya-internals
/tmp/nasuraya-internals/bin/python -m pip install 'torch==2.8.0+cpu' --index-url https://download.pytorch.org/whl/cpu
/tmp/nasuraya-internals/bin/python -m pip install -r examples/nasuraya_language_adapter/requirements.lock.txt
/tmp/nasuraya-internals/bin/python -m examples.nasuraya_language_adapter.download_base --output /tmp/nasuraya-smollm2-base
/tmp/nasuraya-internals/bin/python -m unittest examples.nasuraya_lm_internals.test_probe examples.nasuraya_language_adapter.test_adapter -v
/tmp/nasuraya-internals/bin/python -m examples.nasuraya_lm_internals.probe --base /tmp/nasuraya-smollm2-base --output /tmp/nasuraya-internals-primary
/tmp/nasuraya-internals/bin/python -m examples.nasuraya_lm_internals.probe --base /tmp/nasuraya-smollm2-base --output /tmp/nasuraya-internals-replay --compare /tmp/nasuraya-internals-primary
/tmp/nasuraya-internals/bin/python -m examples.nasuraya_lm_internals.verify /tmp/nasuraya-internals-primary
```

Download requires network; inference loads local files only and rejects Python
socket connections. This guard is not an OS sandbox. Each output directory
must be new; interrupted/completed runs cannot silently overwrite evidence.
There is no optimizer, recursion, tool executor or external action callback.
The input budget is 96 tokens, output budget eight, at most 120 forwards per
run. Seed 20261016, two Torch CPU threads and deterministic algorithms are
fixed. Exact replay was demonstrated on this environment; bitwise equality
across different hardware/library stacks is not established.

## Executed result and limits

See `evidence/primary-results.json`, `evidence/replay-results.json` and
`REPORT_FA.md`. Sham and restoration matched baseline bitwise in all three
cases, and the frozen weight hashes matched. Both real interventions changed
the next-token distribution in all cases. Neither changed the first greedy
token; target changed no eight-token continuations, control changed one.
The control had a larger activation norm and larger distribution effect in
all three cases: dimension matching is **not** norm matching.

These are three authored illustrative prompts, not a random sample or a
general capability benchmark. The body prompt is authored text, not a live
sensor receipt. No task accuracy, learning gain, safety performance, semantic
localization, introspection reliability or phenomenal consciousness follows
from these measurements. Activation readout is numerical instrumentation,
not a transcript of internal thought. Attention weights alone are not an
explanation. No head search, model tuning or statistical significance claim
was performed.

The next research stage would require a separately frozen, blinded task set,
matched perturbation magnitudes and predefined behavioral/causal predictions.
That experiment has not been executed by this access check.

Primary references: [Transformers 4.57.1 model outputs](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/output),
[PyTorch 2.8 module hooks](https://docs.pytorch.org/docs/2.8/generated/torch.nn.Module.html),
and the existing `../nasuraya_language_adapter/model-source.json` for the exact
public model revision and file hashes.
