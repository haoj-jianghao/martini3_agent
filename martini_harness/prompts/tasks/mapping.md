# Your step: mapping (stage 2, items 3-8, and the virtual-site decisions of stage 4)

The task message lists partitions the pipeline projected from the most similar reference models (P1, P2, ...):
each bead names the reference bead it was carried over from ("same" = it holds exactly that bead's fragment), or
says it is the remaining atoms. Each complete partition also has its SASA: the surface of the mapped beads against
the atomistic surface on the stage-4 ensemble (pass within 5%, review to 10%, flag above). They are ordered:
complete and within the mapping rules, then every bead with an exact precedent, then the SASA band, then the
closest analogue. SASA is one criterion among several, not the deciding one. Between partitions that are
equally exact, a ring whose beads share atoms (half-weight ring atoms) is preferred to a ring cut into unshared
beads; do not override the pipeline's choice for ring style alone.

When the task says the pipeline has recorded and chosen a partition, review it: confirm it by finishing without
changing the choice, or override it where the chemistry of this molecule requires it (`design_choose` another
recorded candidate, or `design_candidate` a new one and `design_choose` it); an override needs a rationale that
says why the pipeline's choice is not used. Otherwise, record up to three candidates with `design_candidate` (the
printed `beads=` string can be used as is) and `design_choose` one with its rationale.

`design_candidate` refuses a lone-atom bead, an oversized bead or a divided chemical group; pass `exception` only
to follow a published reference that does the same, naming it. Declare hydrogens exclusions with
`design_hydrogens` and virtual sites with `design_vsite` only if needed. Do NOT record beads in this step.
Final answer: the chosen candidate id, whether it confirms or overrides the pipeline's choice, its beads as atom
lists, and one line per bead on why those atoms.
