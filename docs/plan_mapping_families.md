# Families of candidate partitions (exploration, 2026-11-24; not integrated)

Status: the bead-graph distance chooses the supplied partitions since 2026-11-26 (section "Integrated"); the rest
is exploration. The scripts are
`docs/exploration/mapping_families_atomdist.py` (atom-count distance, below) and
`docs/exploration/mapping_families_beadgraph.py` (bead-graph distance, section "Bead-graph distance", 2026-11-26).

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

State of the code (2026-11-24; superseded on 2026-11-26, section "Integrated"): the research step supplies the three
best-ranked complete partitions within the rules (P1-P3, `design.supplied`), and the mapping agent chooses one; it cannot record a partition of its own.
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

## Bead-graph distance (exploration, 2026-11-26)

Script: `docs/exploration/mapping_families_beadgraph.py`. It addresses limitation 1: a merge costs 1 whatever the bead
sizes. Atom numbers below are atom ids (1-based position in `input/atomistic.sdf`; heavy atoms come first).

### Definition

- **Bead graph.** One node per bead; two beads are joined when a covalent bond runs between them or they share an
  atom (half-shared ring atoms).
- **Regions.** Each ring system (fused rings are one) and each acyclic chain, with the groups of
  `partition.INDIVISIBLE` (carboxyl, amide, ...) carved out of chains as regions of their own. Ibuprofen: ring
  `5,6,7,8,14,15`; chains `1,2,3,4`, `9,10` and the carboxyl `11,12,13`. Without the carving, `9,10` and `11,12,13`
  share one chain region and the matcher pairs them with each other.
- **Bead type** = the set of region instances the bead touches. **Bead label** = (size T/S/R, shares atoms).
- **Correspondence A → B.** Each A bead goes to one B bead or stays unmatched: 1:1 when the types are equal, or as a
  merge, when several connected A beads together have exactly the B bead's atoms (weights summed).
- **Distance** = merges (k beads into one count k − 1) + unmatched beads of A and of B + bead edges in only one graph
  (A's edges taken through the correspondence) + 1:1 pairs whose labels differ. Minimised over correspondences, over
  Aut(G) (B relabelled through σ) and over both directions (a split is a merge from B to A).

### Results

| Pair | Should be | Distance | What differs |
|---|---|---|---|
| ibuprofen 1 vs 2 | same | 1 | merge `7,8` + `9,10` → `7,8,9,10` |
| lidocaine 1 vs 3 | same | 1 | merge `3,6` + `4,5` → `3,4,5,6` |
| naproxen 2 vs 3 | same | 1 | merge `8,14` + `9,10` → `8,9,10,14` |
| naproxen 2 vs 4, 2 vs 5 (ex. 1) | same | 2 | ring re-pairing: one bead edge lost, one gained |
| diphenhydramine mixed (rank 2) vs 1 / vs 3 | dropped | 4 / 4 | one phenyl restyled: 3 labels, 1 edge |
| diphenhydramine 1 vs 3 (ex. 3) | different | 8 | both phenyls restyled: 6 labels, 2 edges |
| naproxen 1 vs 2; ibuprofen 1 vs 3 | different | 10; 10 | unmatched beads and edges |

Same ≤ 2, different ≥ 8: a wider margin than the atom-count distance (4 vs 6 atoms). Naproxen 2 vs 4 is not 0:
the shared ring bond 6–16 joins two beads of the side-chain ring in rank 2 (`6,7`, `15,16`) and two beads of the
methoxy ring in rank 4 (`5,6`, `16,17`). On bare naphthalene the two are mirror images; naproxen's substituents
(C3, C8) break that mirror, so no automorphism relates them.

Families (leader clustering in rank order):

| Cutoff | naproxen (60) | ibuprofen (14) | lidocaine (15) | diphenhydramine (25) |
|---|---|---|---|---|
| 1 | 24 | 7 | 9 | 9 |
| 2 | 15 | 5 | 7 | 9 |
| 3 | 11 | 5 | 5 | 6 |
| 4 | 6 | 3 | 4 | 5 |
| 5 | 4 | 2 | 3 | 4 |

At cutoff 2: naproxen F2 holds ranks 2–5 and rank 1 leads F1; ibuprofen F1 holds ranks 1 and 2, and rank 3 leads F2;
lidocaine F1 is {1, 3}; diphenhydramine F1 (both rings shared), F2 (mixed) and F3 (both rings as pairs) are separate.
The workable window is 2–3.

### What was tried on the way

- **Tanimoto over pair bits, maximised over Aut(G).** No pair improved: naproxen has |Aut| = 1, and candidates are
  already unique up to symmetry (`cover_key`), so no two are symmetry images of each other.
- **Bead graph with strict types, one-to-one, edge Tanimoto.** Naproxen 2 vs 4 = 0.80 and 1 vs 2 = 0.21, but ibuprofen
  1 vs 2 = 0.22: the merged bead `7,8,9,10` touches ring and chain, matches no bead, and loses its edges. Diphenhydramine
  1 vs 3 = 0.83: a phenyl as three shared beads and as three pairs are both a triangle of beads, so ring style needs
  the labels.
- **Merges without the atom check** let unrelated beads merge (naproxen `1,2` + `3,17` → `1,2,3`; atom 17 is not in
  it), which shortened different pairs from 10 to 6.
- **Forcing identical beads and atom merges** (no search for them) overestimated 173 of naproxen's 1770 pairs, 60 of
  them at distance ≤ 5 (rank 23 vs 25: 6 instead of 2, a forced merge where a ring re-pairing was cheaper). It is kept
  only as a starting bound.

### Search and cost

Exact branch and bound. What makes it fast enough:

1. Symmetry outside the search: B is relabelled once per σ, and a 1:1 match must stay in the same region instance
   (this phenyl, not the other one).
2. σ that give the same problem are run once: σ and σ' are equivalent when σ'(B) = t(σ(B)) for a t that leaves A
   unchanged.
3. One bound shared across σ, and a lower bound that counts a 1:1 label mismatch at once (it costs ≥ 1 either way).
4. For clustering, cutoff + 1 is the starting bound: only "d ≤ cutoff" is decided exactly.

Clustering at one cutoff: naproxen 0.6–1.1 s, diphenhydramine 0.4–0.6 s, ibuprofen and lidocaine < 0.05 s. All
pairs without a cap (`--all`): naproxen 19 s, diphenhydramine 44 s. Verified against an exhaustive search: 0
differences over all pairs of ibuprofen, lidocaine and naproxen; diphenhydramine has no exhaustive reference (too slow).

### Open points

- **The mixed ring style still sits between the pure styles** (4 from each, which are 8 apart): it still needs the
  consistency filter (next step 1).
- **One-to-one ring matches are not checked against atoms**, by design: ring re-pairings (naproxen 2 vs 4) have no atom
  correspondence. Only merges are.
- **Cost grows with symmetric scaffolds.** Two equivalent phenyls are handled; a molecule with more equivalent rings
  has not been tried.
- **The cutoff is set from four molecules.** The hide-and-rank benchmark (next step 4) should set it.

## Integrated (2026-11-26)

`martini_harness/core/families.py` holds the bead-graph distance (capped search only) and `supply(mol, cands, n,
cutoff)`. `design.supplied(ranked, mol, md)` now returns, among the complete partitions within the rules:

- the leaders of the first three families, cutoff 2 bead edits (user decision), found by walking the candidates in
  rank order and stopping at the third leader, so the cost does not grow with the number of candidates;
- when there are fewer than three families, the best-ranked variants in the remaining slots, whatever their family
  (user decisions: always three when there are three candidates; by rank, not family 1's variants first), each
  marked "variant in family N".

Each supplied partition carries `family` and `family_leader` (shown by `propose`, stored on the candidate in
`design.json`; the rationale says how many distinct families were supplied). A supplied partition ranked below the
6 for which `assemble` computes SASA gets its SASA computed in `supplied` (limitation 5 above). The mapping prompts
(`tasks/mapping.md`, `stages/2_mapping.md` item 6) explain families and variants.

On the 2026-11-22 drug run (11 molecules): `propose` takes 0.3-2.4 s per molecule; the family search at most 0.22 s
(carbamazepine). The supplied set changes for 6 of 11: ibuprofen P2 rank 3, P3 rank 4; lidocaine P3 rank 4; naproxen
P3 rank 6; aspirin P2 rank 3, P3 rank 5; dexamethasone P3 rank 4; caffeine P2 rank 11 (P3 a variant of family 1);
paracetamol: 2 families, P3 a variant of family 1.

Known effect of leader clustering: it is not transitive. Naproxen rank 4 joins family 2 (distance 2 from rank 2), but
rank 6 (rank 4's ring pairing plus the merge `7,8` + `9,10`) is distance 3 from rank 2 and leads family 3. P3 is then
a variant of a variant of P2, not a different mapping.

## Proposed next steps (not started)

1. **Consistency filter.** Before clustering, drop candidates that map symmetry-equivalent regions differently.
2. **Distance in beads instead of atoms.** Count the beads in the symmetric difference, so that a merge costs the
   same whatever the bead sizes. Explored as the bead-graph distance above (2026-11-26).
3. **Variant filter.** Show only variants with no more non-exact beads than their leader.
4. **Hide-and-rank benchmark to set the cutoff and the ranking.** Hide molecules that have a published Martini 3
   model from the index, run the pipeline, and record where the published partition and its family rank.
5. **Then integrate.** Supply one lead per family (P1-P3 = the leads of the top three families) and list each
   family's named variants. The agent chooses a family and, optionally, a variant, still choosing only. The first
   half is done (section "Integrated"); listing each family's variants is not.

Note for the benchmark: since 2026-11-24, amides that share an atom (imide, urea) keep only their carbonyls whole
(`partition._matches`). This adds candidates for ureas (carbamazepine gains a P3 that splits its urea) and gives
imides partitions at all; the family counts above were measured before that change on molecules without imides
or ureas, so they are unaffected.
