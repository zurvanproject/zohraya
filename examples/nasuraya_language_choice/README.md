# Language choice correction and nonbinding advice v0.2

The first adapter ranked admissible requests above rejected requests, but both
score groups stayed below 0.5. Its all-DEFER result did not mean it had learned
no distinction. `lm-v01-diagnostic` evidence reports the old training/development
score ranges and a threshold selected on training rows only. Old test cases are
now development evidence and are not counted as a new test.

The frozen protocol compares five equally warm-started, 52-step arms: original
answer-token/EOS loss versus two-completion choice loss, each with original or
balanced sampling, plus a fixed shuffled-target control. Balanced batches cycle
validated training rows with two targets per class. No receipt labels are edited
for balancing. The shuffled control records its artificial targets separately.
Choice loss excludes prompt, padding and EOS; it learns the relative likelihood
of the two label completions. Evaluation uses the same label-only scoring for
all arms. It is a constrained completion task, not free language generation.

`choice_balanced` is the primary arm selected before new outcomes. Six new sleep
pressures and two new durations produce 24 fresh inputs. All arm weights and
predictions are saved before generating the first fresh native outcome. Neither
hyperparameters nor the winning arm are selected on these labels. A parent
threshold calibrated on old training data is also frozen before fresh labels.
All results, including null controls and that calibration comparator, are kept.

## Run

Use the pinned dependencies in `requirements.lock.txt` (install CPU torch from
https://download.pytorch.org/whl/cpu first). The base and prior adapter come from
the source-pinned v0.1 checkpoint. No API key is read for training or verification.

```sh
.weight-env/bin/python -m examples.nasuraya_language_choice.experiment prepare \
  --output /private/NEW-choice-run --parent /private/verified-v01-checkpoint
.weight-env/bin/python -m examples.nasuraya_language_choice.experiment train \
  --output /private/NEW-choice-run --base /private/pinned-smollm-base
.weight-env/bin/python -m examples.nasuraya_language_choice.experiment verify \
  --output /private/NEW-choice-run --base /private/pinned-smollm-base
.weight-env/bin/python -m unittest examples.nasuraya_language_adapter.test_adapter examples.nasuraya_language_choice.test_choice -v
```

## Advisory bridge

Only an adapter passing the frozen promotion criteria can be configured. The
bridge rechecks actual native receipt labels, saved predictions, source hashes,
weights and promotion metrics. The host requires a current body checkpoint,
enabled metacognition and no unresolved outcomes or retained API session.

```sh
.weight-env/bin/python -m examples.nasuraya_body_loop configure-language-advisor \
  --session /private/body.sqlite --advisor-run /private/verified-choice-run \
  --advisor-base /private/pinned-smollm-base \
  --observed-checkpoint-sha256 ACTUAL_CURRENT_SHA
```

The existing explicit `api` command then lazily chooses `AdvisedBodyAPIHost`.
Legacy sessions still use `BodyAPIHost` and do not import torch. Programmatic
callers use `examples.nasuraya_body_loop.language_advisor.host_type(loop)` and
its `resume` method to obtain the configured host. Advice is nested inside the
existing `assess_body_action` result; it does not execute a body cycle, train,
change budgets or override the actual core-selected action or native guards.
Only walk is covered; other actions return unsupported. Paths and full bodies
are not included in the advice. A mocked ADMIT recommendation is explicitly
tested against the real enforced gate and cannot make it execute.

After promotion, the explicit `nasuraya_language_choice.live live` command uses
two fresh software fixtures, normal and sleep, each capped at one action and 16
tool calls. The API agent reads advice and may select a recovery action. A walk
prediction is compared with a receipt only if the core actually requested that
same walk from the same checkpoint and duration. Other actions do not validate
or falsify that walk forecast. Goal failure, native veto and untested advice are
reported honestly; no automatic replacement trial is made. The shared memory is
a copy of the previous four live experiences. Original state is not modified.

Completed goals are reopened in a new process with network calls forbidden;
no body or optimizer work is repeated. Full ledgers and adapter binaries remain
in private checkpoints; reduced results and native source audits are public.
