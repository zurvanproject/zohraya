# Special-organ coordination checks

Run `python run_tests.py --special --output /tmp/tadash-special-results` from
this directory. The runner verifies source hashes, creates synthetic defaults
in an isolated temporary tree, runs the existing tests, and adds counterfactual
checks for Resonan, Spandar, and Azarine. The special checks supply no meal or
drink and never load a user checkpoint.

The additional scenarios cover missing light, declared light and its full
energy partition, an isolated light route, heat gating and an explicitly reset
heat fixture, saturation, small reserves, a reserve budget label that cannot
create energy, memory/error feedback, expired evidence, and exact continuation
after JSON serialization. Results distinguish simulated time from execution
time and identify the separate seven-second synthetic warm-up.

The runtime equations are unchanged. These checks validate the recovered
software coupling; they do not complete the proposed anatomy or physical
properties of the fictional organs. Left/right Resonan lobes still share one
light-control model. Spandar tracks a memory digest and prediction error.
Azarine is a ceiling within `reserve_J`, not another energy or heat reservoir.
The heat reset is an intervention in a test fixture, not spontaneous recovery.

Source context: `Nasuraya_Whole_Body_Audit_2026-10-11.html` and
`NASURAYA_STANDING_ANATOMY_V06_FA.html` (special organs proposal 0.7).
Proposed geometry and tested reduced dynamics remain separate.
