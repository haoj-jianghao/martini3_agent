# Martini harness (LangChain + LangGraph)

Builds a Martini 3 coarse-grained GROMACS model of **one molecule** from its SMILES, without Claude Code or Codex. LangGraph decides which step runs next, and LangChain agents on OpenRouter make the chemical decisions (mapping, bead types). Every deterministic calculation and check is done by `martini_harness.core`, Python code copied from the `build-martini-agent` skill (v16.2) on 2026-11-18 and maintained here. The harness is one self-contained package: it does not use the skill at run time and is not synced with it.

A file-by-file explanation of the code is in [`martini_harness/README.md`](martini_harness/README.md). [`docs/flow_of_information_CHXO.pdf`](docs/flow_of_information_CHXO.pdf) follows one CHXO run through the code step by step (with file and line numbers), describes the LangGraph nodes, state and routing, the offline index build and every Python file, and has a debugging guide; rebuild it with `python docs/build_flow_pdf.py` after code changes. The current plan and its status are in [`docs/plan_evidence_records.md`](docs/plan_evidence_records.md).

## Status (2026-11-22)

**What the harness does without a model** (default settings):
- **Research:** opens and annotates the references a molecule needs (`design research`).
- **Partitions:** builds candidate partitions by exact-cover search over beads from reference models. It ranks them: within the mapping rules, then every bead with an exact precedent, then the SASA band (computed up front on the stage-4 ensemble), then rings that share atoms, then the closest analogue. It records the best one as the choice.
- **Typing evidence, per bead:** the bead size, its exact precedents and their surroundings, the type the typing order gives when precedents disagree, and the matching Table 24/25 and Alessandri Table 1 rows with citations.

**What the agents do:**
- **Mapping agent:** confirms or overrides the pipeline's choice. An override needs a recorded reason.
- **Typing agent:** records each bead's type from that evidence.
- **Repair agent:** acts only after a GROMACS test has failed with three seeds.

**Results**, 26 molecules of the logP benchmark (`runs/logp26-20261121/REPORT.md`):
- **Final run with the current code** (Haiku 5.5 and GPT-6 Luna, 26 molecules each):
  - 52 of 52 runs `execution_checked`; every partition confirmed; no repairs, no model errors, no document reads.
  - Same partition for 26 of 26 molecules, same topology for 24.
  - Cost $0.30 (Haiku, 5.4 model calls per molecule) and $0.37 (Luna, 12.5).
- **The two differences:**
  - PACT's terminal ethyl bead, settled afterwards by counting only precedents with the same surroundings.
  - BZAC's benzylic bead, which has no exact precedent and is left to the agent's judgment.
- **Water/octanol logP** of the Luna models (22 molecules with an auto-martini3 result; `runs/logp26-20261121/fe/`, REPORT.pdf):
  - MAE 0.52 log units (R² 0.79), against 0.99 (R² 0.64) for auto-martini3 with the same protocol.
  - Luna is closer to experiment for 14 of 22 molecules.
  - The runs used 40 fs, checked against 20 fs on PIPL.

**Mapping without an agent, larger molecules** (`runs/drug_mapping-20261122/REPORT.md`, 11 drug-like molecules with
OPLS-lite topologies):
- 4 have an all-exact P1 (paracetamol, aspirin, caffeine, diphenhydramine).
- The rest need 1–5 beads without a precedent; transfluthrin and the steroid core of dexamethasone are mostly rule-based.

**Against other mapping tools:**
- **auto-martini3** (9 drugs; same file): splits amide and ester groups, which the harness rules refuse, and never
  shares ring atoms; partitions identical for 2 molecules.
- **Martini-Mapper** (all 37 molecules; `runs/mapper_compare-20261122/REPORT.md`):
  - same partition for 8 of 37;
  - beads with a precedent: 82 %, against 90 % for the harness;
  - 6 molecules break harness rules (5-atom beads, a split ester, lone atoms).

**Open:**
- **Finalize-only failures:** a validation check that fails only at finalize does not reach repair.
- **Rationale vs recorded type:** nothing checks that a recorded type agrees with its rationale (one slip seen).
- **Provenance:** the provenance file (step 2 of the plan) is not written yet.

## How it works

```
START → preflight → intake → research → mapping → mapping_gate → typing → typing_gate
      → bonded_build → test → finalize → report → END
```

| Node | Kind | What it does |
| --- | --- | --- |
| `preflight` | code | Checks that the supplied AA topology exists |
| `intake` | code | Prepares the molecule with `cgbuild.cmd_input` and runs the initial model-catalog search through `design.cmd_init` |
| `research` | code (default) or agent | `research: pipeline` (default since 2026-11-21): `design research` works without a model: it opens the sources of the projected partitions, the rung-1 sources of their beads and the closest other hits, annotates each with the reason, passes their bead views on, and **records the best-ranked partitions (at most two) and chooses the first**; the mapping agent then confirms or overrides that choice with a reason. `research: agent` (config key or `cli run --research agent`): an agent reviews ranked hits, opens, matches and annotates references and returns an evidence summary |
| `mapping` | agent | Confirms or overrides the partition the research step chose (an override needs a reason of at least 40 characters), or, with `research: agent`, records and chooses candidates. Sees the projected partitions with their SASA (`design propose`); `candidate` refuses partitions that break the mapping rules |
| `mapping_gate` | code | Is a candidate chosen? If not, mapping runs again (up to `gate_retries`) |
| `typing` | agent | `bead` for every bead of the chosen candidate, `note`, `check`. Its task message carries, per bead, the size, the rung-1 precedents (when they disagree: each type's count, how many have the same surroundings, the partition's source, and the type the order gives: most precedents with the same surroundings, then the source as tie-break), and the matching Souza SI Table 24/25 and Alessandri Table 1 rows with citations (`design evidence`) |
| `typing_gate` | code | `design.cmd_check`; if incomplete, typing runs again with its output |
| `bonded_build` | code | `cgbuild` stages `bonded` and `build`; reads `static_checks.json` |
| `test` | code | `cgbuild` stage `test` (GROMACS); reads `execution.json`. A failure is run again with `random_seed` + 1 and + 2 before repair (`test/retries.json`); a pass with a later seed continues, flagged as marginal stability |
| `repair` | agent | After a failed static check, or a test failed with three seeds (at most `max_repair_cycles`): changes mapping, sites or beads, then back to `typing_gate` |
| `finalize` | code | `cgbuild` stage `finalize`, `multi_seed_check.check`, `sasa_check.check` |
| `report` | model | Final message from the run's records only |

The core functions are called directly in the harness process (`runner.call`), not as scripts. What they print becomes the tool result; a refused decision becomes an `[exit N]` message the agent reads and corrects.

The method's rules are enforced by how the harness is built:
- Agents have no shell and no write tool. `design.json` changes only through the `design_*` tools, which call `core/design.py`, so its checks and its log apply.
- Each agent node gets only the tools of its step (research cannot record candidates or beads, mapping cannot record beads, typing cannot record candidates).
- Tools are bound to one molecule folder.
- Reference tools only read inside the environment's `generation_reference_paths`.
- Each agent node has a model-call limit; repairs are counted in the graph state.

## Layout

```
config/harness.json   models per node, limits, paths (free OpenRouter models)
config/haiku.json     the same with anthropic/claude-haiku-5.5 and no fallbacks
config/luna.json      the same with openai/gpt-6-luna (20 requests a minute)
config/nemotron.json  the same with nvidia/nemotron-3-ultra-550b-a55b:free and no fallbacks
environment.json     reference paths and local executable names
references/          source documents and models; index/ holds the prepared indexes and src/ their curated inputs
martini_harness/
  core/        the science: cgbuild.py, design.py, partition.py (mapping help), refbeads.py, derive_bonded.py, d5bonded/, multi_seed_check.py,
               sasa_check.py
  build_index.py  offline preparation of references/index/*.jsonl from references/index/src/ and the Bible workbook
  prompts/     agent prompts: harness.md, rules.md, stages/*.md (the method, from SKILL.md v16.2), tasks/<node>.md
  system_prompts.py  puts a node's prompt together from prompts/
  runner.py    calls core functions from the graph and design tools, captures output, and logs results
  tools/       design_tools.py (one tool per design command), reference_tools.py, common.py (output paging)
  config.py, models.py, nodes.py, graph.py, trace.py, cli.py
tests/         test_calls.py (how calls report errors), test_index.py (prepared indexes), test_partition.py (mapping help),
               test_golden.py + golden/ (replays against saved outputs)
docs/          flow_of_information_CHXO.pdf and its builder, plan_evidence_records.md (plan and status)
runs/          one folder per run; runs/logp26-20261121/ holds the 26-molecule batch (batch.py, analyze.py, REPORT.md)
               and fe/ (logP free energies); drug_mapping-20261122/ and mapper_compare-20261122/ the mapping comparisons
```

## Setup

- Python: the `chem` conda environment (langchain 1.5, langgraph 1.2, langchain-openrouter 0.2.9, RDKit, NumPy, SciPy). Everything runs in that one interpreter; `manifest.json` records it (`software.python`) and uses it in its `reproduce` command.
- The bundled `environment.json` resolves references relative to its own directory. It uses `gmx` on `PATH` by default. Set `gromacs_command` there if your installation uses a different command or path.
- API key: `OPENROUTER_API_KEY` in the environment, or a line `OPENROUTER_API_KEY=...` in `customized_harness/.env`. Keep `.env` out of version control. If the key is exported in `~/.bashrc`, a non-interactive shell may not load it; use `bash -ic '...'` or `.env`.

## Running

From `customized_harness/`, with the `chem` interpreter:

```bash
PY=python   # after `conda activate chem`; in a non-interactive shell use the full path, e.g. ~/miniforge3/envs/chem/bin/python
FX=tests/golden/fixtures/CHXO

# Full run with Haiku 5.5 (about 70 s and 2 cents for CHXO)
# research runs as a deterministic step by default; add --research agent to use an LLM agent for it
$PY -m martini_harness.cli run --config config/haiku.json --label haiku55 \
    --id CHXO --name cyclohexanone --smiles 'O=C1CCCCC1' --aa-topology $FX/aa_topology.top

# Replay a recorded design through the graph (no LLM, no API cost): tests tools, gates and every stage
$PY -m martini_harness.cli replay --id CHXO --name cyclohexanone --smiles 'O=C1CCCCC1' \
    --aa-topology $FX/aa_topology.top --log $FX/design_log.jsonl --compare $FX/recorded_design.json

# The graph as Mermaid
$PY -m martini_harness.cli graph

# Tests (about 40 s, no LLM)
$PY -m pytest tests -q

# A batch of molecules from an index file, one lane (model, repeat) at a time, resumable
bash -ic "$PY runs/logp26-20261121/batch.py final-haiku config/haiku.json [ID ...]"
$PY runs/logp26-20261121/analyze.py final-haiku final-luna
```

The CLI exits 0 even when the run ends `blocked` or a node fails; read the status line and `harness/events.log`.

## References and distribution

Distribute `martini_harness/`, `config/`, `environment.json`, and `references/` together. The bundled reference tree includes the source topologies and mappings, simulation inputs, and documents available to the reference tools. It omits duplicate archives, tutorial trajectories, duplicate copies of the core force-field ITP, and the site-specific readiness record. Saved `runs/` are local outputs.

The prepared indexes in `references/index/` are what runs read. The three example files share one schema: one
record per reference model with its SMILES, source locator and beads (type, charge, fragment signature, member
atoms as 1-based heavy-atom positions in the record's SMILES). `mapping_support` says what a record supports:
`atom_membership` (a mapping precedent and a rung-1 source), `fragment_signature` (rung-1 only),
`bead_types_only` or `none` (with `diagnostics`).

| File | Content and use |
| --- | --- |
| [models.jsonl](references/index/models.jsonl) | 176 Martini 3 small-molecule models (`SM3:...`, memberships from their `.ndx` mapping files) and the polyply PEO building blocks (types only) |
| [ff300.jsonl](references/index/ff300.jsonl) | 74 molecules of the Martini 3.0.0 force-field files (`FF300:...`): types and charges from the ITPs; memberships from single beads, a unique Bible CGSmiles placement, or a curated mapping (the six ionic-liquid cations, from Souza SI Figure 16) |
| [bible.jsonl](references/index/bible.jsonl) | 334 Martini Bible rows (`BIBLE:rowN`): beads from CGSmiles; memberships when the fragments fit the molecule in one way up to symmetry |
| [method_evidence.jsonl](references/index/method_evidence.jsonl) | 130 method records (`MEV:...`): Souza SI section C rules, Table 24/25 rows and Alessandri 2022 Table 1 building blocks (49 rows, with bead size and an example model) with SMARTS for automatic selection, Tables 17-19 as values; each with the exact source lines and locator |
| [build_report.json](references/index/build_report.json) | Counts per file and support, and every diagnostic of the build |
| [sections.json](references/index/sections.json) | A locator for document sections, tables, and figures |

`design_init`/`design_query` search all three example files; `design_match` and `design_bead` look up bead
signatures across them; `design_open` shows a record (or an `MEV:` record with its text); `design_evidence` selects
the precedents and Table 24/25 rows for each bead. The harness trusts the supplied references. Preflight checks the
supplied all-atom topology path, and finalization records the hashes of the index files and principal simulation
inputs in `manifest.json`.

### Rebuild the indexes

Curated inputs are in `references/index/src/`: `models_catalog.jsonl` (SM3, PEO), `ff300_catalog.jsonl`,
`ff300_curated.jsonl` (hand mappings with their sources) and `method_evidence.jsonl` (IDs, locating phrases,
statements, SMARTS). The Bible workbook is read directly. After changing any of them, rebuild from the project
root (needs `openpyxl`; about 2 s). The output is deterministic, and the builder fails if a method-evidence
phrase is no longer found in its source.

```bash
python -m martini_harness.build_index            # writes references/index/*.jsonl and build_report.json
python -m martini_harness.build_index --out DIR  # writes elsewhere, for comparison
```

## Tests

- `tests/test_calls.py`: checks command and tool behavior, including parallel writes and Bible identity and bead lookups with `openpyxl` disabled.
- `tests/test_partition.py`: the cover search finds the recorded partitions (first for PHAC and PIPL) and completes molecules the greedy assembly left open (4-methylpyridine, ethylene glycol); the search is bounded by exactness and keeps covers distinct up to symmetry (diphenhydramine's all-exact partitions); the shared ring style ranks first; `design_candidate` refuses a divided ester and a lone-atom bead and accepts an exception only when it names a reference; the research step records and chooses a partition and an override needs a reason; bond caps keep 10 timesteps; a failed GROMACS test is retried with another seed; bead surroundings.
- `tests/test_index.py`: the prepared indexes rebuild byte-identically; memberships reproduce their signatures and cover every heavy atom; FF300 types come from the ITPs; method excerpts are the cited lines; the CHXO typing evidence selects the Table 24 ketone row.
- `tests/test_golden.py`: replays the recorded CHXO, PHAC and PIPL designs and compares the results with `tests/golden/expected/` (decisions, bonded terms, files and SASA exactly; GROMACS checks as pass/fail). Rewrite the expected files with `tests/golden/make_golden.py` only when a change of outputs is intended.

Replays issue one command at a time, so they do not cover what only a live model does (parallel tool calls, unverified notes, retries). Run at least one live run after changing `runner.py`, `tools/` or `core/`.

## What a run leaves

`runs/<label>-<UTC>/<ID>/` is the usual molecule folder (`input/`, `decisions/`, `bonded/`, `model/`, `test/`, `report.md`, `validation.json` and so on), plus `harness/`:

| File | Content |
| --- | --- |
| `run.json` | Configuration, models, limits, timing, final status (and the replay comparison) |
| `events.log` | One line per node |
| `state/NN_node.json` | The state update each node returned, in order |
| `trace.jsonl` | Every model call (which model answered, tokens, tool calls) and every tool call and result |
| `transcripts/NN_node.json` | Full message list of each agent node |
| `commands.jsonl` | Every core call, with exit code and output tails |
| `graph.mmd` | The compiled graph |
| `final_message.md` | The report node's message |

Also in the molecule folder: `research/` (the atomistic ensemble and SASA used for the up-front SASA of candidate partitions), `test/retries.json` (the seeds a GROMACS test was run with) and `test_attempts/attemptN/` (earlier test folders).

`decisions/design_log.jsonl` records the agent's decisions. `manifest.json` records the harness version, a hash of its code and prompts, and the hashes of the configured input files used for provenance.

## Models

`models.default` sets every node's model; `models.<node>` overrides one node, and `models.fallbacks` are tried in order when a call fails.
- `config/nemotron.json` uses `nvidia/nemotron-3-ultra-550b-a55b:free` alone: on the 26 molecules all runs `execution_checked` at $0, with about 12 model calls per molecule.
- `config/harness.json` uses free OpenRouter models (`nvidia/nemotron-3-ultra-550b-a55b:free`, then `nvidia/nemotron-3.5-lightning:free` and `google/gemma-4-31b-it:free`). Free models have per-minute and per-day limits and change often; Gemma returned 429 on 2026-11-19. `openrouter/free` is not used, because it picks a different model per call.
- `config/haiku.json` uses `anthropic/claude-haiku-5.5` ($0.10 / $0.50 per million input / output tokens on 2026-11-19) and 60 requests per minute.
- `config/luna.json` uses `openai/gpt-6-luna` (same price on 2026-11-21) at 20 requests per minute, OpenRouter's limit for new accounts. On the same harness it produced the same models as Haiku with about twice the model calls.

Calls use `request_timeout_s` (300 s), `reasoning_effort: low`, `temperature: 0`. Temperature 0 does not make runs repeat: two Haiku runs of CHXO chose different partitions.

## Limits of this version

- One molecule per command; batches run through `runs/logp26-20261121/batch.py` (one process per molecule).
- A validation check that fails only at finalize (for example the smoke-test bond check) lowers the status but does not reach repair.
- The indexes are prepared offline (`build_index.py`); runs only read them. Compare mode is outside this package.
- No figure rendering: `pdf_page_text` gives text only.
- Checkpoints are in memory (`InMemorySaver`), so a crashed run can't be resumed; the `state/` snapshots show each step.

## History

- 2026-11-16/17, v0.1: vendored copy of the skill, run as scripts in child processes, prompts cut from SKILL.md.
- 2026-11-18, v0.2: the skill's scripts became `martini_harness/core/` and are called in-process; prompts moved to `martini_harness/prompts/`; provenance is the package version and source tree hash; golden replay tests added.
- 2026-11-20: first complete LLM run (Haiku 5.5, CHXO, `runs/haiku55-20261120T034634Z`). Three bugs fixed on the way: the model timeout was passed in seconds where `ChatOpenRouter` expects milliseconds (every earlier "timeout" was 0.3 s); parallel tool calls corrupted `design.json` (core calls are now serialised); `finalize` crashed on an unverified note (`report.md` read the wrong keys).
- 2026-11-21, v0.3: self-contained distribution. `environment.json` and `references/` (original sources, derived files, `index/`) ship with the package and resolve relative to the project; the Bible is read from the prepared `references/index/bible.jsonl` (offline builder `build_bible_index.py`), so runs no longer need `openpyxl`; reference-lock verification was retired (preflight checks only the AA topology; `manifest.json` hashes the two indexes and the main simulation inputs); `python_command` was dropped from `environment.json`, and the manifest's `reproduce` command uses the interpreter that ran.
- 2026-11-21, step 1 of `docs/plan_evidence_records.md`: one schema for the reference examples (`models.jsonl`, new `ff300.jsonl`, `bible.jsonl`) with atom memberships kept where the source determines them, prepared `method_evidence.jsonl`, one builder (`build_index.py`, replaces `build_bible_index.py`); runs read prepared bead views (no per-molecule `reference_beads.json`); the typing and repair tasks carry per-bead evidence (`design evidence`); GROMACS manual removed; reference-text line numbers now follow `grep -n` (form feeds no longer count as line breaks).
- 2026-11-21, mapping help: `design propose` (core/partition.py) projects reference beads onto the target bead by bead and assembles ranked candidate partitions for the mapping task; `design_candidate` checks lone-atom, oversized and group-dividing beads at proposal time; beads are kept in the chosen candidate's order, so identical models write identical files.
- 2026-11-21, comparisons: `runs/compare-20261121` (prepared evidence: typing calls 8.4 → 3.7, no document reads), `runs/compare-20261121-mapping` and `-exact` (mapping help; PHAC and PIPL converge to one model), `runs/compare-20261121-luna` (GPT-6 Luna: same models). `docs/flow_of_information_CHXO.pdf` rebuilt for the current code, with the LangGraph design, every Python file and a debugging guide.
- 2026-11-21, research without an agent: `design research` and the `research: agent | pipeline` switch (config key, `cli run --research`).
- 2026-11-21, up-front SASA: `sasa_check.partition_sasa` scores every candidate partition before typing (ensemble cached in `research/`); ranking exact precedents → SASA → closest analogue; the research step records and chooses the best partition, the mapping agent confirms or overrides (user decisions).
- 2026-11-21, exact-cover search: candidate partitions are now covers of a bead pool (projected beads, their other exact placements, precedent-backed connected sets, open sets) found by backtracking, instead of one reference's beads completed greedily. Dry run of the 26 logP-benchmark molecules: a pipeline choice for all 26 (11 had none before), every bead exact in 25.
- 2026-11-21, after the logP-benchmark batch (`runs/logp26-20261121/REPORT.md`): bond and angle limits use a 10-timestep period (GROMACS guideline; caps T 17,765, S 26,648, R 35,531 kJ/mol/nm2, from the bead masses); a failed GROMACS test is repeated with random_seed + 1 and + 2 before repair (`test/retries.json`, flagged as marginal stability in `validation.json`); minimisation ending above 100 x emtol is noted in `report.md` as strain (information only); between equally exact partitions, rings whose beads share atoms rank first; when exact precedents disagree on a type, the evidence block gives each type's count, how many have the same surroundings and which is the partition's source, and the typing prompt says how to choose. Golden expectations regenerated (capped force constants only).
- 2026-11-21: typing order for disagreeing precedents is the most precedents with the same surroundings (all precedents when none has them), then the partition's source as tie-break; the smoke-test bond check allows max(0.02 nm, half the bond's ensemble standard deviation).
- 2026-11-22: water/octanol logP of the 22 Luna models with an auto-martini3 result (`runs/logp26-20261121/fe/`, 40 fs, benchmark protocol): MAE 0.52 vs 0.99 for auto-martini3.
- 2026-11-22: mapping-only runs of 11 drug-like molecules (OPLS-lite topologies, `runs/drug_mapping-20261122/`) and comparisons with auto-martini3 and Martini-Mapper (`runs/mapper_compare-20261122/`).
- 2026-11-22: the cover search is bounded by exactness and counts only covers distinct up to symmetry (user decision): on diphenhydramine the old cap of 500 raw covers was spent on mirror-image ring variants and missed the all-exact partitions. Of 37 test molecules (26 logP, 11 drugs) 35 keep their P1; diphenhydramine becomes all-exact, dasatinib takes a shared-atom ring; partitions more than one non-exact bead worse than the best are no longer listed (MTBE loses a flagged P2). Searches finish within the 50,000-step limit (at most about 7 s, dasatinib).
- 2026-11-22: final run of the 26 molecules with Haiku and Luna (`final-haiku/`, `final-luna/`): 52/52 `execution_checked`, same topology for 24/26; `docs/flow_of_information_CHXO.pdf` follows a run with the current defaults.
