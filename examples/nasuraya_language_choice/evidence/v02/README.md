# Fixed comparison and live advisory evidence

The parent adapter already separated the two score groups, but both stayed below
the original 0.5 decision cutoff. The old test set is development evidence here.
The v0.1 diagnostic and parent train-only threshold are retained openly.

All five equally warm-started, fixed-budget arms committed their fresh-case
predictions before any fresh outcome labels were generated. The primary arm
`choice_balanced` was preselected, not chosen from the fresh results. It achieved
24/24, including 8 admissible and 16 rejected walks. Continued original-loss
training, unbalanced choice training and the parent with a train-only threshold
also reached 24/24. Balanced original-loss training and the shuffled-target
control reached balanced accuracy 0.75. These comparisons do not prove that
new weights were necessary or that the chosen recipe is uniquely superior.

Two actual API sessions received the selected advisor's output. The normal
session executed a matching 0.1-second walk. The sleep fixture chose and executed
a 1-second sleep after receiving DEFER advice about a 0.1-second walk; that walk
forecast was not physically tested. Non-walk advice is unsupported. Both saved
goals cold-replayed without network, native cycles or duplicate learning. Both
remote sessions were deleted. Shared copied memory advanced from 4 to 6 episodes;
the original live memory remained unchanged. There is no isolated causal test
of advisor influence on the API agent's decision quality.

13 language/advisor tests and 78 API regressions passed. All 72 tracked native
runtime files match the parent. Full body plans, service IDs, runtime ledgers,
model text output and adapter binaries are excluded from this public directory.
The SHA-bound private checkpoint retains weights, plans and receipt stores.
