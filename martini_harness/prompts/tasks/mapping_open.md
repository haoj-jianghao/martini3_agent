# Your step: mapping without supplied partitions (stage 2, items 3-8, and the virtual-site decisions of stage 4)

The pipeline's search found no complete partition within the mapping rules for this molecule, so it supplied
none. The task message shows the best incomplete partitions it found (P1, P2, ...), each bead with the reference
bead it was carried over from, and the atoms they leave uncovered. Use them as a starting point where they fit.

Record up to three partitions of your own with `design_candidate` (atoms as `1,2,3|4,5:0.5,...`, each with its
summary, pros and cons), then choose one with `design_choose` and its rationale. The output of `design_candidate`
lists, for each bead, its size, the indexed beads that hold the same fragment (types and example IDs) and the
Alessandri 2022 Table 1 building blocks of that size inside it. `design_match` lists the precedents of one
fragment.

`design_candidate` refuses a lone-atom bead, a bead larger than an R bead, or a divided chemical group (amides
that share an atom, as in an imide or a urea, keep only their carbonyls whole). These rules are probably why the
pipeline found nothing, so a partition that follows them may need a bead without an exact precedent. Pass
`exception` only to follow a published reference that breaks a rule in the same way, naming it (REF_ID); say in
the rationale why the molecule needs it, and record the departure with `design_note` (limitation).

Declare hydrogens exclusions with `design_hydrogens` and virtual sites with `design_vsite` only if needed. Do NOT
record beads in this step.
Final answer: the candidates you recorded and the one you chose, its beads as atom lists, one line per bead on
why those atoms, and any exception you used with its reference.
