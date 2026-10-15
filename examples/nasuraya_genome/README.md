# Nasuraya: 48-chromosome computational genome v0.1

The existing dosage design is retained. A versioned genotype-to-phenotype
prototype now adds four bounded limb-design loci, a closed contract for every
chromosome, JSON Schema, atomic in-memory edit batches and recomputed cold
checkpoint restoration. See the [Persian architecture and evidence report](../../docs/nasuraya-genome-v01-fa.md).

```sh
python3 -m unittest discover -s examples/nasuraya_genome -t . -v
python3 -m examples.nasuraya_genome.traits --output /tmp/genome-traits-demo.json
```

`contract-v0.1.json` contains 48 stable chromosome IDs and 28 logical loci:
24 existing software dosage proxies and four trait loci, each with A/B alleles.
`genotype-v0.1.schema.json` is the closed Draft 7 JSON Schema;
`baseline-v0.1.json` is the complete 48-chromosome starting genotype.
`validate_genotype` additionally verifies source hashes, strict finite-number
types, revision/parent consistency and full locus coverage. `express` enforces
the authored foot-proportion coupling. The implementation uses only stdlib.
Contracts and examples are generated deterministically with
`python3 -m examples.nasuraya_genome.generate_contract`; regeneration after source
drift requires explicit review and an appropriate version/migration decision.

`mutate(..., expected_revision=...)` returns a new valid genotype or rejects
the entire edit batch. `checkpoint`, `save` and `restore` round-trip that genotype
and recompute its phenotype. Checksums detect accidental corruption and drift;
they are not signatures, authenticated ancestry or a concurrent multiwriter
database. Save files are proposal checkpoints, separate from native body/session
state. The source runtime directory is a forbidden save destination.

The identity covenant, fixed-face preservation policy and count invariants are
outside mutable alleles. G22/G23 learning remains external. No face image is
loaded, rendered or verified by this module. Structural expression produces a
candidate specification only; `native_apply_allowed` is always false, including
for the baseline. Proposed dimensions cannot authorize native changes, move a
body, enlarge a contact patch or recover fatigue. Appearance genes only emit
metadata; they do not alter a mesh. L000 audit results cannot grant action.

## Retained dosage model

The user's 15 October 2026 instruction proposes **48 design chromosomes: 24 A/B
pairs**. This is a Tadash software architecture, not an observed physical
karyotype. The preserved Library genome v0.38 (Library version 46, source hash
in `genome48.json`) has 22 anatomical modules in 12 regulatory domains, plus
learned overlays G22/G23. Those layers are not recast as chromosomes.

Each existing domain receives two distinct pairs: a developmental program and
an adult maintenance program. This split is authored engineering design; the
old source did not assign these chromosome positions. A/B are homolog labels,
not parents, sex chromosomes, nucleotide sequences, lengths or real loci.

The pure audit assigns half nominal dimensionless capacity per copy and caps
extra copies at nominal output while recording copy deviations. A declared
boundary fault quarantines its domain. Developmental capacities propagate the
original module prerequisites and phase gates. Maintenance ceilings stay local:
loss of a developmental program never deletes an existing adult organ. These
ceilings **do not grant functional or action permission**. Actual perfusion,
innervation, fresh observations, resource authorization and support mechanics
remain the body runtime's responsibility. G12 stays disabled at every phase.
No energy, material, muscle strength or fatigue recovery is created by an audit.

Run:

```sh
python3 -m unittest examples.nasuraya_genome.test_chromosomes -v
python3 -m examples.nasuraya_genome.chromosomes --output /tmp/genome48-evaluation.json
```

The fixed software survey includes baseline, all 48 single-copy losses, all
48 extra-copy perturbations, all 12 boundary faults and five developmental
phases: 114 conditions, not 114 biological experiments. It checks declared
contract behavior; it cannot establish phenotype improvement. Audits pin the
design hash and are recomputed from their saved conditions during verification.
No current body state, memories, native equations or API calls are changed.
