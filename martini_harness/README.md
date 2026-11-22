# `martini_harness`: code reference

This explains every part of the package: what it is for, its main objects and functions, what it reads and writes, and why it is built that way. For setup and running, see `../README.md`.

## How the pieces fit

```
cli.py ──► graph.py ──► nodes.py (Pipeline) ──┬─► runner.call ──► core/ (cgbuild, design, multi_seed_check, sasa_check)
                                              ├─► tools/ (design_tools ─► runner.call; reference_tools, common)
                                              ├─► system_prompts.py ──► prompts/
                                              ├─► models.py (ChatOpenRouter per node)
                                              └─► trace.py  (callback → harness/trace.jsonl)
config.py is read by all of them.
```

There are two layers:
- **Science layer, `core/`:** the method's deterministic code, copied from `build-martini-agent` v16.2 `scripts/` on 2026-11-18 and maintained here. The orchestration layer never reimplements chemistry, bonded terms or checks.
- **Orchestration layer:** the rest of the package. It decides which step runs next, gives agents tools, and records what happened.

Graph stages and design tools call the scientific commands in-process through `runner.call`.

---

## `__init__.py`

Holds the docstring and `__version__` (`0.3.0`). Nothing else is imported at package level, so `python -m martini_harness.cli` loads LangChain only when it is used.

---

## `config.py`

Loads a harness config (default `config/harness.json`) and the environment file named by `martini_env`. Both shipped configs use the project-local `environment.json`.

**`HARNESS_ROOT`**: the `customized_harness/` folder. Relative paths in the config are resolved against it.

**`HarnessConfig`** (dataclass):

| Field / method | Meaning |
| --- | --- |
| `path` | Absolute path of the config file in use |
| `raw` | The parsed config (models, limits, flags) |
| `martini_env`, `env` | Path and content of the bundled `environment.json`. Reference paths resolve relative to its folder |
| `project` | The folder of `environment.json`. Every reference path, and every `--source PATH:LOCATOR`, is relative to it |
| `runs_root` | Where run folders are created (`customized_harness/runs`) |
| `prompts` | `martini_harness/prompts/` |
| `model_for(node)` | The node's model from `models.<node>`, or `models.default` |
| `fallbacks` | `models.fallbacks`, tried in order when a model call fails |
| `limit(key)` | An integer from `limits` (for example `research_model_calls`, `gate_retries`) |
| `reference_roots()` | `generation_reference_paths` of `environment.json` as absolute paths: the only folders agents may read |

**`load_config(path=None)`** is the only place that reads configuration, so another model set only needs `--config` (as `config/haiku.json`, `config/luna.json` and `config/nemotron.json` do). The config key `research` (`pipeline`, the default, or `agent`) selects how the research node works; `cli run --research` overrides it.

---

## `runner.py`

Runs scientific commands for the graph and design tools.

**`configure(cfg)`** calls `cgbuild.configure(martini_env, gmx_threads)` at startup. It sets the force-field paths, GROMACS command and the prepared index files (`indexes`). It clears the cached indexes when configuring a pipeline and removes `OMP_NUM_THREADS` so GROMACS can use the requested `-ntomp`.

**`call(moldir, fn, *args, tag, **kwargs) -> CallResult`** runs one core function:
- **Output:** what `fn` prints is captured with `contextlib.redirect_stdout`; the core functions report by printing.
- **Errors become codes:** `DesignError` (a refused decision, normally exit 2), `cgbuild.StageError` (a stage that cannot continue, exit 1) and `SystemExit` become a non-zero code with their message. Any other exception also does, with its traceback, so a bug in the core code shows up in the result and in the log instead of ending the run.
- **One call at a time:** a process-wide lock (`_CALL_LOCK`) serialises all calls. A model may request several tools in one turn, and LangChain runs those in parallel threads. Without the lock, `redirect_stdout` (which is process-wide) mixed the outputs, and `design.py` commands, which each read, change and rewrite `design.json`, corrupted the file (found in the first Haiku 5.5 run, 2026-11-20). `tests/test_calls.py::test_parallel_tool_calls_keep_design_json_valid` covers it.
- **Logging:** every call is appended to `<moldir>/harness/commands.jsonl` with its start time, wall time, tag, function, arguments, exit code, the last 800 characters of output and the last 2,000 of the error.

**`CallResult`** holds `code`, `stdout`, `stderr` and `call` (the function's name).
- `ok` is true when `code == 0`.
- `text()` joins output and error. On failure it starts with `[exit N]`. Agents are told in `prompts/harness.md` to read that prefix as a refusal and correct their arguments.

---

## `core/`

The science. `core/__init__.py` records where it came from.

| Module | What it does | Called by |
| --- | --- | --- |
| `cgbuild.py` | Stages `input` (SMILES, conformers, frozen AA topology), `search`, `bonded`, `build` (files, static checks), `test` (GROMACS em, eq1, eq2, smoke), `finalize` (`validation.json`, `manifest.json`, `report.md`); `COMMANDS` maps stage names to `cmd_*` functions; `harness_provenance()` Also: `examples()` and `method_evidence()` load the prepared indexes; `classify` builds `validation.json` (the smoke-test bond check allows max(0.02 nm, 0.5 × the bond's ensemble standard deviation), `BOND_DEV_MIN_NM`, `BOND_DEV_SD_FRACTION`); `write_report` adds an information note when minimisation ends above `EM_STRAIN_FACTOR` (100) × its target; `cmd_test` takes a `seed`. | `nodes.intake`, `Pipeline.stage` |
| `design.py` | The design record: `cmd_init`, `atoms`, `hits`, `query`, `open` (also `MEV:` records), `annotate`, `match`, `research` (the pipeline's research step: opens and annotates references, records the best partitions and chooses one), `propose` (ranked candidate partitions with SASA), `evidence` (per bead: size, precedents, surroundings when they disagree, the type the typing order gives, matching table rows), `candidate` (refuses rule-breaking partitions unless an `exception` names a reference), `choose`, `hydrogens`, `vsite`, `bead`, `note`, `show`, `check`. Each change is saved to `decisions/design.json` and appended to `decisions/design_log.jsonl` with the file's hash. `namespace(cmd, moldir, **kw)` builds a command's arguments from the parser's defaults | `tools/design_tools.py` |
| `partition.py` | Mapping help: rule checks of a partition (`issues`); bead-by-bead projection of reference models onto the target (`projections`); the bead pool (projected beads, their other exact placements, connected 2–5-atom sets with an indexed precedent, 2–4-atom sets without one: `bead_pool`, `bead_maker`); exact cover with weights by backtracking, closing a branch with a filler bead when the open atoms form one allowed bead (`cover_search`: backtracking bounded by exactness, keeping covers within one non-exact bead of the best and distinct up to symmetry, `cover_key`); ranked candidates (`assemble`: exact precedents, SASA band, fewer references, closest analogue; the greedy `_greedy` as fallback); Table 1 building blocks inside a set of atoms | `design.py` (`propose`, `research`, `candidate`) |
| `refbeads.py` | Fragment signatures, and the parsers that turn mapping files, CGSmiles and ITPs into bead views | `design.py` (signatures), `build_index.py` |
| `derive_bonded.py`, `d5bonded/` | The D5 bonded-term method (OPLS + GBSA-OBC2 conformer ensembles and Hessians in NumPy). `d5bonded/terms.py` keeps every vibration at a period of at least `MIN_PERIOD_STEPS` = 10 timesteps of 20 fs: bond caps from the reduced mass of the two beads (T 17,765, S 26,648, R 35,531 kJ/mol/nm² for same-size pairs; 20,000 / 30,000 / 40,000 with 9 steps until 2026-11-21), angle and dihedral limits from the same period; bonds below 700 are raised to 700 | `cgbuild` stage `bonded`; `derive_ensemble` also for the up-front SASA |
| `multi_seed_check.py` | `check(out, moldirs)`: the model under four seeds | `nodes.finalize` |
| `sasa_check.py` | `check(out, moldirs)`: SASA of the built model against the atomistic ensemble; `partition_sasa(md, partitions, sizes)`: the same measure for candidate partitions before typing (ensemble cached in `research/`) | `nodes.finalize`; `design.py` (`propose`, `research`) |

Changes made when the scripts were moved in: `die()` raises `DesignError` instead of calling `sys.exit`; `cgbuild` reads its environment in `configure()` instead of at import; the agent-session binding (`MARTINI_MOLDIR`, `bound_check`) was dropped, because the tools are bound to one folder; provenance is `harness_provenance()` (package version and a SHA-256 over the `.py`, `.md` and `.json` files of `martini_harness/`) instead of the skill tree hash. The modules still run from the command line (`python -m martini_harness.core.design ...`) with `MARTINI_ENV` set.

Known fix after the move: `write_report` read unverified notes as `{text, location, later_status}`, while `design.py note --unverified` stores `{statement, label}`. Any run with an unverified note crashed at `finalize` (the skill has the same bug). It now prints `statement (label)`.

### Reference data during a run

- `cgbuild.examples()` loads `models.jsonl`, `ff300.jsonl` and `bible.jsonl` once per configuration: records by id,
  and lookup tables by constitution, canonical tautomer and bead signature. `cgbuild.method_evidence()` loads
  `method_evidence.jsonl`.
- `cgbuild.cmd_search` matches the queries (SMARTS, motif tags) against every example record;
  `design.ranked_hits` sorts the hits by Morgan similarity. Exact and tautomer identity matches set
  `reference_exposed`.
- `design.precedents(signature)` is a table lookup; `design_match`, `design_candidate` and `design_bead` use it.
- `design evidence` (`cmd_evidence`) prints, per bead of the chosen candidate, its precedents and the method
  records whose `applies_to` holds (`core` SMARTS inside the bead, `all` for every bead atom; tested on the
  heavy-atom graph); with no Table 24/25 row it names the Table 17/18/19 record for the bead size. The typing and
  repair nodes put this into their task messages.
- `decisions/analogue_search.json` records the hits, identity matches, annotations and the index-file hashes.

---

## `system_prompts.py` and `prompts/`

Each agent node's system prompt is put together from text files:

| File | Content | Goes to |
| --- | --- | --- |
| `prompts/harness.md` | How the pipeline works: `design_*` tools, reference tools and citations, `[exit N]`, `more_output`, no shell | every node |
| `prompts/tasks/<node>.md` | What this step does, what it must not do yet (for example no beads during mapping), what its final answer contains | that node |
| `prompts/rules.md` | Rules, method and experiment boundary | every node except report |
| `prompts/stages/*.md` | The method's stages (`2_mapping`, `3_typing`, `4_bonded`, `5_check`, `6_deliver`), taken from SKILL.md v16.2 | per `NODE_STAGES` |

**`NODE_STAGES`**: research gets 2; mapping 2 and 4; typing 3; repair 2–5; report 6.

**`system_prompt(prompts_dir, node)`** joins harness, task, "# Method", rules and stages. It raises `KeyError` for an unknown node and `FileNotFoundError` for a missing file. Prompt sizes on 2026-11-21: research 13.1k characters, mapping 15.4k, typing 10.3k, repair 19.2k, report 3.7k.2k characters, mapping 13.0k, typing 8.7k, repair 16.9k, report 2.8k.

To change what a step does, edit its task file; to change the method, edit `rules.md` or a stage file.

---

## `tools/common.py`

State shared by the tools of one run, and paging of long outputs.

- **`ToolContext(cfg, moldir, max_chars)`** binds tools to one molecule folder. Every tool factory takes it, so a tool cannot address another molecule.
- **`ToolContext.page(text)`** returns short text unchanged. Longer text (above `tool_output_chars`, default 6000) returns its first page plus a handle such as `out3`; the full text is kept in memory.
- **`ToolContext.more(handle, page)`** returns another page.
- **`more_output_tool(ctx)`** exposes `more` to agents as `more_output(handle, page)`.

---

## `tools/design_tools.py`

One LangChain tool per design command. This is how agents record decisions.

- **`run_design(ctx, cmd, **kw)`** builds the arguments with `design.namespace` (the command's defaults plus `kw`; unknown names raise `TypeError`) and calls the command's `cmd_*` function through `runner.call` with tag `design.<cmd>`. The log entry in `design_log.jsonl` is therefore the same as a command-line call's.
- **Argument schemas** (`HitsArgs`, `QueryArgs`, `RefArgs`, `AnnotateArgs`, `MatchArgs`, `EvidenceArgs`, `CandidateArgs`, `ChooseArgs`, `BeadArgs`, `VsiteArgs`, `HydrogensArgs`, `NoteArgs`, `NoArgs`) are pydantic models.
  - Their field names are `design.py`'s argument names. The replay node feeds a recorded `design_log.jsonl` straight back through these tools, and `test_every_tool_field_is_an_argument_of_its_command` checks the match.
  - Field descriptions give the formats: atom lists like `1,2,3:0.5`, candidates like `1,2,3|4,5:0.5,6`, citations as `PATH:LOCATOR`.
  - `BeadArgs.rung` is restricted to 1–3 and `VsiteArgs.construction` to the two allowed constructions.
- **`SPECS`** lists `(command, schema, description)` for 17 commands (`init` is run by the intake node), including `propose` (projected partitions), `evidence` (per-bead evidence) and `research` (the pipeline's research step; no agent gets it, but replay can re-issue it from a log).
- **`make_design_tools(ctx, names=None)`** builds `StructuredTool`s named `design_<command>`, optionally only those in `names`. Each returns `ctx.page(result.text())`.

All validation stays in `design.py`: rung-1 signature checks, unique rationales of 25+ characters, candidate weights summing to one, at most three candidates, existence of cited files and types.

---

## `tools/reference_tools.py`

Read-only tools for the configured reference files and the molecule's own run folder.

- **`_resolve(root, allowed, rel)`** resolves a path relative to the project root and refuses anything outside `generation_reference_paths` (symlinks and `..` are resolved first). Agents cannot read benchmarks, other runs or the harness code.
- **`make_reference_tools(ctx)`** returns four tools:

  | Tool | What it does |
  | --- | --- |
  | `list_references(path="")` | Lists the readable roots, or the content of one folder (`.git` hidden) |
  | `read_reference(path, start_line, n_lines)` | Numbered lines of a text file, at most 400 per call, so the agent can cite `path:line N`. Refuses PDFs and binary formats |
  | `grep_references(pattern, path, max_hits)` | `grep -rniIE`, at most 20 hits per file and `max_hits` in total; default path `references/derived` |
  | `pdf_page_text(path, page)` | `pdftotext -layout` of one page |

  Paths in results are relative to the project root, which is the form `design.py` checks in `--source`. These tools can search or extract text. `sections.json` is a document locator, and `design_open` can return a mapping figure's path when the model entry has one.
- **`make_run_file_tool(ctx)`** returns `read_run_file(path, start_line, n_lines)` for files inside the molecule folder. Only the repair node gets it.

---

## `models.py`

Chat models through OpenRouter.

- **`load_dotenv()`** reads `customized_harness/.env` without overwriting variables that are already set.
- **`_limiter(cfg)`** is one `InMemoryRateLimiter` for the whole process, at `requests_per_minute`. All nodes and fallbacks share it, because OpenRouter's free-tier limit is per account.
- **`chat_model(cfg, model_id)`** creates a `ChatOpenRouter` with the configured `temperature` and `max_tokens`, `max_retries=2`, the shared limiter, `reasoning={"effort": reasoning_effort}` and `app_title`. The timeout is `request_timeout_s × 1000`, because `ChatOpenRouter.request_timeout` is in milliseconds (it maps to the SDK's `timeout_ms`). Until 2026-11-20 the seconds were passed unchanged, so every call had a 0.18 s or 0.3 s timeout. That caused every "timeout" in the first two LLM runs. It raises a clear error if `OPENROUTER_API_KEY` is missing.
- **`node_models(cfg, node)`** returns the node's primary model and its fallbacks, without repeating the primary.

---

## `trace.py`

**`JsonlTracer(path, node)`** is a LangChain callback handler. Each record carries the node name and a UTC time.

| Event | Recorded |
| --- | --- |
| `model_start` | Number of messages and characters sent |
| `model_end` | The model that answered, provider, finish reason, token usage, the tool calls requested with their arguments, the first 2,000 characters of text |
| `model_error` | Exception type and message (timeouts, 429 rate limits) |
| `tool_start` / `tool_end` / `tool_error` | Tool name, input, and the first 3,000 characters of output |
| `agent_error` | Written by `Pipeline.run_agent` when an agent fails as a whole |

The machine's clock can jump by about 2 hours (WSL2), so order records by file position, not by time.

---

## `nodes.py`

The graph state, and every node as a method of `Pipeline`.

**`MolState`** (TypedDict) is what flows between nodes:

| Key | Set by | Meaning |
| --- | --- | --- |
| `mol_id`, `name`, `smiles`, `aa_topology`, `moldir`, `mode`, `replay_log` | cli | Inputs |
| `init_output` | intake | Output of `design init` |
| `evidence`, `mapping_summary`, `typing_summary` | agents | Each agent's final answer, passed to the next agent |
| `feedback` | gates | Why an agent is sent back; empty when the step passed |
| `attempts` | gates | Retries per gate (`{"mapping": n, "typing": n}`) |
| `repairs` | repair | Number of repair cycles used |
| `failure`, `stage_failed` | bonded_build, test | What failed (`"bonded"`, `"build"` or `"test"`) and the details |
| `status` | preflight, intake, bonded_build, finalize | `blocked`, or the status from `validation.json` |
| `final_message` | report | The final message |
| `events` | every node | One line per step (`operator.add` reducer, so updates append) |

**`AGENT_TOOLS`** says which design commands each agent node gets, and whether it gets the reference tools and `read_run_file`. Research cannot record candidates or beads, mapping cannot record beads, typing cannot record candidates, and repair can change all of them. This enforces "partition first, type second" structurally.

**`Pipeline(cfg, moldir, mode)`** holds the configuration, the `ToolContext`, the trace path and `max_repairs` (`max_repair_cycles` of `environment.json`), and runs `runner.configure`.

Helpers:
- `tools_for(node)` builds the node's tool list from `AGENT_TOOLS`.
- `run_agent(node, task, limit_key)` builds an agent with LangChain's `create_agent` (the node's model, tools and system prompt) and three middleware: `ModelCallLimitMiddleware` (the node's call limit), `ModelRetryMiddleware` (backoff 5 s to 90 s, `model_retries` times) and `ModelFallbackMiddleware` (if fallbacks are configured). It invokes the agent with the task as one human message. Any exception is written to the trace and returned as `[agent error] ...`, so the gate after the node decides what happens next. It saves the full message list to `harness/transcripts/NN_<node>.json` and returns the last message's text.
- `design(cmd, **kw)` runs a design command and returns its text.
- `stage(cmd)` runs one `cgbuild` stage (`bonded`, `build`, `test`, `finalize`) on the molecule folder.

Deterministic nodes (each returns a partial state update):

| Node | Does | Status and routing data |
| --- | --- | --- |
| `preflight` | Checks that the supplied AA topology file exists | `status: blocked` with `failure` if it is missing |
| `intake` | `cgbuild.cmd_input`, then `design init` with `agent=langgraph-harness` and `model=<mapping model>` (or `replay`), so `design.json` records who made the decisions | `init_output`; `blocked` on failure |
| `mapping_gate` | Reads `decisions/design.json`: is `chosen_candidate` set? | Empty `feedback` if yes; otherwise feedback with `design show` and a higher `attempts.mapping` |
| `typing_gate` | `design check` (exit 0 means complete) | Feedback is the check's list of what is missing |
| `bonded_build` | Stages `bonded` and `build`; reads `test/static_checks.json` | `stage_failed="bonded"` (with `bonded_failure.json`) or `"build"` (with the failed static checks); the event line shows `bonded.json` flags |
| `test` | Stage `test` with `random_seed`; on a failure again with `random_seed` + 1 and + 2 (`cgbuild.TEST_RETRY_SEEDS`); writes `test/retries.json` | Passes if every stage passes with one of the seeds (a later seed adds a flagged marginal-stability check at finalize); otherwise `stage_failed="test"` |
| `finalize` | Stage `finalize`; `multi_seed_check.check` into `multi_seed/` if a model exists; `sasa_check.check` into `sasa/` if the ensemble exists | `status` from `validation.json` |
| `replay` | Replay mode only: re-issues each command of a recorded `design_log.jsonl` (except `init`) through the same design tools, keeping only arguments the tool's schema knows | Counts commands and errors; `check` failures are expected mid-log and not counted |
| `report` | Gathers events, status, last failure, `report.md`, `multi_seed/results.json`, `sasa/summary.json` and `bonded.json` flags. In LLM mode (with `run_report_agent`) the report model writes the final message from these records only; otherwise the records are the message | Writes `harness/final_message.md` |

Agent nodes build a task message and call `run_agent`:

| Node | Task message contains | Limit key |
| --- | --- | --- |
| `research` | Molecule, atom table, top `research_task_hits` hits (`research: agent`). With `research: pipeline` (the default) no agent runs: the node calls `design research` and passes its output on as `evidence` | `research_model_calls` |
| `mapping` | The pipeline's choice with its rationale (confirm or override), atom table, ranked partitions with each bead's source and SASA (`design propose`), research evidence | `mapping_model_calls` |
| `typing` | Atom table, the chosen candidate's beads (JSON), per-bead evidence (`design evidence`), mapping summary, research summary | `typing_model_calls` |
| `repair` | Failed stage and its details, `design show`, per-bead evidence | `repair_model_calls` |

When a gate sent the node back, `_fb` appends a "Feedback from the pipeline (fix this first)" section.

---

## `graph.py`

**`build_graph(pipeline)`** builds and compiles the `StateGraph(MolState)`.

```
START → preflight → intake → research → mapping → mapping_gate → typing → typing_gate
      → bonded_build → test → finalize → report → END
```

| From | Rule |
| --- | --- |
| `preflight`, `intake` | `status == "blocked"` → `report`, otherwise the next step |
| `mapping_gate` | No feedback → `typing`. Feedback and `attempts.mapping ≤ gate_retries` → `mapping`. Otherwise → `report` |
| `typing_gate` | No feedback → `bonded_build`. Feedback and retries left (LLM mode) → `typing`. Otherwise → `report` |
| `bonded_build` | Stage 4 failed → `report` (not something an agent may fix by choosing values). Static check failed → `repair` if repairs are left, else `finalize` (which classifies the model as `blocked`). Otherwise → `test` |
| `test` | Failed with all three seeds and repairs left → `repair`, else `finalize` |
| `repair` | Always → `typing_gate`, so the changed design is checked before stage 4 runs again |

In replay mode the agent nodes (and `repair`) are replaced by one `replay` node, and gates go to `report` instead of back to an agent. Everything else is identical, so a replay tests the whole deterministic path. It does not test what only a live model does: parallel tool calls, notes, retries.

The graph is compiled with `InMemorySaver`, so `app.get_state(...)` and `app.get_state_history(...)` work during a run. State is not kept after the process ends; the `state/` snapshots written by `cli.py` are the durable record.

---

## `cli.py`

The command line (`python -m martini_harness.cli ...`).

| Command | Does |
| --- | --- |
| `run --id --name --smiles --aa-topology [--config] [--label] [--runs-root]` | Full run with the configured models |
| `replay ... --log design_log.jsonl [--compare design.json]` | Runs the graph with a recorded design instead of agents, and optionally compares the resulting decisions with a recorded `design.json` |
| `graph [--mode llm\|replay] [--config]` | Prints the compiled graph as Mermaid |

**`run(args, mode)`**:
1. Creates `runs/<label>-<UTC>/<ID>/`. The two levels leave room for several molecules per run folder later.
2. Builds the pipeline and graph and writes `harness/graph.mmd`.
3. Writes `harness/run.json`: config path, models per node, fallbacks, limits and molecule.
4. Streams the graph with `stream_mode="updates"`. Each node's update is saved as `harness/state/NN_<node>.json`, and its `events` lines are printed and appended to `harness/events.log` with elapsed seconds.
5. Adds the finish time, wall time, status, repairs and (for replay) the comparison to `run.json`.

It returns 0 whatever the status; an exception that escapes a node (a bug outside `runner.call`) ends the process with a traceback.

**`compare_designs(new, old)`** compares two `design.json` files: beads (name, type, members with weights, rung), chosen candidate, candidates, opened references and virtual sites. It returns `identical_decisions` and per-field results. Free-text rationales and timestamps are not compared.

---

## Tests (`../tests/`)

- **`test_calls.py`**: in-process calls on a CHXO folder. A refused decision is an `[exit 2]` message; an incomplete design is `[exit 1]` with the to-do list; unknown arguments are rejected before the command runs; defaults match the command line; a tool returns refusals as text; a failed stage is a message and a log entry; every tool field is an argument of its command; eight parallel `design_note` calls keep `design.json` valid and keep every note.
- **`test_golden.py`** with `golden/`: `golden.replay` runs `cli replay` on each fixture (`fixtures/<ID>/`: `design_log.jsonl`, AA topology, `molecule.json`, `recorded_design.json`); `golden.snapshot` reduces the folder to what must not change (decisions, `bonded.json`, `mapping.json`, `parameters.json`, `molecule.itp`, `molecule.gro` and SASA exactly; static checks, execution steps, validation checks and seeds as pass/fail); `golden.diff` compares it with `expected/<ID>.json`. Fixtures: CHXO, PHAC, PIPL. `make_golden.py` rewrites the expected files; use it only for an intended change of outputs, and review the differences first.

## Other Python files

- **`../test.py`**: an early one-call check of `ChatOpenRouter` with `openrouter/free`. The harness doesn't use it.
- **`build_index.py`**: builds the four prepared indexes and `build_report.json` from `references/index/src/` and the Bible workbook (see its docstring and `../README.md`). Example records: `ndx_beads` for SM3; ITP types and charges for FF300 with memberships from a single bead, `resolve_on_molecule` (kept when `placement_kind` finds one placement up to symmetry; the ITP type wins over a CGSmiles type, `itp_types_win`) or the curated file; CGSmiles placement for the Bible. A record whose memberships leave heavy atoms out is downgraded to `fragment_signature`. Method records are located by phrase in their source text and copied verbatim.
- **`../docs/build_flow_pdf.py`**: builds `docs/flow_of_information_CHXO.pdf`: Parts A–F follow the live Haiku run `runs/compare-20261121-exact/haiku-CHXO-r3-*/CHXO`, Parts G–J the replay `runs/replay-20261119T003848Z/CHXO` (same decisions); plus the LangGraph design, every Python file, the offline index build and a debugging guide. Line numbers are looked up at build time; a renamed or removed function makes the build fail with its name.

## Extending

- **Another model for one node:** set `models.<node>` in the config, or copy the config and pass `--config`.
- **A new agent step:**
  1. add `prompts/tasks/<node>.md` and the node's stages to `system_prompts.NODE_STAGES`;
  2. add its tools to `nodes.AGENT_TOOLS`;
  3. add a method to `Pipeline`;
  4. wire it in `graph.build_graph`.
- **A new deterministic check:** add a function to `core/`, a node method that calls it through `runner.call` and reads the record it writes, then a conditional edge on a state key it sets.
- **Batch:** loop over a TSV in a new CLI command, building one `Pipeline` and graph per molecule in `runs/<label>-<UTC>/<ID>/`, then summarise the run folder (the skill's `cgbuild.py summary` was not copied; a summary step would have to be added to `core/`). Molecules can't run in parallel threads of one process (the call lock and `cgbuild`'s module-level configuration); use one process per molecule.
