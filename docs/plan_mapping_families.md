# Families of candidate partitions (exploration, 2026-11-24; not integrated)

Status: exploration only. Nothing here is used by the harness yet. The script is
`docs/exploration/mapping_families_atomdist.py`.

## Problem

The research pipeline's exact-cover search finds many valid partitions for drug-like molecules: 60 for
naproxen, 25 for diphenhydramine, and 500 (the cap) for dasatinib (`runs/drug_mapping-20261122/REPORT.md`). The
ranking cannot separate most of them:

- **Exact hits are cheap around rings.** Aromatic `cc` pairs have 44-297 precedents, so nearly every way of cutting
  a ring counts as exact. "Fewest non-exact beads" does not separate the ring variants.
- **SASA bands are coarse.** Most top candidates are in "pass", so weaker tie-breaks decide the order.
- **Near-duplicates fill the short list.** Naproxen P2 and P3 differ only in merging `9,10` into a neighbouring
  bead.

The goal is for the pipeline to supply **a few meaningful partitions** instead of many poorly ranked ones. The
mapping agent then only chooses among them. Grouping candidates into families is the proposed way to pick those
few.

State of the code (2026-11-24): the research step supplies the three best-ranked complete partitions within the
rules (P1-P3, `design.supplied`), and the mapping agent chooses one; it cannot record a partition of its own.
When the pipeline finds no complete partition (for example neopentane, tert-butanol, dimethyl sulfone), the
mapping node runs with the `mapping_open` profile and records its own. Families would change which three are
supplied, not this flow.

## Three kinds of family (real candidates)

| # | Molecule | Candidates | Difference | Wanted handling |
|---|---|---|---|---|
| 1 | naproxen | ranks 2, 4, 5 | the same cut (5 ring pairs, CH(CH3) apart); only which ring atoms pair differs | one family, show its best member |
| 2 | ibuprofen; lidocaine | ranks 1, 2; ranks 1, 3 | one local merge or split: `7,8 \| 9,10` or `7,8,9,10`; `3,6 \| 4,5` or `3,4,5,6` | one family, the difference shown as a named variant |
| 3 | diphenhydramine | ranks 1, 3 (and 2) | ring style: both phenyls half-shared, or both as pairs; rank 2 mixes the two | separate families; drop the mixed one |

## Leiden: considered and set aside

The idea was to partition the target first (for example with Leiden on the molecular graph), then pick the
partition with the most hits. It was set aside for four reasons:

- Leiden cannot enforce bead sizes (2-4 heavy atoms) and cannot share ring atoms.
- On graphs of 10-30 atoms, the result depends on the random seed.
- Generation is not the bottleneck: the bead pool (`partition.bead_pool`) already contains every connected set of
  target atoms with a precedent.
- The open problem is selection, not generation.

## Similarity between two partitions

### Tried: co-membership bits with Tanimoto

There is one bit per atom pair, set when the two atoms are in one bead; a shared atom contributes w_i·w_j. Two
partitions are compared with weighted Tanimoto, taking the maximum over the molecule's symmetries.

| Pair | Should be | Pair bits | Hybrid (below) |
|---|---|---|---|
| naproxen 2 vs 4 (ex. 1) | same | **0.33** | 1.00 |
| naproxen 1 vs 2 (genuinely different) | different | 0.44 | 0.62 |
| ibuprofen 1 vs 2 (ex. 2) | same | 0.76 | **0.64** |
| ibuprofen 1 vs 3 (genuinely different) | different | 0.47 | 0.60 |
| diphenhydramine 1 vs 3 (ex. 3) | different | 0.52 | 0.17 |
| diphenhydramine 2 (mixed) vs 1 / vs 3 | dropped | 0.73 / 0.72 | 0.48 / 0.48 |

- **Pair bits alone get example 1 backwards.** Two pairings of one ring share almost no pair bits.
- **The hybrid fixes that.** Pairs between two ring atoms are dropped, and each ring atom gets a role instead: bead
  size and whether the bead is shared. This builds example 1's rule into the features.
- **Tanimoto is relative, so one cutoff does not carry across molecule sizes.** One merge changes about 40% of a
  15-atom molecule's fingerprint.

### Chosen for testing: hybrid per-atom features, atom-count distance, minimum over symmetries

Features of heavy atom i in partition A, f_A(i), taken over every bead that holds i:

- if i is a ring atom: `('role', bead size T/S/R, bead shares ring atoms)`;
- for every partner j in the bead where i or j is a non-ring atom: `('pair', j, w_i·w_j)`.

The distance counts the atoms whose features differ, minimized over the automorphisms of the heavy-atom graph:

    d(A, B)     = #{ i : f_A(i) != f_B(i) }
    d_sym(A, B) = min over σ in Aut(G) of d(A, σB)

- **σB** is B with every bead relabelled through σ, weights included. Pair partners are relabelled too.
- **Aut(G)** comes from `GetSubstructMatches(mol, mol, uniquify=False)` on the heavy-atom graph. It preserves
  element, aromaticity and bonds, and ignores chirality (a partition is topological; mirror-image frames give
  the same SASA). Sizes: naproxen 1, ibuprofen 4, lidocaine 4, diphenhydramine 16.
- **d_sym is a proper distance on partitions up to symmetry.** It is invariant when the same σ is applied to both
  partitions, and Aut is a group. d_sym = 0 exactly when `partition.cover_key` treats the two as the same.
- **The minimizing σ is kept.** It lets a variant be described in its leader's numbering, for example
  `7,8 | 9,10 → 7,8,9,10`.
- **Cost:** every candidate's features are precomputed under every σ, which is |Aut| tables per candidate. For
  highly symmetric scaffolds, cap `maxMatches`, or compare multisets of features per canonical symmetry class
  (`CanonicalRankAtoms`, `breakTies=False`).

### Clustering: leader clustering in rank order

Candidates are taken in rank order. Each one joins the nearest existing leader within the cutoff (ties go to the
better-ranked leader); otherwise it leads a new family. Rank order is used rather than Butina because Butina picks
family centres by density, so a family's centre could be a worse partition than its best member.

## Results (cutoff 4 atoms)

| Pair | d_sym | Same family? |
|---|---|---|
| naproxen 2 vs 4, 2 vs 5 (ex. 1) | 0 | yes ✓ |
| ibuprofen 1 vs 2 (ex. 2) | 4 | yes ✓ |
| naproxen 2 vs 3 (merge) | 4 | yes ✓ |
| diphenhydramine 1 vs 3 (ex. 3) | 12 | no ✓ |
| diphenhydramine 2 (mixed) vs 1 / vs 3 | 6 / 6 | its own family |
| naproxen 1 vs 2; ibuprofen 1 vs 3 (genuinely different) | 6; 8 | no ✓ |

Families: naproxen 60 → 15, ibuprofen 14 → 7, diphenhydramine 25 → 14. The leading families are the intended
ones. In ibuprofen, F1 holds ranks 1 and 2, with the variant "CH(CH3) separate or merged with 7,8". In
diphenhydramine, F1 has both rings shared, F2 is the mixed style, and F3 has both rings as pairs.

Number of families by cutoff:

| Cutoff (atoms) | 0 | 3 | 4 | 5 | 6 | 8 |
|---|---|---|---|---|---|---|
| naproxen (60) | 54 | 36 | 15 | 13 | 6 | 4 |
| ibuprofen (14) | 13 | 11 | 7 | 6 | 4 | 2 |
| diphenhydramine (25) | 25 | 23 | 14 | 11 | 7 | 5 |

The workable window is 4-5. At 6, genuinely different mappings merge: naproxen 1 vs 2, and one restyled phenyl
in diphenhydramine, are both at d = 6.

## Limitations found

1. **The cutoff partly measures bead size.** Merging two 2-atom beads gives d = 4; merging a 2-atom bead with a
   3-atom bead gives d = 5. The margin to "different mapping" (6) is one or two atoms.
2. **Independent choices multiply families.** Diphenhydramine has an amine head, a linker and two ring styles.
   Two local changes together give d ≈ 8 and start a new family. Only the top 2-3 families matter for the agent.
3. **No similarity can remove inconsistent candidates.** The mixed ring style sits halfway between the pure ones
   under every fingerprint tried, so it needs an explicit filter.
4. **Some variants are worse than their leader.** Ibuprofen F1 also takes in ring merges (`5,6 | 7,8 → 5,6,7,8`,
   2 non-exact beads). Only variants about as good as their leader should be shown.
5. **SASA is computed only for the top 6 candidates.** `assemble` computes SASA for the 6 best (`n_sasa=6`), and
   `sasa_text` prints "SASA not computed (incomplete partition)" for every other candidate, even complete ones.
   A family lead from lower down needs its SASA computed, and the message is wrong.

## Proposed next steps (not started)

1. **Consistency filter.** Before clustering, drop candidates that map symmetry-equivalent regions differently.
2. **Distance in beads instead of atoms.** Count the beads in the symmetric difference, so that a merge costs the
   same whatever the bead sizes.
3. **Variant filter.** Show only variants with no more non-exact beads than their leader.
4. **Hide-and-rank benchmark to set the cutoff and the ranking.** Hide molecules that have a published Martini 3
   model from the index, run the pipeline, and record where the published partition and its family rank.
5. **Then integrate.** Supply one lead per family (P1-P3 = the leads of the top three families) and list each
   family's named variants. The agent chooses a family and, optionally, a variant, still choosing only.

Note for the benchmark: since 2026-11-24, amides that share an atom (imide, urea) keep only their carbonyls whole
(`partition._matches`). This adds candidates for ureas (carbamazepine gains a P3 that splits its urea) and gives
imides partitions at all; the family counts above were measured before that change on molecules without imides
or ureas, so they are unaffected.
