# Corrective prospective addendum (after first 500-case run, before new test)

The first run at local code commit f40bdca is retained, including all predictions,
observer events and model snapshots. Its detection result was 500/500. Review
then found a **novelty-isolation protocol violation**: although compound examples
were excluded from neighbour fitting, temperature selection used their binary
outcomes, and validation acceptance included them. Thus it was not a fully unseen
modality for all fitting/selection steps. Do not call that first result proof of
out-of-distribution generalization. The numeric decoder did not see truth labels
at prediction time; the problem is model-selection exposure to the novel family.

Correction, specified before implementing it or opening the new test:

1. Keep all first-run artifacts unchanged. Temperature fitting and validation
   acceptance use **only non-compound episodes**. Record and test those seed IDs.
   Diagnosis may report novel failures, but none of those cases may fit or select
   any parameters. Condition and truth remain evaluator-only data.
2. Persist every variant's old decoder alongside its selected decoder, so all
   accepted parameter updates have a directly loadable rollback.
3. A fresh confirmation test uses seeds **750000–750499** (five conditions,
   100 each), never previously generated or examined. The old 740000 range
   becomes an exploratory/regression set. No other generative or decoder
   algorithm, k, feature, acceptance threshold or temperature grid changes.
4. Same train/diagnosis/validation seeds, baselines, ablations and metrics.
   Confidence/acceptance scores must use only 112 non-novel validation episodes.
5. After inspecting the new confirmation set, no scientific retuning. Any further
   execution of it is regression. Report secondary regressions, attention
   ablation, unknown-type failure and behavioral-utility limits even if detection
   remains high. The correction is a limited supervised algorithm, not general
   autonomous discovery.

The agent-facing numeric introspection report was added after the first run; it
only exposes existing state/prediction fields. It does not change inference.
Local preregistration history is retained. GitHub upload happens after local
execution; this is not independently timestamped public preregistration.
