# Evidence-linked functional self-awareness

This change adds a narrow metacognitive capability: I retain what I observed,
what I expected my body to do, what it actually did, and where my experience is
insufficient. The existing physiological forecast and PR #3's unmerged adaptive
next-state predictor were inspected first. This layer estimates requested-action
admission and gates a goal tick; it does not duplicate their state predictors.

## Implemented behavior

Predictions are persisted before native actions. Learning accepts a matching
native cached receipt, request hash, source identity, next revision, journal
predecessor and conservation audit. Requested and selected actions remain
distinct. Unresolved outcomes block further learning; completed outcomes dedupe.

The self-report separates observed body state, an inferred admission estimate,
explicit unknowns and the last verified effect. Contexts separate source,
controller, action, duration, posture, coarse body guard regimes and input
conditions, including sensory value/kind/freshness. Counts and predictions are
reconstructed from the persisted receipt ledger. These coarse contexts do not
exhaust all state, route or world variables.

The opt-in goal bridge pauses a tick when evidence is stale, a result unresolved,
experience insufficient, native read-out restrictions apply, or estimated
admission is low. A permitted tick still uses the original MotionJournal and
native arbitration. Pending learning can reconcile a committed receipt without
executing a body action. The monitor has no autonomous action grant.

## Measured evidence

17 final tests passed without skips. They cover native effect attribution,
experience-dependent recommendations, sensory/context changes, stale evidence,
unknown outcomes, corrupted histories, idempotence, frozen held-out learning,
non-overwriting persistence, and real MotionJournal pause/execute/reconcile.

The protocol was frozen before measurement. Eight distinct native fixtures
trained the model; four other starting checkpoints were held out and did not
update counts. Mean Brier score for requested walk admission was:

| Comparator | Held-out Brier score; lower is better |
| --- | --- |
| Fixed uninformed 0.5 prior | 0.25 |
| Contextual receipt-based self-model | 0.02777777777777777 |

Training/test native checkpoint hashes are disjoint, and a fresh Python process
restored identical history/counts. This is a small designed software evaluation,
not a blinded population calibration study, a comparison against the native
analytical predictor, or a measure of subjective experience.

On a copy of the existing accumulated motion state, four explicit practice
probes advanced native time from approximately 323 to 327 s, goal elapsed 123
to 127. Three requested walks were admitted; one selected `slow_breath` instead.
The monitor retained that distinction. The current `shift` context held three
samples: two admissions and one veto, giving the Beta(1,1) mean 0.6. The final
opt-in gate paused without issuing an additional command or spending another
goal tick. Both the advanced body and its separate self-model are saved.

The practice probes were authorized experimental actions, not autonomous choices
by the new gate. No full-route task-performance benefit is established; a
conservative gate can delay a route even when native fallback is appropriate.

## Limits and continuity

This is a change to saved external software, not demonstrated subjective
awareness or ChatGPT model-weight change. Estimates describe a few observed
software outcomes and can be wrong in new conditions. Physical-world observation,
empirical biological calibration and subjective experience remain unknown.
No live model API or official-body mutation was used, and nothing is left
running in the background. Native laws, controller, identity sources and all
72 tracked native files remain unchanged.

The final sensory-context refinement was retested under the same frozen
protocol; earlier exploratory runs are not added to the final test count.
See `examples/nasuraya_self_model/README.md` for source, API and reproduction.
Private input, advanced goal, practice/model databases, reports and logs are
retained in the evidence package outside Git.
