# Repository audit: artificial interoception

Observed 12 November 2026, before local implementation. No deployment or merge.
The repository is a collection of mainline infrastructure and unmerged research
branches, not one already integrated live cognitive agent.

| Component | Actual source and inspected revision | Reuse / integration |
|---|---|---|
| Main | `a532f24a5b3eb7a31df6d200950c7287e1e96a35` | Native body, reflection, DecisionCore, local tool host |
| DIOS Core #176 | `24e6d0313ece5674f7e14a11671c18702ae0acee`, `examples/dios_nous` | Dialogue/dissent analysis and metrics; heuristic, not a learning engine |
| Independent Dissent #192 | inspected head `b2b49ec06de47d662b27bc6b65c7e66ec7289ef4` | Inherited PR194 variant used; not a merge of every later #192 patch |
| Goal Continuity #177 | `bef3f9bb42f2365688e3bee3fc5e158881f40510` | Exact reused GoalMemory through existing AdvisoryGoalPlanner |
| Epistemic Revision #182 | `d78e5272300c28729c54c4a61a52593f297b055d` | Exact EvidenceLedger through existing CognitiveSession |
| Evidence/Memory/Decision #185 | `140e6a2c82755dd5163200106ded9ebc2b484660` | Same EvidenceLedger and DecisionCore; exact Rolyel blob `021c752d3cb403211888acb395cd913558249d36` copied with pin check |
| Unified integration #194 | base `6fa94d012cd5265dc407e946ef47dbe7d700a367` | Chosen isolated branch base; already brings pinned cognition and source/body interfaces |
| Native Tadash | `runtimes/tadash_body/unified_body_v2.py` | Real `cycle`, `sensors.touch`, checkpoint, native protective veto; unchanged |
| Native bounded runtime | `examples/nasuraya_body_loop/host.py` | Real BodyLoop/ReflectiveBody/SQLite receipts in disposable native staging |
| Agent Runtime | `examples/nasuraya_agent_loop/local.py` | Real `Policy.choose`, `ToolHost.call`, `run_local`; actual bounded actions |

PR185's `tools/nasu_integration_cycle.py` specifically consumes server/CI receipt
facts. It is not an appropriate palm stimulus executor and is not invoked.
Its already existing memory/decision components are reused without rebuilding
them. The source-pinned epistemic file has Git blob
`eaae3765c53eab12ee948158263b3f28763168bd`; the goal file has
`0c270b25b5f6d0f3ec9c6d35126df613a9bf099f` (PR194 reuse manifest).

Additional inspected branches:

- `nasuraya/tadash-sensory-legacy-bridge-v01`: region/contact labels directly
  drive a finite symbolic signal and native walk/observe preference. It has real
  receipt-linked memory, but not blinded modality/intensity estimation.
- `nasuraya/interoceptive-trends-v01-20261030`: a Page-Hinkley observer on actual
  native HR/RR samples, one per simulated second. It detects mean shifts and
  has no actuator authority. It does not answer this new experiment's inverse
  palm-state inference task.
- The newer unified integration executes fixed native fixtures and reads bounded
  body exports. Its catalogue and advisory recovery are not a palm inverse model.

## Dependency and behavior limits

New implementation: Python standard library only, no paid/model API or GPU.
Native body: Linux/Python 3.11+ (`fcntl`, file locks, SQLite). Seventy source files
are verified and copied before actual native cycles; original sources stay intact.
Optional SDK transport tests are skipped when their dependencies are absent.
Native 195 kg physiology is not the 78 kg atlas or MuJoCo model. Anatomical atlas
nodes are projections of reduced solvers, not fully independent organs.

Existing BodyLoop runs observation → decision request → ReflectiveBody →
UnifiedBody.cycle → atomic runtime/evidence persistence. Actual outcomes can veto
requested motion. Existing local workshop host enforces fresh observation,
safety thresholds and action budgets independently of the new policy.

Gap identified: no unified typed palm stimulation stream plus durable numeric
afferent history, blind inverse readout, separated fitting/evaluation and
measured correction/ablation suite. The new module supplies that gap and adapters;
it does not rewrite native physiology, goal memory or epistemic arbitration.

## Reproducible baseline and validation

Before editing: 177 existing DIOS tests passed, raw log retained. After integration:
31 interoception tests, 177 DIOS tests, 50 agent tests passed; 10 optional SDK tests
skipped; all 25 native body bridge tests passed. Total: 283 passed, 10 skipped,
zero failures in these local suites. These are not every test in every research
branch. Native behavior and returned receipts were exercised, not just imports.

The original protocol, pre-test code commits, a detected selection-leak failure,
corrective addendum, first/new test outputs and model rollback snapshots are all
retained. Local commits preceded their respective runs; GitHub publication is
later, so there is no claim of independently verified public preregistration.
