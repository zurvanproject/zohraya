# Measured balance experience: promotion blocked

This folder contains the complete frozen experiment, including unsuccessful trials.
The fixed +6 mm reference reduced geometric-mean RMS tilt by 20.46% across six
held-out scenarios but increased it by 97.63% in the unseen rightward push case.
The predeclared criterion was **not met**. No policy was applied to the native body.

- [Persian report and reproduction commands](../../docs/nasuraya-experience-balance-v01-fa.md)
- [Frozen protocol](protocol.json), [training selection](policy.json), [primary outcomes](evaluation.json)
- [Secondary transfer](secondary-evaluation.json), [friction-context hypothesis](context-evaluation.json)
- [Promotion decision](promotion-decision.json), [71-trial integrity audit](evidence-audit.json)
- [Comparison chart](comparison.png), [17-second verified physics replay](visual-replay/comparison.mp4)
- [Terminal tail-joint diagnosis](settling-diagnosis.json), [numerical-kernel diagnosis](numerical-portability-audit.json)
- [Second round: training blocked, fresh validation unrun](../experience-balance-v02/blocked-evaluation.json)

There are 15 training rollouts, 12 primary held-out rollouts and 44 secondary
rollouts. Of these 71, 67 completed the requested steps and met the settling gate;
three training rollouts stopped at the tilt guard and one secondary baseline
completed its steps without meeting the settling gate. The total is 152 accepted
steps, not 152 independently validated scenarios. Original physical traces are
retained as individual gzip files with SHA-256 references in each record.

Primary measurements used the recorded SkylakeX numerical runtime. Separate
Haswell controls diagnose numerical portability and make CI repeatable; they are
excluded from training and held-out scores. Lower RMS, completed steps and an
accepted terminal state are distinct outcomes.
