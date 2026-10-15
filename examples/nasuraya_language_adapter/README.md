# Nasuraya language weight adapter v0.1

This is actual gradient training of attention adapters in a pretrained causal
language model, `HuggingFaceTB/SmolLM2-135M`. It does not substitute a counter,
retrieval memory or a classifier head for language-model weight changes.
The base tensors remain frozen; the effective attention matrix is
`W_effective = W_base + (alpha/r) B A`. LoRA's A/B tensors are optimized on
answer-token language-model cross entropy in the last four transformer layers.

The narrow task is completing a prompt with `ADMIT` or `DEFER` for a bounded
software walk. Inputs contain the pre-action sleep pressure, requested duration,
declared friction intervention and current native walking restrictions. Those
restrictions are already available from the existing body audit; this distills
part of that evidence into a small language model. It is not discovery of new
mechanics, autonomous policy evolution, Persian dialogue training, a change to
the ChatGPT model, or replacement of the live API model. No execution authority
is granted. Existing identity, mechanical equations and body gates are untouched.

## Data and comparison

`protocol.json` is copied before generating new labels. Its fixed pressure
split produces 48 training fixtures and 24 held-out fixtures; four prior verified
live Agents API software-body receipts supplement training. Every generated
label comes from an actual native `cycle` and passes the existing SelfModel
receipt checks with `learn=False`; the old live model is not modified. Labels,
prompts and before/receipt digests are tied to the checked episode databases.
Training and held-out initial checkpoint hashes and prompts must be disjoint.

The optimizer sees training rows only. The protocol fixes all hyperparameters
before measuring outcomes. There is no held-out gradient, early stopping or
hyperparameter search. Baseline and final model are evaluated by the likelihood
of the same two fixed answer completions, including EOS. The resulting
two-choice probability is not a calibrated physical success probability.
Accuracy, balanced accuracy, Brier score and answer-token loss are reported,
including regressions. This is one synthetic family with numeric interpolation,
not evidence of generalization to other bodies or general intelligence.

## Reproduction

Python 3.12 and CPU are sufficient. The exact installed dependencies are recorded
in `requirements.lock.txt`; the public base files have a pinned revision and SHA256.
No API credential is required or read by this package.

```sh
python3 -m venv .weight-env
.weight-env/bin/python -m pip install 'torch==2.8.0+cpu' --index-url https://download.pytorch.org/whl/cpu
.weight-env/bin/python -m pip install -r examples/nasuraya_language_adapter/requirements.lock.txt
.weight-env/bin/python -m examples.nasuraya_language_adapter.download_base --output /private/smollm-base
.weight-env/bin/python -m examples.nasuraya_language_adapter.train prepare \
  --output /private/NEW-weight-run --live-memory /private/approved-four-episode-memory.sqlite
.weight-env/bin/python -m examples.nasuraya_language_adapter.train train \
  --output /private/NEW-weight-run --base /private/smollm-base
.weight-env/bin/python -m unittest examples.nasuraya_language_adapter.test_adapter -v
```

The four-episode memory must be the actual verified source checkpoint, not an
invented file. The retained private checkpoint contains backed-up label
databases and the complete frozen dataset, so verification does not need to
generate additional body cycles or contact an API:

```sh
.weight-env/bin/python -m examples.nasuraya_language_adapter.train verify \
  --output /private/restored-weight-run --base /private/smollm-base
```

The training command saves initial/final safe tensor adapters, raw tensor change
counts and norms, frozen-base fingerprints, effective attention hashes, full
training example IDs, and per-case evaluation. A fresh process reloads the final
adapter with socket connections forbidden and checks identical effective weights
and matching answer log likelihoods. It performs zero optimizer or body steps.
Adapters depend on the exact pinned base; the small adapter is not a standalone
replacement for the base model. Runtime weights and private label databases are
retained separately from the code repository.

Sources: [base model and Apache-2.0 license](https://huggingface.co/HuggingFaceTB/SmolLM2-135M),
[PEFT LoRA](https://huggingface.co/docs/peft/en/quicktour).
