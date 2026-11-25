# Plan: prepared evidence records, harness pre-selection and provenance

Revised 2026-11-21 (harness v0.3.0). Replaces the first draft of the same goal.

## Goal

Make every Martini 3 mapping and bead-typing decision traceable to evidence that was delivered to the agent, and
move whatever the harness can compute out of the agent. Measures of success: fewer model calls and raw document
reads per molecule, decisions that cite resolvable evidence IDs, unchanged scientific outputs on replay.

The LangGraph stages, the partition-first/type-second order, the typing ladder, the scientific checks and the
exact/tautomer exposure checks stay as they are. Research stays in the graph until step 3.

Baseline (CHXO, Haiku 5.5, `runs/haiku55-v03-20261121T164250Z`): 16 model calls (research 3, mapping 3, typing 9,
report 1), 177k input tokens, about 2.3 ¢; typing spent 4 tool calls (2 `grep_references`, 2 `read_reference`)
finding the Souza SI Table 24 ketone row, and 6 `design_match` calls were made by agents across three nodes.

## Decisions already taken

| Topic | Decision |
| --- | --- |
| Atom numbering | 1-based heavy-atom order of the reference's own canonical SMILES (as `design.json` uses for the target). The source topology index is kept beside it for audit |
| GROMACS manual | Dropped from the bundle and from agent reach. Python writes and checks the topology; the deterministic stages need only the force-field ITPs and MDP files, which stay |
| Record structure | Every JSONL that supplies reference mapping/typing examples uses one schema (section 1.1): `models.jsonl`, `ff300.jsonl`, `bible.jsonl`. Method evidence uses the same envelope with its own body |
| FF300 | The molecules of the Martini 3.0.0 force-field files are mapping and typing examples like any other, in their own file `ff300.jsonl`. Bead types and charges come from the ITPs; atom memberships come from a unique CGSmiles placement, a single bead, or a curated mapping from a cited source |
| Evidence IDs | Existing forms are kept: `SM3:1MIMI:opt`, `FF300:solvent:DMSO`, `POLYPLY-M3:PEO`, `BIBLE:row2`; a bead is `<record id>:<bead name>` (the form `source_bead` already uses). Method records get `MEV:<source>:<item>`, for example `MEV:souza-si:T24:ketone` |
| Order | Step 1 (records + harness pre-selection) is built and checked by replay, then reviewed by the user before any live run. Step 2 (provenance) follows; step 3 measures the research node |

## Step 1: prepared records and pre-selection

### 1.1 One schema for reference examples

Three files hold one record per reference model: `references/index/models.jsonl` (SM3 and POLYPLY-M3),
`references/index/ff300.jsonl` (FF300) and `references/index/bible.jsonl` (BIBLE):

```json
{
  "id": "SM3:1MIMI:opt",
  "kind": "example_model",
  "collection": "SM3",
  "name": "1-METHYLIMIDAZOLE",
  "variant": "optimized",
  "molecule": {"smiles": "Cn1ccnc1", "formal_charge": 0, "smiles_check": "formula_match_AA_itp",
               "constitution": "...", "tautomer": "..."},
  "motifs": ["imidazole", "..."],
  "source": {"path": "references/original/small-molecules/models/itps/opt-mono/1MIMI.itp",
             "locator": "moleculetype 1MIMI in 1MIMI.itp; LIBRARY.md row 1MIMI", "sha256": "...",
             "mapping_path": "....ndx", "mapping_figure": "....png", "doi": ["10.1002/adts.202100391"]},
  "mapping_support": "atom_membership",
  "mapping_origin": "ndx",
  "beads": [
    {"id": "SM3:1MIMI:opt:N1", "name": "N1", "type": "TN1", "charge_e": 0.0, "signature": "*n(*)C",
     "members": {"1": 1.0, "2": 1.0}, "source_atoms": {"1": [1, 4]}, "neighbours": ["N2", "R3"],
     "diagnostic": null}
  ],
  "diagnostics": [],
  "notes": "..."
}
```

- `mapping_support` states what the record can support, and the tools and checks rely on it:
  - `atom_membership`: atom memberships with weights (shared atoms keep fractional weights). Supports a mapping
    precedent and rung-1 typing.
  - `fragment_signature`: verified bead signatures, but the atom memberships are not determined (the CGSmiles
    fragments fit the molecule in non-equivalent ways). Supports rung-1 typing by exact signature, not a mapping
    transfer.
  - `bead_types_only`: documented bead types and their scope, no atom mapping (PEO: EO repeat bead and OHter end
    bead, with the polyply locator). Usable as an adaptation precedent only.
  - `none`: could not be resolved; `diagnostics` says why. Served only on explicit `design_open`.
- `mapping_origin` says where the memberships come from:
  - `ndx`: a mapping file (all 176 SM3 records).
  - `single_bead`: the whole molecule is one bead, so every heavy atom belongs to it.
  - `cgsmiles_placement`: the record's CGSmiles fragments have exactly one placement on the molecule, up to
    symmetry. `place_beads` in `core/refbeads.py` already computes these placements; today only the signatures
    are kept and the memberships are thrown away. When the placements are equivalent by symmetry, the builder
    keeps the first one and records that.
  - `curated`: a mapping written by hand into `src/` with the figure or text that documents it, flagged as such.
- `members` is `null` unless `mapping_support` is `atom_membership`.

The FF300 entries are the 81 molecules shipped inside the Martini 3.0.0 force-field files: 58 solvents, 18 ions
and 5 nucleobases. A CG ITP lists beads, types, charges and bonded terms, but not which atoms each bead holds, so
the memberships come from elsewhere. Measured on 2026-11-21 (to be confirmed by the builder):

| FF300 group | Count | Memberships from |
| --- | --- | --- |
| Single-bead molecules | 25 | `single_bead` |
| Multi-bead, with a Bible CGSmiles | 43 | `cgsmiles_placement`: 33 have one placement, 10 more are symmetry-equivalent; all 43 are determined |
| Imidazolium ionic liquids (MIM, EIM, BIM, OIM, DIM) and trihexyl(tetradecyl)phosphonium (PHO) | 6 | `curated` from Souza SI section on IL models (souza2021-si.txt lines 2528–2553) and Supplementary Figure 16 |
| Nucleobases (ADEN, CYTO, GUAN, THYM, URAC) | 5 | `curated`, but the source that documents their mapping is not in the bundle; it must be added, otherwise `bead_types_only` |
| Heptanal (HPA), 9,12-octadecadiene (OCD912) | 2 | `curated` if a source is found (none in the bundle so far), otherwise `bead_types_only` |

The builder also checks that the bead types and charges a CGSmiles string gives agree with the ITP, and records
any disagreement in `diagnostics`; the ITP wins.

The same placement rule applies to the Bible. Of its 315 CGSmiles rows, about 259 have one placement or only
symmetry-equivalent ones and become `atom_membership`; the rest (about 46) stay `fragment_signature`, and 10
cannot be placed (`none`). The builder's report gives the exact counts.

### 1.2 Method evidence

`references/index/method_evidence.jsonl`, same envelope (`id`, `kind`, `source`, `diagnostics`):

```json
{
  "id": "MEV:souza-si:T24:ketone",
  "kind": "table_row",
  "stage": "typing",
  "source": {"path": "references/derived/souza2021-si.txt", "locator": "Supplementary Table 24, line 1526",
             "sha256": "..."},
  "applies_to": {"smarts": ["[#6][CX3](=O)[#6]"], "bead_size": ["R", "S", "T"]},
  "statement": "ketone: default bead type N5a",
  "excerpt": "<exact text of the row from the source file>",
  "diagnostics": []
}
```

First set:
- Souza SI section C1 (partitioning rules) and C2 (proximity rules 1–4): `kind: method_rule`, one record per rule.
- Souza SI Tables 24 and 25: one `table_row` per chemical group, each with SMARTS so the harness can select it.
- Souza SI Tables 17–19 (partitioning data, rung 3): one record per table with row values.
- Alessandri 2022 worked examples only where they decide a specific case (ring mapping, virtual-site choice).

The short rules that already live in `prompts/stages/*.md` stay there and get their `MEV:` IDs in brackets, so
an agent can cite them without opening anything.

### 1.3 One offline builder

`martini_harness/build_index.py` replaces `build_bible_index.py` and writes all four files from curated inputs
in `references/index/src/`:

| Curated input (edited by hand) | Built file |
| --- | --- |
| `src/models_catalog.jsonl`: today's SM3 and POLYPLY-M3 catalog fields (IDs, names, SMILES, source and mapping paths, motifs, notes) | `models.jsonl` with bead views from `core/refbeads.py` (`ndx_beads`) |
| `src/ff300_catalog.jsonl`: today's FF300 catalog fields; `src/ff300_curated.jsonl`: hand mappings with their source locators | `ff300.jsonl`: types and charges from the ITPs, memberships from `single_bead`, `cgsmiles_placement` or `curated` |
| Bible workbook (`references/original/bible/src/MartiniCGSmilesDB_v6.xlsx`) | `bible.jsonl` in the common schema |
| `src/method_evidence.jsonl`: ID, kind, locator, SMARTS, statement | `method_evidence.jsonl`; the builder reads the locator from the source file, fills `excerpt` and `sha256`, and fails if the text is not found |

The builder is deterministic (sorted output, no timestamps inside records) and writes `src/build_report.json`
with record counts per `mapping_support` and every diagnostic. Runs only read the built files.

### 1.4 Runtime changes

- `design.ref_beads` reads bead views from `models.jsonl`, `ff300.jsonl` and `bible.jsonl` directly. Searches (`design_init`, `design_query`) cover all three. The per-molecule cache
  `decisions/reference_beads.json` and the runtime reconstruction of SM3 bead views go away. `refbeads.py` stays
  for the target's fragment signatures and for the builder.
- Tool results are short and carry IDs in one fixed form, `[ID]`:
  - `design_hits`: ranked records with `mapping_support` and bead count.
  - `design_open`: the record; for `atom_membership` the bead memberships, weights and types.
  - `design_match`: exact precedents as bead IDs with type, charge and `mapping_support`.
  - `design_candidate`: its result lists, per proposed bead, the exact precedents of its fragment. Mapping then
    needs no separate `design_match` calls.
- Harness pre-selection in task messages (deterministic, no tool call):
  - research: model hits (as now) plus exact and tautomer identity matches.
  - typing: after `mapping_gate`, for each bead of the chosen candidate, its fragment signature, its exact
    precedents (rung 1) and the Table 24/25 rows whose SMARTS match the fragment (rung 2), with excerpts and IDs.
    Rung 3 gets the Tables 17–19 records when no row matches.
  - repair: the same block for the beads it may change.
- GROMACS manual removed: `references/original/gromacs/` (14 MB), `references/derived/gromacs-manual-2026.3.txt`,
  its `sections.json` entry and README row, `gromacs_documentation_version` in `environment.json`, and
  `references/original/gromacs` in `generation_reference_paths`.
- `grep_references`, `read_reference` and `pdf_page_text` stay for cases that need the original text.

### 1.5 Checks for step 1 (no LLM)

- The builder run twice gives byte-identical files.
- New bead types and signatures equal today's runtime views for every SM3, FF300 and Bible record, including a
  shared-atom SM3 model and an unresolved record (`none`). A test covers both.
- Every `cgsmiles_placement` membership reproduces the bead's signature, and every FF300 record's types and charges
  equal its ITP.
- Every `MEV:` excerpt is found at its locator.
- The pre-selected typing block for CHXO contains `MEV:souza-si:T24:ketone` for B1, and the PHAC and PIPL blocks
  contain the rows their recorded designs cite.
- CHXO, PHAC and PIPL replay with the same mapping, types, bonded terms, files, SASA and validation outcomes.
  Free-text counts inside `design.json` (for example "1672 reference beads checked") may change; if they do, the
  golden expected files are regenerated after the difference is reviewed.
- `pytest tests` passes.

**Checkpoint:** the user reviews the prepared files (`references/index/*.jsonl`, `src/`, `build_report.json`) and
the pre-selected typing blocks before any live run.

Then live runs: 3 runs each of CHXO, PHAC and PIPL with Haiku 5.5, compared with 3 baseline (v0.3) runs of each.
Measured: model calls per node, document-tool calls, `design_match` calls, tokens, cost, outcome, and whether the
types and citations are the same or better.

## Step 2: provenance

`decisions/provenance.json`, written at `finalize`, answers three questions:

| Question | Record and where it comes from |
| --- | --- |
| What did the agent receive? | Per node and attempt: evidence ID, source path, locator, sha256, and what was delivered (a full record, an excerpt, or only a listing). Logged by `ToolContext.page()` for tool results (it knows which page was delivered) and by the node for pre-selected task blocks |
| What did the agent say it used? | Evidence IDs and a short rationale on `design_candidate`, `design_choose` and `design_bead`. New optional field `evidence: list[str]` on those three calls; `source_bead` stays; on `design_bead`, `MEV:` IDs replace free-text `sources`, which remain accepted |
| What did the harness verify? | Per cited ID: delivered in this node, carried forward from an earlier node, or not delivered; and for an exact transfer the signature match and `mapping_support`, for an adaptation the cited row or rule. `design.py` refuses IDs that do not resolve |

- Repair keeps earlier decisions: provenance links each accepted `design_log.jsonl` event and records revisions.
- Replay and legacy logs: citations are preserved, delivery is `unknown` (no model received anything).
- The report summarises the final mapping and each bead's evidence from `provenance.json`.

Checks: provenance separates delivered, cited and verified for a mapping choice, an exact transfer, an adapted
type and a repaired decision; replay still reproduces the golden outputs (decision-field additions reviewed).

## Step 3: the research node

With steps 1 and 2 in place, compare 3 live runs per molecule with and without the research node (research's
pre-selection moved into the mapping task message). Measure model calls and document-tool calls, and review
whether mapping rationales and typing citations still support the decisions before changing the default graph.

## Later candidates (not in this plan)

- Projected partitions: for hits with `atom_membership` that share a substructure with the target, map their bead
  memberships onto target atoms (MCS) and give them to mapping as candidate partitions.
- Removing further bundled source files, reviewed separately once the prepared lookups have passed replay.

## Status of step 1 (2026-11-21)

Built and checked by replay; waiting for the user's review of the prepared files before live runs.

- Done as planned: one example schema (`models.jsonl`, `ff300.jsonl`, `bible.jsonl`), `method_evidence.jsonl`,
  one builder (`build_index.py`), prepared views at run time, per-bead evidence in the typing and repair tasks
  (`design evidence`), `design_open` for `MEV:` records, IDs in the stage prompts, GROMACS manual removed.
- FF300: 7 compounds dropped (no mapping source); the 6 ionic-liquid cations curated from Souza SI Figure 16;
  ITP types win over Bible CGSmiles types (OCE, DISH, DXE, DISS relabelled; TXE has a 4-bead CGSmiles for a
  3-bead ITP and keeps types only; single-bead DCE and DMAD now carry their ITP types X3h and P2ah).
- Found while building: the source mapping of SM3:4NIAN (both variants) leaves the nitro-bearing ring carbon in
  no bead, so these records are `fragment_signature`; two Bible rows (94, 118) gained signatures (equivalent
  placements that swap identical beads); reference-text line numbers now follow `grep -n` (the reference tools
  and the builder counted form feeds as line breaks, so earlier citations such as "line 1564" for the Table 24
  ketone row are 38 lines off).
- Added after review: Alessandri 2022 Table 1 (49 building-block rows, `MEV:alessandri:T1:*`), same structure as the Table 24/25 rows (`row`, `applies_to` with `bead_size`); Figure 2 left out (not well defined).
- Not done: the flow PDF (`docs/build_flow_pdf.py`) still describes
  v0.3.
- Open issue: RDKit's canonical SMILES of a few fragments depends on atom order (SM3:NDMBI R06, an aromatic C
  bonded to an aliphatic C, both with bonds out of the bead). Signatures are now deterministic for a given atom
  numbering, but such a fragment can still miss a match between two molecules numbered differently.
- Replay: CHXO, PHAC and PIPL give the same mapping, types, bonded terms, files, SASA and validation; the only
  change is the text "1672 reference beads checked" → "1648" (beads with a verified signature). Golden files
  regenerated after review. 18 tests pass.

## Mapping help (2026-11-21, after the step-1 comparison)

The comparison (`runs/compare-20261121/REPORT.md`) showed typing settled by the prepared evidence and the
run-to-run variation entering at mapping. Added:
- Projected partitions (`design propose`, `core/partition.py`): each bead of the 25 most similar reference models
  with atom memberships is matched in the target (element, aromaticity, ring or chain, bonds); one placement per
  bead is chosen so that shared atoms stay shared and bonded atoms bonded. Beads that would cut an indivisible
  group are not used. Candidates start from one reference, are completed from the others, and connected leftovers
  of 1.5-4.5 heavy atoms become filler beads; they are ranked complete and rule-abiding first, then fewest beads
  without an exact precedent (user decision, 2026-11-21), then the closest analogue.
  Without an agent, the top candidates are the recorded partitions of CHXO and PHAC; PIPL's is the second.
- Proposal-time checks in `design_candidate`: lone-atom bead, bead above R size, divided carboxyl, ester, amide,
  carbonyl, nitro, nitrile, sulfonyl, sulfoxide or phosphate group; refused unless `exception` names a reference.
- Table 1 building blocks for mapping: listed per bead in the candidate output, and for leftover atoms.
- Beads are stored in the chosen candidate's order (identical models now give identical ITP files).

Next: live comparison runs of CHXO against `runs/compare-20261121`.


## Results so far and open decisions (2026-11-21)

- Haiku 5.5, ranked by exact precedents (`runs/compare-20261121-exact`): PHAC and PIPL one byte-identical model
  in 3 of 3 runs each, equal to the recorded designs; CHXO two models (P1 once, P2 twice).
- GPT-6 Luna, same harness (`runs/compare-20261121-luna`): the same models as Haiku, byte for byte; CHXO P1 twice,
  P2 once; about twice the model calls at similar cost.
- Open, waiting for the user's decision:
  1. Let the harness record the top projected partition when it is complete, within the rules and all-exact; the
     agent confirms it or replaces it with a stated reason that the gate checks.
  2. Show the precedent count of every projected bead more plainly (an agent once missed one).
  3. Refuse `design_hydrogens` that excludes the hydrogens of every heavy atom (seen once, PHAC 2026-11-20).
  4. Step 2 (provenance file) and step 3 (research node) of this plan.

## Step 3: research without an agent (implemented 2026-11-21)

`design research` (core/design.py `cmd_research`) does what the research agents did, without a model: it opens the
sources of the beads of the top projected partitions, up to two references holding each bead's fragment exactly
(rung-1 sources; atom memberships first) and the five closest other hits; annotates each with the reason it was
opened; and prints one compact block per reference (variants with identical beads collapsed), which becomes the
`evidence` passed to mapping. Selected with `research: pipeline` in the config or `cli run --research pipeline`;
the default stays `agent` until the live comparison. Evidence of the 14 analysed agent runs: research took 29 % of
model calls; its 58 opens, 57 annotations and 32 matches are lookups on the prepared records; its 4 added queries
repeated motifs the derived queries and the projections already cover; no document was read.
Live comparison (Haiku 5.5, one run per molecule, `runs/compare-20261121-research`): the same models as the
research-agent runs (CHXO P1, PHAC and PIPL the recorded designs), byte for byte; model calls 12.0 → 8, 13.7 → 8,
14.0 → 6; cost about 2.2 ¢ → 1.4 ¢. `pipeline` became the default on 2026-11-21 (user decision).

## Up-front SASA and the pipeline's choice of partition (2026-11-21, user decisions)

- The research step records the best-ranked complete, rule-abiding partitions (at most two, so the agent can add
  one) and chooses the first (`pipeline_choice`). The mapping agent confirms it or overrides it; `design_choose`
  refuses an override whose rationale is under 40 characters; the gate logs "confirmed" or "overrides".
- Ranking: complete and within the rules, then fewest beads without an exact precedent, then the SASA band, then
  the closest analogue. SASA is a second criterion and information for the agent, never the only one.
- SASA up front (`sasa_check.partition_sasa`): the stage-4 ensemble (same function, seed and frames) built once
  and cached in `research/`; each candidate mapped onto it; bead radii from the size letter of the bead's exact
  precedents when they agree, else from its heavy-atom weight. It reproduced the final SASA of earlier live runs
  exactly (CHXO P1 −6.63 %, P2 −14.28 %; PHAC −2.15 %; PIPL +3.65 %). About 1 s per molecule.
Live check (Haiku 5.5, one run per molecule, `runs/compare-20261121-confirm`): each mapping agent confirmed P1 in
one model call; 4-5 model calls and about 0.9 ¢ per molecule; models byte-identical to the earlier runs with the
same partitions.

## Exact-cover search (2026-11-21)

The greedy assembly took all beads of one seed reference and completed with others where they fitted; when the
seed's local style (ring split, chain register) did not fit, one atom was left over (11 of the 26 logP-benchmark
molecules, although reference beads containing that atom existed). Now (`core/partition.py`):
- Bead pool: the projected beads; every other placement of their fragments with the same signature; every connected
  set of 2-5 heavy atoms whose fragment has an indexed precedent; connected sets of 2-4 atoms without one (not
  exact). Beads that cut an indivisible group or break the size rules are left out.
- `cover_search`: backtracking from the most constrained atom (exact beads first) for sets of beads whose weights sum
  to one on every heavy atom; a branch whose open atoms form one allowed bead is also closed with that filler bead
  (keeps half-shared fillers such as CHXO's recorded ring bead). Covers equal up to symmetry are merged.
  Since 2026-11-22 (user decision, after diphenhydramine): bounded by exactness (branches with more than best + 1
  non-exact beads are pruned, covers beyond best + 1 dropped) and only covers distinct up to symmetry are kept and
  counted; when 500 are kept a better cover replaces a worse one and the search goes on. Before, the first 500 raw
  covers (mostly mirror-image ring variants under one root choice) could hide all-exact partitions.
- Ranking unchanged in spirit: rules, exact precedents, SASA band, then fewer references, then closest analogue.
- No ring-style rule (user decision). The greedy assembly stays as the fallback when no cover exists.
Prototype findings: shared atoms were already allowed; backtracking across references completed 8 of the 11, extra
placements 1 more, precedent-backed sets 1 more, open sets the last (BZAC, one non-exact bead).
Dry run (no model calls) of all 26: a choice for every molecule, 25 with every bead exact; SASA 17 pass, 8 review,
1 flag (MTBE). Cover search: milliseconds; the up-front ensemble takes up to about 1 minute for long chains.

## Changes after the logP-benchmark batch (2026-11-21, user decisions)

- Disagreeing precedents: a prompt instruction, not a hard-coded rule. The evidence block now lists, for a bead
  whose exact precedents disagree, each type's count, how many of its precedents have the same surroundings as the
  bead (atoms one bond outside: element, aromatic, double bond) and which type the partition's own source uses; the
  typing prompt orders the choice: same surroundings, then the partition's source, then the majority, and the
  rationale names the rejected types.
- Ring style: between equally exact partitions, rings whose beads share atoms rank first (after the SASA band);
  the mapping prompt says not to override for ring style alone.
- GROMACS test: a failure is repeated with two more seeds before repair; a pass with any seed continues, flagged
  as marginal stability (CINA: the same model failed and passed by chance; the repair agent changed a good mapping).
- Strain flag: minimisation ending above 100 x emtol is flagged. Finding after implementation: in Luna pass 1, 8 of
  26 molecules (all substituted aromatics, all passing their tests) end above that limit, so the flag does not
  single out CINA. Decision: information only, a note in `report.md` (not a check in `validation.json`).
- Period limit 9 -> 10 timesteps for bond caps, angle and dihedral limits (caps from the bead masses). Golden
  expectations regenerated: capped force constants and one angle changed; no status or GROMACS result changed.

## Typing order and bond check (2026-11-21, user decisions)

- Disagreeing precedents: the order is now same surroundings, then the most precedents, then the partition's source
  only as tie-break. Reason: a bead's "partition source" is the first projected reference that placed it, not a
  deliberate choice; for GUAI it was Bible row 271 (2-methylhydroquinone, TN6a), while the library model of p-cresol,
  Bible row 192 and Alessandri Table 1 give TN6, which the user confirmed is correct for an aromatic C-OH T bead.
  The evidence now gives TN6 for GUAI and SN3a for both DGBE ether beads.
- Smoke-test bond check: |mean - b0| below max(0.02 nm, 0.5 x the bond's ensemble standard deviation)
  (`bond_mean_within_max(0.02nm,0.5sd)_of_b0_in_smoke`). The fixed 0.02 nm failed BZAC by chance: its floored bond
  b2 (k 700, std 0.06 nm) gave -0.007 nm and -0.028 nm in byte-identical topologies. With the new limit (0.030 nm
  for b2) all seven BZAC runs pass; the golden models pass unchanged.


## Status 2026-11-22

Done:
- **Step 1:** prepared records; evidence per bead with sizes, surroundings and table rows.
- **Step 3:** research by the pipeline, the default.
- **Mapping help:** cover search, up-front SASA, the pipeline records and chooses the partition, the agent confirms or overrides.
- **Typing order** for disagreeing precedents: the most precedents with the same surroundings, then the partition's source as tie-break.
- **Test robustness:** seed retries before repair; 10-timestep limits; a bond check scaled to each bond's spread; the strain note in `report.md`.

Final run with the current code, 26 molecules × (Haiku, Luna) (`runs/logp26-20261121/final-*`):
- 52/52 `execution_checked`; same partition 26/26, same topology 24/26.
- Afterwards the majority step was changed to count only precedents with the same surroundings. That settles PACT (TC2, as Haiku chose), leaving BZAC's bead without an exact precedent as the only difference.

Since the final run (2026-11-22):
- **Water/octanol logP** of the Luna models (`runs/logp26-20261121/fe/`): MAE 0.52 vs 0.99 for auto-martini3 on 22 molecules.
- **Cover search** bounded by exactness and counting covers distinct up to symmetry (see the exact-cover section).
- **Mapping-only tests** on 11 drug-like molecules, and comparisons with auto-martini3 and Martini-Mapper
  (`runs/drug_mapping-20261122/REPORT.md`, `runs/mapper_compare-20261122/REPORT.md`): the harness's partitions hold
  more beads with an exact precedent (90 % vs 82 % for Martini-Mapper) and keep chemical groups whole.
- **Gap:** for molecules with little reference coverage (transfluthrin, the dexamethasone core), the partition is
  rule-based: open beads up to 4 atoms, sized by heavy-atom count, typed at rung 2/3.

Open:
- **Step 2:** the provenance file.
- **Finalize-only failures:** a validation check that fails only at finalize does not reach repair.
- **Rationale vs recorded type:** no check that a recorded type agrees with its rationale (one slip seen).

## Mapping: the agent chooses, the pipeline supplies (2026-11-24, user decisions)

- **Choose only.** The research step supplies the three best-ranked complete partitions within the mapping rules
  (P1-P3, `design.supplied` / `record_supplied`) and chooses P1; `design propose` shows the same three. The
  mapping agent confirms P1 or chooses P2/P3 (reason of at least 40 characters). It has no `design_candidate`, and
  `design.py` refuses `candidate`, and `choose` of a candidate the pipeline did not supply, once P1-P3 exist.
  Repair has no `design_candidate` either. With `research: agent`, `design shortlist` records P1-P3 after the agent.
- **No supplied partition.** When the search finds no complete partition within the rules, the mapping node runs
  with the profile `mapping_open` (`prompts/tasks/mapping_open.md`; tools of mapping plus `candidate`): it records
  up to three partitions of its own, checked by the same rules, and chooses one. Research blocks only when its
  command fails. Repair stays for failed builds and tests.
- **Imides and ureas.** Amides that share an atom keep only their carbonyls whole (`partition._matches`), as in the
  published imide models (SM3:CAFF; thymine and uracil in `martini_v3.0.0_nucleobases_v1.itp`); a lone amide stays
  indivisible. An N-H imide therefore keeps one C(=O)NH bead and puts the other C=O alone or with its neighbour.
  Glutarimide, barbiturates, hydantoins and thalidomide get partitions (without exact precedents; accepted).
- **5-atom branched beads.** Not added to the bead pool without an indexed precedent (user decision). Published 5-atom
  branched beads are whole small molecules (CCl4, TMA, ions; neopentane in Souza SI C1) or charged and sulfonyl
  centres (phosphonium, sulfonamides); a tert-butyl substituent is a 4-atom S bead (FF300 TBA, Bible rows 73, 327).
  Neopentane, tert-butanol and dimethyl sulfone therefore go to `mapping_open`.
- **Multi-fragment SMILES** (salts, counter-ions, mixtures) are refused at intake (`cgbuild.cmd_input`).
- **Agent-written candidates** carry `proposed_by: agent` and no bead sources or SASA (an earlier version that added
  them was reverted).
- **Families of partitions:** explored, not integrated (`docs/plan_mapping_families.md`).

Open:
- Families of candidates and the hide-and-rank benchmark (`docs/plan_mapping_families.md`).
- `sasa_text` prints "incomplete partition" for complete candidates ranked below the 6 whose SASA is computed.
- No live LLM run of the `mapping_open` profile yet (tested with a stubbed agent on neopentane).

