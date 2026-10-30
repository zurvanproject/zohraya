# Continuous self-knowledge v0.2 evidence

These are compact results from the complete, source-frozen evaluation. The full
native archive and pre-action records are delivered separately with the Persian
report. `raw-evidence-sha256.json` identifies those exact files.

`summary.json` retains the predeclared acceptance outcome, including any failed
criteria. Training and validation were frozen before the held-out test. The
supplementary bootstrap is conditional on fixed training histories and uses
whole eight-action case blocks; it does not establish population confidence.

The persistent demonstration is separate from the 3,888-cycle evaluation. Each
step opens its existing SQLite session in a new process. The replay checks
assert unchanged saved state and zero additional body actions.

Reproduction and limitations are documented in
`../../nasuraya-continuous-self-knowledge-v02-fa.md`.
