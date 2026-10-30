# Pre-action slow-breath audit

The fixed starting point is PR #96, commit a868545ece003b0d949317d9877cacfeb60ad475.
Its three missed slow-breath outcomes came from two distinct initial states. This targeted simulator test asks whether an observer trained on exact action names can forecast the action before it happens and withhold a forecast when its evidence disagrees. It does not change arbitration or use an external model service.

## Frozen design

Every case starts a fresh native body session from the same source-pinned template, requests walk for 0.1 simulated seconds, and has no feedback history. Only the listed starting inputs change. The held-out cases share the simulator and are not a random population sample.

| Partition | Fatigue inputs | (Pain input, sleep input) |
| --- | --- | --- |
| Fit (20) | .480, .510, .518, .523, .530, .538, .543, .548, .558, .580 | cross with (.04, .34) and (.12, .61) |
| Held out, interior (11) | .488, .513, .519, .521, .525, .533, .541, .544, .546, .552, .574 | (.08, .455) |
| Held out, stress (4) | .510, .535 | cross with (.78, .455) and (.08, .93) |

Use only the 20 fit receipts for both observers. Freeze each held-out forecast before executing its action. The #96 observer uses its published selected configuration. Because it pools slow breathing with other actions, also give it credit as a binary alarm whenever it predicts a supported “other”; distinguish that proxy from a named prediction.

The candidate uses observed fatigue between the two nearest bounding fit levels. It predicts an exact native name only if both levels agree unanimously, and observed pain and sleep lie within the training range. Otherwise it abstains. The simulator's action thresholds are not model inputs. No thresholds or cases may be retuned after opening the held-out results.

Report native action counts, exact-name precision among issued predictions, coverage, slow-breath recall and false alarms separately for the 11 interior and 4 stress cases. Show counts with denominators. A focused improvement requires at least one correctly named interior slow breath without a false slow-breath alarm in either held-out group. Abstentions remain in the recall denominator. Passing this small test does not authorize using the observer to control movement.
