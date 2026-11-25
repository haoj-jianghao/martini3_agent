# Your step: mapping (stage 2, items 3-8, and the virtual-site decisions of stage 4)

The task message lists the three partitions the pipeline supplies (P1, P2, P3), projected from the most similar
reference models:
each bead names the reference bead it was carried over from ("same" = it holds exactly that bead's fragment), or
says it is the remaining atoms. Each complete partition also has its SASA: the surface of the mapped beads against
the atomistic surface on the stage-4 ensemble (pass within 5%, review to 10%, flag above). They are ordered:
complete and within the mapping rules, then every bead with an exact precedent, then the SASA band, then the
closest analogue. SASA is one criterion among several, not the deciding one. Between partitions that are
equally exact, a ring whose beads share atoms (half-weight ring atoms) is preferred to a ring cut into unshared
beads; do not override the pipeline's choice for ring style alone.

The pipeline has recorded P1-P3 and chosen P1. Review them and choose one: confirm P1 by finishing without
changing the choice, or choose P2 or P3 with `design_choose` where the chemistry of this molecule requires it; that
override needs a rationale that says why P1 is not used. You choose only among P1-P3: you cannot record a
partition of your own. If none of them is defensible, choose the least bad one and say what is wrong with it in
the rationale and with `design_note` (limitation).

Declare hydrogens exclusions with `design_hydrogens` and virtual sites with `design_vsite` only if needed. Do NOT
record beads in this step.
Final answer: the chosen candidate id, whether it confirms or overrides the pipeline's choice, its beads as atom
lists, and one line per bead on why those atoms.
