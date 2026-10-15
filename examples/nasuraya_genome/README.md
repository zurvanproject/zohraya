# Nasuraya: 48-slot chromosome design

The user's 15 October 2026 instruction fixes **48 design chromosomes: 24 A/B
pairs**. This is a new Tadash software architecture, not an observed physical
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
