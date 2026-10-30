# Frozen longitudinal test of pre-action body forecasts

Starting commit: 11ee0a39a84d44fbc75e808c6560795f1970fb7d. The previous cloud experiment evaluated the first action after each reset. This test asks what happens when the native body and its feedback ledger continue across actions.

Use the unmodified 20 prior single-action fit receipts in docs/evidence/cloud-breath-audit/fit.json (SHA-256 b63ecb0368dba9a8540fade7201a05d21fac14c3b7f4fd81ebfe9389447ae674). Neither model parameters nor examples may be updated from the 40 new outcomes. Start one fresh native session for each row below and advance it five times, always preferring walk, for 0.1 simulated seconds each time. Each session retains its native state and ledger between actions. Six interior cases share pain input .07 and sleep input .47, with starting fatigue .498, .517, .522, .532, .542 or .556. Two additional stress trajectories start at (.532, .78, .47) and (.532, .07, .93) in (fatigue, pain, sleep) order.

## Observers

1. Repeat the exact-name bracketing observer from the single-action experiment unchanged.
2. Repeat the #96 selected bucket observer with pre-action body and applicable past feedback. A supported “other” is only a proxy alarm for slow breathing.
3. Repeat the immediately preceding executed native action as an exact-name forecast. Abstain on the first action.
4. Test one new authored rule. If the current ledger records a failed walk request, forecast observe only when the last native action was observe and its applicable feedback is a verified success; otherwise abstain. With no failed walk request, return the unmodified bracketing forecast.

Record all forecasts before dispatch. Verify each actual action against the native owner's receipt and connect consecutive state checkpoints. Score first vs subsequent actions and separate stress from interior. Report assertions, correct/wrong or abstained, slow-breath false alarms, and the behavior on actual action switches. For the new rule to pass, on the 32 subsequent actions it must make fewer wrong assertions than the frozen exact-name observer, at least as many correct assertions and no more false slow-breath alarms. Record the result of the comparison even when a criterion fails. The eight synthetic trajectories are not a random population and the five actions per trajectory are correlated. None of the observers controls the body.
