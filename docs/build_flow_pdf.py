"""Builds customized_harness/docs/flow_of_information_CHXO.pdf: the flow of information for one molecule (CHXO),
the LangGraph node design, the offline index build, and a description of every Python file.

Line numbers are looked up in the source files at build time, so they match the code the reader has open.
Run from customized_harness/: python docs/build_flow_pdf.py (needs reportlab).
"""
import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "martini_harness/core"
OUT = ROOT / "docs/flow_of_information_CHXO.pdf"
RUN = "runs/replay-final-20261122T051914Z/CHXO"              # Parts G-J (replay of the recorded design, current code)
LIVE = "runs/logp26-20261121/final-haiku/CHXO-20261122T023816Z/CHXO"   # Parts A-F (live Haiku 5.5 run, default settings)

FILES = {
    "cli.py": ROOT / "martini_harness/cli.py", "config.py": ROOT / "martini_harness/config.py",
    "graph.py": ROOT / "martini_harness/graph.py", "nodes.py": ROOT / "martini_harness/nodes.py",
    "runner.py": ROOT / "martini_harness/runner.py", "system_prompts.py": ROOT / "martini_harness/system_prompts.py",
    "models.py": ROOT / "martini_harness/models.py", "trace.py": ROOT / "martini_harness/trace.py",
    "tools/common.py": ROOT / "martini_harness/tools/common.py",
    "tools/design_tools.py": ROOT / "martini_harness/tools/design_tools.py",
    "tools/reference_tools.py": ROOT / "martini_harness/tools/reference_tools.py",
    "build_index.py": ROOT / "martini_harness/build_index.py",
}
for _f in ("cgbuild.py", "design.py", "partition.py", "refbeads.py", "derive_bonded.py", "multi_seed_check.py",
           "sasa_check.py", "d5bonded/opls.py", "d5bonded/energy.py", "d5bonded/ensemble.py", "d5bonded/terms.py",
           "d5bonded/fit.py", "d5bonded/geometry.py", "d5bonded/mapping.py"):
    FILES["core/" + _f] = CORE / _f
_cache = {}
BUILT = __import__("datetime").date.today().isoformat()
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "martini_harness/__init__.py").read_text()).group(1)


def line_of(f, name):
    """Line of `def name` / `class name` in file f; 'Cls.meth' finds meth after class Cls; inner functions too."""
    lines = _cache.setdefault(f, FILES[f].read_text().splitlines())
    start = 0
    if "." in name:
        cls, name = name.split(".", 1)
        for i, l in enumerate(lines):
            if re.match(rf"^\s*class\s+{re.escape(cls)}\b", l):
                start = i
                break
        else:
            raise KeyError(f"class {cls} not in {f}")
    for i in range(start, len(lines)):
        if re.match(rf"^\s*(async\s+def|def|class)\s+{re.escape(name)}\b", lines[i]):
            return i + 1
    raise KeyError(f"{name} not in {f}")


def chain(rows):
    """A call chain as a table: (file, function, what happens); file 'model'/'LangChain' for rows outside the code.
    Called after the styles are defined (it appends to `story`)."""
    data = []
    for i, (f, name, what) in enumerate(rows):
        arrow = "" if i == 0 else ("← " if i == len(rows) - 1 else "→ ")
        where = arrow + (ref(f, name) if name else f"<i>{escape(f)}</i>")
        data.append([Paragraph(where, SMALL), Paragraph(md(what), SMALL)])
    t = Table(data, colWidths=[78 * mm, WIDTH - 78 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d2dc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f8fa")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    story.append(t)
    story.append(Spacer(1, 6))


def ref(f, name):
    """'file.py:LINE name()' as markup."""
    n = line_of(f, name)
    short = name.split(".")[-1] if not name.startswith(("Heavy", "Examples", "GmxTopology", "OplsObc2", "NumpyEnergy", "Pipeline", "CallResult", "DesignError", "StageError", "ToolContext", "JsonlTracer", "D5Ensemble", "OplsTopology", "HarnessConfig")) else name
    return f'<font face="Courier" color="#1f4e79">{escape(f)}:{n}</font> <b>{escape(short)}()</b>'


def md(text):
    """Escape, then `code` -> Courier, **b** -> bold, {f|name} -> located function reference."""
    out, pos = [], 0
    for m in re.finditer(r"\{([^{}|]+)\|([^{}]+)\}", text):
        out.append(_inline(text[pos:m.start()]))
        out.append(ref(m.group(1), m.group(2)))
        pos = m.end()
    out.append(_inline(text[pos:]))
    return "".join(out)


def _inline(t):
    t = escape(t)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    for u, r in (("⁻¹", "-1"), ("⁻²", "-2"), ("²", "2"), ("³", "3"), ("ᵀ", "T")):
        t = t.replace(u, f"<super>{r}</super>")
    return t


# ---------------------------------------------------------------- styles
ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.6, leading=11.2, alignment=TA_LEFT)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.8, leading=10)
LABEL = ParagraphStyle("label", parent=BODY, fontName="Helvetica-Bold", fontSize=7.6, leading=10, textColor=colors.HexColor("#444444"))
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=8, spaceAfter=4,
                    textColor=colors.HexColor("#1f4e79"))
STEPH = ParagraphStyle("steph", parent=BODY, fontName="Helvetica-Bold", fontSize=9, leading=11.5)
CODE = ParagraphStyle("code", parent=BODY, fontName="Courier", fontSize=7.2, leading=8.8)

story = []
step_no = [0]
STEPLOG = []  # first function of each step, in order (for checking cross-references)
WIDTH = A4[0] - 30 * mm


def h1(t):
    story.append(Paragraph(md(t), H1))


def h2(t):
    story.append(Paragraph(md(t), H2))


def p(t, style=BODY):
    story.append(Paragraph(md(t), style))
    story.append(Spacer(1, 3))


def code(t):
    story.append(Preformatted(t, CODE))
    story.append(Spacer(1, 4))


def step(where, does, produces, sent):
    """where: list of (file, function) in call order; first is the step's main function."""
    step_no[0] += 1
    STEPLOG.append(where[0][1])
    head = Paragraph(f"Step {step_no[0]}: " + " → ".join(ref(f, n) for f, n in where), STEPH)
    rows = [[head, ""],
            [Paragraph("Does", LABEL), Paragraph(md(does), BODY)],
            [Paragraph("Produces", LABEL), Paragraph(md(produces), BODY)],
            [Paragraph("Sent to", LABEL), Paragraph(md(sent), BODY)]]
    t = Table(rows, colWidths=[17 * mm, WIDTH - 17 * mm])
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#e8eef5")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#9aaabb")),
        ("LINEBELOW", (0, 0), (1, 0), 0.4, colors.HexColor("#9aaabb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(KeepTogether([t, Spacer(1, 5)]))


def table(rows, widths, header=True, style=SMALL):
    data = [[Paragraph(md(c), style) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b5c0cc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
          ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")))
    t.setStyle(TableStyle(st))
    story.append(t)
    story.append(Spacer(1, 6))


# ================================================================= content
h1("Flow of information: from SMILES to a Martini topology (CHXO)")
p("**Contents.** How one agent tool call reaches the code; the inputs; the path in one table; **the LangGraph "
  "design** (nodes, state, routing, what each agent receives); Parts A–J, the run step by step; Appendix A, "
  "files and who reads them; Appendix B, functions CHXO did not reach; **Appendix C, every Python file**; "
  "**Appendix D, the offline index build**; Appendix E, debugging guide.")
p("This document follows one molecule, cyclohexanone (CHXO, SMILES `O=C1CCCCC1`), through the harness "
  "`customized_harness/martini_harness`: one Python package in which LangGraph orders the steps, LangChain agents "
  "make the chemical decisions and `martini_harness/core` does every deterministic calculation. Each step names "
  "the file and function, what it does, what it produces and where that goes next, so the code can be read "
  "alongside it.")
p("**Reading the references.** `core/cgbuild.py:201 cmd_input()` means: open `martini_harness/core/cgbuild.py` "
  "at line 201. Every file is given relative to `martini_harness/` (for example `nodes.py`, "
  "`tools/design_tools.py`, `core/design.py`, `core/d5bonded/terms.py`). Line numbers were read from the files "
  f"when this PDF was built ({BUILT}, harness version {VERSION}). In a step heading, `→` lists the functions in "
  "the order they call each other.")
p("**Where the numbers come from.** Parts A–F follow the live run `customized_harness/" + LIVE + "` "
  "(Haiku 5.5, 2026-11-22, default settings: research by the pipeline, which records and chooses the partition; "
  "the mapping agent confirms it; typing from prepared evidence: 6 model calls, status `execution_checked`). Its task "
  "messages, tool calls and decisions are quoted as they happened; it produced three beads (B1 TN4a = atoms 1, 2; "
  "B2 SC3 = 3, 4, 5; B3 TC3 = 6, 7). Parts G–J show stage 4 and the deterministic checks on the **recorded "
  "CHXO design** of the golden test (two beads: O1 TN6a = atoms 1, 2, 3 (½), 7 (½); R2 C3 = 3 (½), 4, 5, 6, 7 (½)), "
  "with numbers from its replay on the same code, `customized_harness/" + RUN + "`. The functions are the same for "
  "any design; the two-bead design keeps the numbers short.")
p("**One process.** Every function in this document runs in the harness's own Python process: a node or a tool "
  "calls a `core` function through {runner.py|call} (Step 8), which captures what the function prints and turns "
  "a refusal or a failure into a result with an exit code. Calls run one at a time, even when a model asks "
  "for several tools in one turn. Data passes as Python arguments and as files in the "
  "molecule folder. The only other programs started are external ones: GROMACS (`gmx`, Parts I and J) and, "
  "if no AA topology is supplied, the OPLS engine.")

h2("How one agent tool call reaches the code")
p("The same chain carries every agent decision of Parts D–F. Here the typing agent records bead B1 (Step 52). "
  "Read it downwards for the call, upwards for the answer the model receives.")
chain([
    ("model", "", "returns a tool call `design_bead(name='B1', atoms='1,2', rung=1, source_bead='BIBLE:row327:TN4a#2', rationale=...)`"),
    ("LangChain", "", "validates the arguments against `BeadArgs` (pydantic) and calls the tool's function"),
    ("tools/design_tools.py", "make_design_tools", "`fn(_cmd='bead', **kw)`: the tool function"),
    ("tools/design_tools.py", "run_design", "`run_design(ctx, 'bead', **kw)`"),
    ("core/design.py", "namespace", "`namespace('bead', moldir, **kw)`: the command's defaults plus the agent's arguments"),
    ("runner.py", "call", "`call(moldir, cmd_bead, ns, tag='design.bead')`: waits for `_CALL_LOCK` (one core call at a time)"),
    ("runner.py", "_call", "runs `cmd_bead` with `print` captured, catches `DesignError`"),
    ("core/design.py", "cmd_bead", "`cmd_bead(ns)`: checks the claim, copies the type, writes `design.json` and the log line"),
    ("core/design.py", "die", "on a refused claim: `raise DesignError(message)`"),
    ("runner.py", "CallResult.text", "the result text, `[exit 2]` + message when refused; one line in `harness/commands.jsonl`"),
    ("tools/common.py", "ToolContext.page", "first 6000 characters, plus a handle for `more_output` if longer"),
    ("model", "", "receives the text as a ToolMessage and decides the next call"),
])
p("A deterministic node takes a shorter path to the same wrapper, for example {nodes.py|Pipeline.stage} → "
  "{runner.py|call} → {core/cgbuild.py|cmd_build}. Who calls the agents themselves: the graph runs a node "
  "method ({nodes.py|Pipeline.research}, {nodes.py|Pipeline.mapping}, {nodes.py|Pipeline.typing}, "
  "{nodes.py|Pipeline.repair}); each builds a task message and calls {nodes.py|Pipeline.run_agent}, which "
  "creates a LangChain agent with that node's model, tools and system prompt and runs its loop (Step 39).")

h2("The inputs")
table([["Input", "Value for CHXO", "First used in"],
       ["SMILES", "`O=C1CCCCC1` (7 heavy atoms, formula C6H10O, formal charge 0)", "Step 1, then Step 12"],
       ["Molecule id and name", "`CHXO`, `cyclohexanone`", "Step 1"],
       ["OPLS-AA topology", "`tests/golden/fixtures/CHXO/aa_topology.top` (copy of the benchmark's "
        "`agent_codex/CHXO/input/aa_topology.top`): 17 atoms "
        "(O, 6 C, 10 H), 17 bonds, 45 pairs, 33 angles, 49 dihedrals, nrexcl 3, defaults `1 3 yes 0.5 0.5`", "Step 13"],
       ["Martini environment", "`environment.json`: references, force-field ITPs, GROMACS, "
        "seed 20261031, `bonded` settings (300 conformers, 200 samples per minimum, "
        "8 kcal/mol window)", "Step 2"],
       ["Harness configuration", "`config/harness.json`: models per node, limits, timeouts", "Step 2"]],
      [32 * mm, 105 * mm, WIDTH - 137 * mm])

h2("The path in one table")
table([["Part", "What happens", "Main output", "Steps"],
       ["—", "Offline, before any run: `build_index.py` prepares the reference indexes", "`references/index/*.jsonl`", "Appendix D"],
       ["A", "Harness starts, builds the graph", "compiled graph, initial state", "1–6"],
       ["B", "Preflight: AA topology exists", "pass / blocked", "7–10"],
       ["C", "SMILES and AA topology enter the core code; design initialised; reference search over the prepared indexes", "`input/*`, `design.json`, `analogue_search.json`", "11–34"],
       ["D", "Research by the pipeline: candidate partitions (cover search, up-front SASA), references opened and annotated, the best partition recorded and chosen", "candidates, choice and annotations in `design.json`, evidence text", "35–44"],
       ["E", "The mapping agent confirms or overrides the pipeline's partition", "the choice in `design.json`", "45–50"],
       ["F", "The harness selects evidence per bead; the typing agent records each bead's type and charge", "beads in `design.json`", "51–56"],
       ["G", "Stage 4: SMILES + AA topology + mapping → bonded terms (no MD)", "`decisions/bonded.json`, ensemble `.npz`", "57–74"],
       ["H", "Build: the Martini topology files", "`model/molecule.itp`, `.gro`, `mapping.svg`", "75–84"],
       ["I", "GROMACS execution checks", "`test/execution.json`", "85–90"],
       ["J", "Finalize, multi-seed and SASA checks, final message", "`validation.json`, `report.md`, `final_message.md`", "91–97"]],
      [10 * mm, 82 * mm, 62 * mm, WIDTH - 154 * mm])

story.append(PageBreak())
h2("The LangGraph design: nodes, state and routing")
p("{graph.py|build_graph} builds one `StateGraph(MolState)` per molecule. Every node is a method of "
  "{nodes.py|Pipeline}; it receives the whole state and returns a partial update (a dict), which LangGraph merges "
  "into the state (`events` is appended, everything else replaced). {cli.py|run} streams the graph and saves each "
  "update as `harness/state/NN_<node>.json`. Code nodes call `core` functions through {runner.py|call}; agent "
  "nodes run a LangChain agent ({nodes.py|Pipeline.run_agent}) whose tools call the same `core` functions.")
code("""START -> preflight -> intake -> research -> mapping -> mapping_gate -> typing -> typing_gate
      -> bonded_build -> test -> finalize -> report -> END

preflight, intake   blocked                 -> report
mapping_gate        no choice               -> mapping (up to gate_retries = 2), then report
typing_gate         design incomplete       -> typing  (up to gate_retries = 2), then report
bonded_build        stage 4 failed          -> report  (not repairable by an agent)
                    static check failed     -> repair (repairs left) or finalize (status blocked)
test                a GROMACS stage failed  -> repair (repairs left) or finalize
repair              always                  -> typing_gate (the changed design is checked first)
replay mode: research, mapping, typing and repair are replaced by one `replay` node""")
h2("Nodes")
table([["Node", "Kind", "Method", "Reads", "Does", "State update"],
       ["preflight", "code", "{nodes.py|Pipeline.preflight}", "`aa_topology`", "checks the AA topology file exists", "`events`; `status: blocked`, `failure` if missing"],
       ["intake", "code", "{nodes.py|Pipeline.intake}", "`smiles`, `mol_id`, `name`, `aa_topology`", "`cgbuild.cmd_input` (frozen input), `design init` (queries, reference search)", "`init_output`, `attempts`, `repairs`"],
       ["research", "agent or code", "{nodes.py|Pipeline.research}", "atom table, top hits", "`design research` ({core/design.py|cmd_research}) without a model (`research: pipeline`, the default): opens and annotates references, scores candidate partitions by SASA ({core/sasa_check.py|partition_sasa}), records the best and chooses it; or an agent opens, matches and annotates references (`research: agent`)", "`evidence` (final answer, or the printed evidence blocks)"],
       ["mapping", "agent", "{nodes.py|Pipeline.mapping}", "atom table, the pipeline's choice, **projected partitions with SASA** (`design propose`), `evidence`", "confirms or overrides the pipeline's choice (or records and chooses candidates)", "`mapping_summary`"],
       ["mapping_gate", "code", "{nodes.py|Pipeline.mapping_gate}", "`design.json`", "is a candidate chosen?", "`feedback`, `attempts.mapping`"],
       ["typing", "agent", "{nodes.py|Pipeline.typing}", "chosen candidate, **per-bead evidence** (`design evidence`), summaries", "records every bead with type, rung, sources", "`typing_summary`"],
       ["typing_gate", "code", "{nodes.py|Pipeline.typing_gate}", "`design.json`", "`design check`", "`feedback`, `attempts.typing`"],
       ["bonded_build", "code", "{nodes.py|Pipeline.bonded_build}", "design, input", "stages `bonded` and `build`", "`stage_failed`, `failure`, or ok"],
       ["test", "code", "{nodes.py|Pipeline.test}", "model files", "stage `test` (GROMACS)", "`stage_failed`, `failure`, or ok"],
       ["repair", "agent", "{nodes.py|Pipeline.repair}", "failure, `design show`, per-bead evidence", "changes mapping, sites or beads", "`repairs`, `feedback: ''`"],
       ["finalize", "code", "{nodes.py|Pipeline.finalize}", "all records", "stage `finalize`, multi-seed, SASA", "`status`"],
       ["report", "model / code", "{nodes.py|Pipeline.report}", "records only", "final message", "`final_message`"],
       ["replay", "code", "{nodes.py|Pipeline.replay}", "`replay_log`", "re-issues a recorded `design_log.jsonl` through the same tools", "`evidence`, `mapping_summary` = 'replayed'"]],
      [17 * mm, 11 * mm, 37 * mm, 34 * mm, 44 * mm, WIDTH - 143 * mm])
h2("State (`MolState`, {nodes.py|MolState})")
table([["Key", "Set by", "Meaning"],
       ["`mol_id`, `name`, `smiles`, `aa_topology`, `moldir`, `mode`, `replay_log`", "{cli.py|run}", "inputs"],
       ["`init_output`", "intake", "printed output of `design init`"],
       ["`evidence`, `mapping_summary`, `typing_summary`", "research, mapping, typing", "each agent's final answer, passed to the next agent's task"],
       ["`feedback`", "gates", "why an agent is sent back (empty when the step passed); appended to the next task by {nodes.py|Pipeline._fb}"],
       ["`attempts`, `repairs`", "gates, repair", "retry counters checked by the routing functions"],
       ["`failure`, `stage_failed`", "bonded_build, test", "what failed and where"],
       ["`status`", "preflight, intake, bonded_build, finalize", "`blocked` or the status from `validation.json`"],
       ["`final_message`", "report", "the run's final message"],
       ["`events`", "every node", "one line per step (`operator.add` reducer: updates append)"]],
      [62 * mm, 40 * mm, WIDTH - 102 * mm])
h2("What each agent node receives")
p("{nodes.py|Pipeline.run_agent} builds a LangChain agent (`create_agent`) from three things: the system prompt "
  "({system_prompts.py|system_prompt}: `prompts/harness.md` + `prompts/tasks/<node>.md` + `prompts/rules.md` + "
  "the stage files of `NODE_STAGES`), the node's tools ({nodes.py|Pipeline.tools_for} from `AGENT_TOOLS`) and a "
  "task message built by the node method. **Work done by the harness before the agent starts** is in the task "
  "message, so the agent does not spend model calls on it.")
table([["Node", "System prompt (characters)", "Task message (prepared by the harness)", "Design tools", "Limit key (calls)"],
       ["research (only with `research: agent`)", "harness, tasks/research, rules, stage 2 (13.1k)", "molecule, atom table, top 15 ranked hits with support (`atoms`/`fragments`/`types`)",
        "atoms, hits, query, open, annotate, match, note, show + reference tools", "`research_model_calls` (30)"],
       ["mapping", "harness, tasks/mapping, rules, stages 2 and 4 (15.4k)", "**the pipeline's choice** (confirm or override), atom table, **ranked partitions P1–P3** with each bead's source and SASA (`design propose`), research evidence",
        "atoms, hits, open, annotate, match, propose, candidate, choose, hydrogens, vsite, note, show + reference tools", "`mapping_model_calls` (25)"],
       ["typing", "harness, tasks/typing, rules, stage 3 (10.3k)", "atom table, chosen candidate, **evidence per bead**: size, rung-1 precedents (with surroundings and the order's result when they disagree), matching Table 24/25 and Alessandri Table 1 rows with citations, C2 rules (`design evidence`), summaries",
        "atoms, open, annotate, match, evidence, bead, vsite, note, show, check + reference tools", "`typing_model_calls` (30)"],
       ["repair", "harness, tasks/repair, rules, stages 2–5 (19.2k)", "failed stage and details, `design show`, evidence per bead",
        "all of the above + `read_run_file`", "`repair_model_calls` (20)"],
       ["report", "harness, tasks/report, stage 6 (3.7k)", "events, status, report.md, multi-seed, SASA, bonded flags", "none (one model call)", "—"]],
      [15 * mm, 36 * mm, 62 * mm, 50 * mm, WIDTH - 163 * mm])
p("**Structural rules.** The tools enforce the method's order: research cannot record candidates or beads, mapping "
  "cannot record beads, typing cannot record candidates. Every decision goes through a `design_*` tool, so its "
  "checks and its log line apply; there is no shell and no file-writing tool. `design_candidate` refuses a "
  "partition that breaks the mapping rules (Step 47); `design_bead` refuses a rung-1 claim whose fragment "
  "signature differs from its source (Step 52); the gates re-check the design themselves (Steps 50, 56).")

story.append(PageBreak())
# ----------------------------------------------------------------- Part A
h2("Part A. The harness starts")
step([("cli.py", "main")],
     "Parses the command line `run --id CHXO --name cyclohexanone --smiles 'O=C1CCCCC1' --aa-topology <path>` "
     "(or `replay ... --log design_log.jsonl`).",
     "An argparse namespace `a` with `id`, `name`, `smiles`, `aa_topology`, `config`, `label`.",
     "{cli.py|run} with mode `llm` (or `replay`).")
step([("cli.py", "run"), ("config.py", "load_config")],
     "Reads `config/harness.json`, then the Martini `environment.json` it names. Resolves relative paths "
     "against `customized_harness/` ({config.py|_abs}).",
     "A {config.py|HarnessConfig}: `project` is the folder of `environment.json`, the base of every reference path. Includes `env` (the "
     "environment dict), `martini_env` (its path), `runs_root`, and `prompts` = `martini_harness/prompts/`.",
     "Back to {cli.py|run}; every later node reads it through the `Pipeline`.")
step([("cli.py", "run"), ("cli.py", "_utc")],
     "Creates the molecule folder `runs/<label>-<UTC>/CHXO/` and `harness/state/`.",
     "The absolute path `moldir`. The SMILES is not written yet; it lives in the graph state until Step 12.",
     "{nodes.py|Pipeline.__init__}.")
step([("nodes.py", "Pipeline.__init__"), ("tools/common.py", "ToolContext"), ("runner.py", "configure"),
      ("core/cgbuild.py", "configure")],
     "Stores the configuration and folder; creates the `ToolContext` that binds every tool to this one folder "
     "and pages long outputs (6000 characters); sets the trace path and `max_repairs` = 3 "
     "(`max_repair_cycles` of environment.json). **`configure` points the core code at the environment, once:** "
     "`cgbuild.configure` reads `environment.json` and sets the module values every core function uses: "
     "`ENV`, `PROJECT`, `GMX` (the GROMACS command), `SEED` 20261031, the paths of the core, solvent "
     "and ion ITPs, the water box, the production MDP, the tutorial MDP folder, the prepared index files "
     "(`INDEXES`: models, FF300, Bible, method evidence; their in-memory caches are cleared), and `GMX_THREADS` "
     "(4, from `gmx_threads`). It removes `OMP_NUM_THREADS`, which GROMACS "
     "rejects when it differs from `-ntomp`.",
     "The `Pipeline` object whose methods are the graph nodes.",
     "{graph.py|build_graph}.")
step([("graph.py", "build_graph")],
     "Adds every node (Pipeline methods), the fixed edges and the conditional edges (routing functions "
     "{graph.py|blocked}, {graph.py|after_mapping}, {graph.py|after_typing}, {graph.py|can_repair}, "
     "{graph.py|after_build}, {graph.py|after_test}); compiles with `InMemorySaver`.",
     "The compiled LangGraph `app`.",
     "{cli.py|run}, which writes `harness/graph.mmd` and `harness/run.json`.")
step([("cli.py", "run")],
     "Builds the initial state, a `MolState` ({nodes.py|MolState}): `mol_id` CHXO, `name`, `smiles` "
     "`O=C1CCCCC1`, `aa_topology` (absolute path), `moldir`, `mode`, `replay_log`, `events` []. Starts "
     "`app.stream(state, stream_mode='updates')`. After every node it writes `harness/state/NN_<node>.json` "
     "and appends the node's `events` to `harness/events.log`.",
     "The running graph. From here on each node receives the whole state and returns a partial update.",
     "The first node, {nodes.py|Pipeline.preflight}.")

# ----------------------------------------------------------------- Part B
h2("Part B. Preflight")
step([("nodes.py", "Pipeline.preflight")],
     "Takes the all-atom topology path from the graph state.",
     "The supplied path.",
     "{nodes.py|Pipeline.preflight} checks the path (Step 9).")
step([("runner.py", "call"), ("runner.py", "_call"), ("runner.py", "_now"), ("runner.py", "CallResult"), ("runner.py", "_brief")],
     "(Reference for Parts C–J.) **The single bridge from a node or tool to a core function.** `call(moldir, fn, "
     "*args, tag=...)` runs `fn` with `print` redirected into a buffer. A `DesignError` (refused decision) becomes "
     "its exit code (2, or 1 for an incomplete design) and the message `design: ...`; a `StageError` (a stage "
     "that cannot go on) code 1 and its message; `SystemExit` its code; any other exception code 1 with the full "
     "traceback, so a bug in the core code shows in the result instead of ending the run. Appends one line to "
     "`harness/commands.jsonl` (tag, function, arguments, exit, output tails). **One call at a time:** `call` holds "
     "a process-wide lock (`_CALL_LOCK`) and runs the work in `_call`. A model may ask for several tools in one "
     "turn, and LangChain runs them in parallel threads; without the lock their output mixed (the `print` "
     "redirect is process-wide) and design commands, which each read, change and rewrite `design.json`, "
     "corrupted it (first Haiku 5.5 run, 2026-11-20).",
     "A `CallResult(code, stdout, stderr, call)`; `ok` is `code == 0`, {runner.py|CallResult.text} joins the "
     "output and puts `[exit N]` first on failure.",
     "Whoever called it. The deterministic stages and design tools use this wrapper.")
step([("nodes.py", "Pipeline.preflight")],
     "Checks that the AA topology file exists.",
     "State update `{events: ['preflight: AA topology found']}`. A missing file sets `status: blocked` and `failure`.",
     "Routing lambda in {graph.py|build_graph}.")
step([("graph.py", "build_graph")],
     "Routes on the preflight status.",
     "A blocked run goes to `report`. A run with an AA topology goes to `intake`.",
     "{nodes.py|Pipeline.intake} for CHXO.")

# ----------------------------------------------------------------- Part C
h2("Part C. The SMILES and the AA topology enter the core code")
p("Part C is where the two inputs are first parsed, checked against each other and frozen as files. "
  "Everything later reads these files, never the original strings in the graph state.")
step([("nodes.py", "Pipeline.intake"), ("runner.py", "call")],
     "Builds the arguments of the input stage as a `SimpleNamespace(moldir, smiles='O=C1CCCCC1', id='CHXO', "
     "name='cyclohexanone', aa_topology=<path>, cls='', stereo_note='', aa_engine='', aa_charge_model='')` and "
     "calls `call(moldir, cgbuild.cmd_input, a, tag='cgbuild.input')`.",
     "The call of the next step.",
     "{core/cgbuild.py|cmd_input}.")
step([("core/cgbuild.py", "cmd_input")],
     "Uses the module values set by `configure` (Step 4). `cmd_input` starts: "
     "`Chem.MolFromSmiles('O=C1CCCCC1')` → `mol0` (RDKit indices O0, C1–C6), "
     "`SanitizeMol`, canonical isomeric SMILES `O=C1CCCCC1`, chiral centres (none), double-bond stereo "
     "(none), fragments (1).",
     "`mol0` and the SMILES descriptors that go into `request.json` (Step 18).",
     "Because `aa_topology` is given: {core/cgbuild.py|supplied_topology}.")
step([("core/cgbuild.py", "supplied_topology"), ("core/d5bonded/opls.py", "flatten_topology"), ("core/d5bonded/energy.py", "_read_lines")],
     "**The AA topology enters here.** `_read_lines` reads the user's file, expands `#include` (relative to "
     "the including file), refuses other preprocessor directives and strips comments. `flatten_topology` "
     "checks the section list: it adds `[ defaults ] 1 3 yes 0.5 0.5` if missing (with a note) and "
     "`[ system ]`/`[ molecules ]` if missing, then writes one self-contained file.",
     "`input/aa_topology.top` (194 lines for CHXO; it already had `[ defaults ]`, so notes = []).",
     "{core/d5bonded/opls.py|check_supplied_topology} with the SMILES and the flattened file.")
step([("core/d5bonded/opls.py", "check_supplied_topology"), ("core/d5bonded/energy.py", "GmxTopology.__init__"),
      ("core/d5bonded/energy.py", "GmxTopology._need")],
     "Parses the flattened topology into arrays: `[ defaults ]` (nbfunc, comb-rule, gen-pairs, fudgeLJ, "
     "fudgeQQ), `[ atomtypes ]` (σ, ε, mass by type), `[ moleculetype ]` nrexcl, `[ atoms ]` (charge, mass; "
     "element from mass with `MASS_TO_Z`), `[ bonds ]`, `[ pairs ]`, `[ angles ]`, `[ dihedrals ]` (funct 3 → "
     "Ryckaert–Bellemans list, funct 1/4/9 → periodic list), `[ exclusions ]`, `[ molecules ]`. `_need` "
     "rejects unsupported function types. It requires comb-rule 3 and gen-pairs (OPLS-AA) and one molecule.",
     "A `GmxTopology` `g`: n = 17, charges (O −0.454, carbonyl C +0.367, ring C −0.17 to −0.23, H +0.09 to "
     "+0.13), z, σ, ε, bonded lists.",
     "{core/d5bonded/opls.py|atom_permutation} inside `check_supplied_topology`.")
step([("core/d5bonded/opls.py", "atom_permutation"), ("core/d5bonded/opls.py", "_bare_graph")],
     "**The SMILES and the topology are matched atom by atom.** Builds two element-only graphs with single "
     "bonds (`_bare_graph`): one from `Chem.AddHs(mol)` of the SMILES, one from the topology's elements and "
     "bonds. Compares atom and bond counts (17/17), then `GetSubstructMatch`.",
     "`perm`: `perm[i]` = RDKit index of topology atom i. A different bond graph or protonation state raises "
     "`TopologyError`.",
     "Back to `check_supplied_topology`, which then checks the largest |charge| (0.454 ≤ 3.4 e), the net charge "
     "(0.000 against formal charge 0, tolerance 0.02 e) and fudge factors (0.5/0.5, so no note). It returns "
     "`(g, perm, notes)` to {core/cgbuild.py|supplied_topology}.")
step([("core/cgbuild.py", "supplied_topology"), ("core/cgbuild.py", "sha256")],
     "Builds the record of the accepted topology. On any error it writes `input/aa_topology_failure.json` and "
     "raises `StageError`, which {runner.py|call} turns into a failed result (intake then blocks the run).",
     "`aa_top` = {file `input/aa_topology.top`, sha256 `0839da…`, source_path, source_sha256 `2f4cfb…`, "
     "engine None, charge_model None, n_atoms 17, net_charge_e 0, notes []}.",
     "Back to {core/cgbuild.py|cmd_input}; it is written into `request.json` (Step 18). Stage 4 checks the file "
     "against this sha256 (Step 59).")
step([("core/cgbuild.py", "cmd_input")],
     "Generates the atomistic structure from the SMILES: `Chem.AddHs(mol0)` → `molH` (17 atoms; H appended "
     "after the heavy atoms, indices 7–16); ETKDGv3 with `randomSeed` 20261031, `EmbedMultipleConfs("
     "numConfs=10)`; `MMFFOptimizeMoleculeConfs(maxIters=5000)`; stereo re-assigned from 3D per conformer; "
     "the lowest-energy converged conformer is selected.",
     "10 conformers: 8 at 1.0611 kcal/mol (chair) and 2 at 4.0326 (twist); selected conformer id 0.",
     "The file writers in the next step.")
step([("core/cgbuild.py", "cmd_input"), ("core/cgbuild.py", "wjson")],
     "Writes the frozen input of the run.",
     "`input/atomistic.sdf` (selected conformer, 17 atoms, RDKit order); `input/conformers.sdf` (all 10); "
     "`input/atoms.json` (one-based `atom_id`, RDKit index, element, hybridisation, neighbours, coordinates in "
     "nm); `input/request.json` (original and canonical SMILES, formal charge 0, formula C6H10O, 7 heavy atoms, "
     "stereo, `aa_topology` record, environment path, hash and snapshot); `input/conformers.json`.",
     "Read later by: the design commands ({core/design.py|target} reads `atomistic.sdf`), stage 4 "
     "(`request.json`, `aa_topology.top`), the build (`conformers.sdf`, `atomistic.sdf`). `cmd_input` returns "
     "and {runner.py|call} hands its printed summary back to {nodes.py|Pipeline.intake}.")
step([("nodes.py", "Pipeline.intake"), ("nodes.py", "Pipeline.design"), ("tools/design_tools.py", "run_design"),
      ("core/design.py", "namespace"), ("core/design.py", "build_parser"), ("runner.py", "call")],
     "Initialises the decision record with `design('init', agent='langgraph-harness', model=<mapping model>)` "
     "(`replay` in replay mode). `namespace` takes the defaults of the `init` command from `build_parser` and "
     "adds the keyword arguments, so the function receives exactly what a command line would give it; an "
     "unknown argument raises `TypeError` before anything runs.",
     "`call(moldir, cmd_init, ns, tag='design.init')`.",
     "{core/design.py|cmd_init}.")
step([("core/design.py", "cmd_init"), ("core/design.py", "target")],
     "On import `core/design.py` imports `cgbuild` (whose module values `configure` set in Step 4) and "
     "`refbeads`, and makes a Morgan fingerprint generator (radius 2, 2048 bits). `cmd_init` refuses an existing "
     "`design.json` ({core/design.py|die} raises `DesignError`), reads `request.json`, and `target` reads "
     "`input/atomistic.sdf` with hydrogens. It builds the empty design: `molecule_id`, `resname` CHXO, "
     "`authored_by` (agent, model, tool `martini_harness.core.design`), `analogue_queries`, empty annotations, "
     "candidates, beads, virtual sites, notes.",
     "The design dictionary in memory; its queries come from the next step.",
     "{core/design.py|derive_queries}.")
step([("core/design.py", "derive_queries"), ("core/design.py", "add")],
     "**First use of the SMILES chemistry for the search.** On the heavy-atom molecule: ring systems "
     "(merged rings), single rings of fused systems, ring–substituent junctions, every `GROUPS` SMARTS "
     "(functional groups) with and without its neighbouring atoms, and acyclic sp3 carbon chains of 3 or more. "
     "`add` turns an atom set into a fragment SMILES and skips duplicates.",
     "4 queries for CHXO: `ring_system_1` `C1CCCCC1`, `ring_1_substituent_at_2` `O=C1CCCCC1`, `ketone` "
     "`[#6][CX3](=O)[#6]`, `ketone_at_3-2-1-7` `CCC(=O)CC` (no chain: every carbon is in the ring).",
     "Stored in `design['analogue_queries']`, then {core/design.py|save}.")
step([("core/design.py", "save"), ("core/cgbuild.py", "wjson"), ("core/design.py", "sha"), ("core/design.py", "now")],
     "Writes the design and appends one line to the decision log with the hash of the design it leaves. "
     "Every later design command that changes the design ends here, which forms the hash chain checked in "
     "Step 77.",
     "`decisions/design.json` and line 1 of `decisions/design_log.jsonl` `{utc, command 'init', args, "
     "design_sha256}`.",
     "{core/design.py|run_search}.")
step([("core/design.py", "run_search"), ("core/cgbuild.py", "cmd_search"), ("core/cgbuild.py", "rjson"), ("core/cgbuild.py", "examples"),
      ("core/cgbuild.py", "tautomer_key"), ("core/cgbuild.py", "index_files")],
     "Runs `cgbuild.cmd_search` in-process with its printing suppressed. It reads the queries from `design.json` "
     "and the SMILES from `request.json`, and takes every example record from {core/cgbuild.py|examples} (Step 26): "
     "177 records of `models.jsonl`, 74 of `ff300.jsonl`, 334 of `bible.jsonl`. Each query SMARTS (and motif tag) "
     "is matched against every record's SMILES. Exposure: the target's constitution and canonical tautomer are "
     "looked up in the prepared identity tables (same molecule in any index → `reference_exposed`). Hits are merged "
     "by reference ID with the annotations so far.",
     "`decisions/analogue_search.json` (36 hits for CHXO, each with `mapping_support`; `reference_exposed` false; "
     "the index files and their hashes).",
     "{core/design.py|atom_table} and {core/design.py|print_hits}, which print what the agent will see.")
step([("core/design.py", "atom_table")],
     "Prints the heavy-atom SMILES with one-based ids as atom-map numbers and one line per heavy atom.",
     "`[O:1]=[C:2]1[CH2:3][CH2:4][CH2:5][CH2:6][CH2:7]1`; atom 1 O (neighbour 2); atom 2 C (1, 3, 7); atoms "
     "3–7 CH2 in the ring. **These one-based ids are the atom ids every later decision uses.**",
     "Printed output of `cmd_init`, captured by {runner.py|call}; the same table reaches the agent (Step 35).")
step([("core/design.py", "print_hits"), ("core/design.py", "ranked_hits"), ("core/design.py", "refs")],
     "Ranks hits by Tanimoto similarity of Morgan fingerprints (radius 2, 2048 bits) between the target and each "
     "hit's SMILES; prints the top 15 with each record's support (`atoms` = bead member atoms known, `fragments` = "
     "signatures only, `types` = types only) and bead types, taken from the prepared records ({core/design.py|refs}).",
     "`SM3:CYPO:opt`, `SM3:CYPO:cog` and `BIBLE:row169` cyclopentanone 0.91 (atoms; SC3 TN6a); cyclohexane 0.27 "
     "(four records, SC3 SC3); benzoquinones 0.19 and 0.15; …",
     "The init output (Step 32), and later the research task (Step 35).")
step([("core/cgbuild.py", "examples"), ("core/cgbuild.py", "Examples"), ("core/cgbuild.py", "method_evidence")],
     "**Loads the prepared indexes, once per configuration** (`functools.cache`; cleared by `configure`). Reads "
     "`models.jsonl`, `ff300.jsonl`, `bible.jsonl` in that order and builds four tables: records by id; ids by "
     "constitution; ids by canonical tautomer; and, for every bead with a verified signature, the beads holding "
     "each fragment signature (1648 beads). `method_evidence` loads `method_evidence.jsonl` (130 records). Nothing "
     "is computed from the source files during a run; the records were built offline (Appendix D).",
     "An `Examples(records, exact, tautomers, fragments)` tuple and the method records.",
     "Every later lookup: {core/design.py|precedents} (rung-1 precedents, a table lookup), {core/design.py|cmd_open}, "
     "{core/design.py|cmd_bead}, {core/design.py|cmd_evidence}, {core/partition.py|projections}.")
step([("build_index.py", "build_models"), ("build_index.py", "example"), ("build_index.py", "bead"), ("build_index.py", "support_of")],
     "(Offline, Appendix D.) How the record `SM3:CYPO:opt` came to be. `build_models` reads its catalog entry from "
     "`references/index/src/models_catalog.jsonl`, makes its beads with {core/refbeads.py|ndx_beads} (next step), "
     "and `example` writes the common record: id, collection, name, variant, molecule (SMILES, formal charge, "
     "constitution, tautomer), motifs, source (ITP path, locator, sha256, `.ndx` mapping, figure, AA ITP, DOI), "
     "`mapping_support` (`support_of`: all beads with members → `atom_membership`) and `mapping_origin` (`ndx`). "
     "A record whose memberships leave a heavy atom out is downgraded to `fragment_signature`.",
     "One line of `references/index/models.jsonl`; member atoms are 1-based positions in the record's SMILES.",
     "{core/cgbuild.py|examples} at run time.")
step([("core/refbeads.py", "ndx_beads"), ("core/refbeads.py", "_aa_to_smiles_perm"), ("core/refbeads.py", "_itp_atoms_bonds"),
      ("core/refbeads.py", "_element_from_mass"), ("core/refbeads.py", "_parse_ndx"), ("core/refbeads.py", "neighbours")],
     "(Offline.) `_aa_to_smiles_perm` reads the reference's all-atom ITP (`_itp_atoms_bonds`; elements from masses "
     "with `_element_from_mass`) and matches its graph onto `AddHs(SMILES)` → map from AA atom number to SMILES "
     "index. `_itp_atoms_bonds` of the CG ITP gives bead names, types and charges; `_parse_ndx` gives each bead's "
     "AA atoms; an atom listed in two groups gets weight ½ in each; `neighbours` lists the bonded CG beads.",
     "Per bead: name, type, charge, `members` `{SMILES atom: weight}`, `source_atoms` (AA numbers), neighbours. "
     "CYPO bead O2 (TN6a): carbonyl O and C at 1, the two neighbouring carbons at 0.5.",
     "{core/refbeads.py|fragment_signature} for each bead.")
step([("core/refbeads.py", "fragment_signature"), ("core/refbeads.py", "_normalise")],
     "**The fragment signature, the key of rung-1 typing.** Builds a new molecule from the bead's heavy atoms "
     "(sorted, so the result does not depend on their order; element, charge, aromaticity; an isotope label "
     "`round(100·w)` on a shared atom with weight below 1), the bonds among them, and one dummy atom `*` for every "
     "bond to a heavy atom outside the bead. `_normalise` removes H counts, map numbers and stereo, makes dummy "
     "bonds single and returns canonical SMILES.",
     "CYPO O2 → `*[50C]C(=O)[50C]*`; CYPO R1 (SC3) → `*[50C]CC[50C]*`.",
     "Stored as `signature` in the bead record. The same function signs the target's beads (Steps 46, 47, 51, 52), "
     "so equal strings mean the same atoms in the same bonding context.")
step([("core/refbeads.py", "cgsmiles_beads"), ("core/refbeads.py", "cg_graph"), ("core/refbeads.py", "_cgsmiles_fragment_to_smiles"),
      ("core/refbeads.py", "_half"), ("core/refbeads.py", "_aromatic_bonds"), ("build_index.py", "placed_beads")],
     "(Offline.) Bible rows and most FF300 molecules come as CGSmiles. Example `BIBLE:row169` (cyclopentanone, "
     "fragments `[!]CC(=O)C[!]` and `[!]CCCC[!]`). Splits the CGSmiles into CG block and fragment block; "
     "`cg_graph` gives node names and CG bonds; the type comes from the node name, checked against the core types; "
     "`_cgsmiles_fragment_to_smiles` turns a fragment into SMILES with a dummy per bonding descriptor and weight "
     "labels (a squash `[!]` marks a shared atom, weight 0.5 through `_half`); `_aromatic_bonds` restores aromatic "
     "bonds. `placed_beads` (build_index) then places them.",
     "Bead records `TN6a#1`, `SC3#2` with `fragment_smiles` and `cg_neighbours`.",
     "{core/refbeads.py|resolve_on_molecule}.")
step([("core/refbeads.py", "resolve_on_molecule"), ("core/refbeads.py", "place_beads"), ("core/refbeads.py", "_fragment_query"),
      ("core/refbeads.py", "touches"), ("core/refbeads.py", "rec"), ("core/refbeads.py", "placement_kind")],
     "(Offline.) Places the fragments on the source molecule: `_fragment_query` makes a substructure query per "
     "fragment; the recursive search `rec` keeps combinations where every heavy atom's weights sum to 1 and CG "
     "neighbours touch (`touches`). `placement_kind`: one placement → `unique`; every placement the first one moved "
     "by a symmetry of the molecule (beads of the same fragment may swap) → `symmetry_equivalent`; otherwise "
     "`ambiguous`. In the first two cases each bead keeps its **member atoms** from the first placement and the "
     "signature that follows from them; an ambiguous molecule keeps signatures only.",
     "`BIBLE:row169` (SMILES `C1CCC(=O)C1`): TN6a#1 `*[50C]C(=O)[50C]*` atoms {4: 1, 5: 1, 3: 0.5, 6: 0.5}, "
     "SC3#2 `*[50C]CC[50C]*` atoms {1: 1, 2: 1, 3: 0.5, 6: 0.5}; `atom_membership` via `cgsmiles_placement`. "
     "Bible: 279 of 334 rows have memberships.",
     "Saved in `references/index/bible.jsonl` (and `ff300.jsonl`), loaded in Step 26.")
step([("core/design.py", "cmd_init")],
     "Prints the derived queries with hit counts, the exposure line and the ranked hits, and returns (exit code 0 in the `CallResult`).",
     "The text `init_output` (about 2,600 characters for CHXO).",
     "Back through {runner.py|call} to {nodes.py|Pipeline.intake}.")
step([("nodes.py", "Pipeline.intake")],
     "Returns the state update.",
     "`{init_output, attempts: {}, repairs: 0, events: ['intake: input frozen, design initialised']}`.",
     "Routing in {graph.py|build_graph}: not blocked → {nodes.py|Pipeline.research} (LLM mode) or "
     "{nodes.py|Pipeline.replay} (replay mode, Step 44).")
step([("tools/design_tools.py", "make_design_tools"), ("tools/design_tools.py", "fn")],
     "(Reference for Parts D–F.) Creates one LangChain `StructuredTool` per design command listed in `SPECS` "
     "(16 commands; `init` is run by intake), "
     "named `design_<command>`, with a pydantic argument schema whose field names are the command's argument "
     "names (a test checks that every field exists). The tool function `fn` calls "
     "{tools/design_tools.py|run_design} and returns `ToolContext.page(result.text())`.",
     "The design tools an agent node receives (a subset per node, `AGENT_TOOLS` in `nodes.py`).",
     "Each tool call in Parts D–F goes: tool → `run_design` → `namespace` → `call` → the `cmd_*` function named "
     "in the step (the chain shown before Part A).")

# ----------------------------------------------------------------- Part D
h2("Part D. Research by the pipeline: references, candidate partitions and the choice")
p("With `research: pipeline` (the default) this step makes no model call. With `research: agent` an agent opens, "
  "matches and annotates references instead (Steps 40–43 describe the agent machinery all agent nodes share).")
step([("nodes.py", "Pipeline.research"), ("nodes.py", "Pipeline.design"), ("core/design.py", "cmd_research")],
     "`research_mode` is `pipeline` (config key `research`, or `cli run --research`), so the node calls "
     "`design('research')` and passes its printed output on as `evidence`.",
     "State `{evidence: <one block per opened reference>, events: ['research (pipeline): 12 references opened and annotated']}`.",
     "{core/design.py|cmd_research}.")
step([("core/design.py", "cmd_research"), ("core/design.py", "ranked_candidates"), ("core/design.py", "similarity_to"),
      ("core/partition.py", "projections"), ("core/partition.py", "assemble")],
     "`ranked_candidates` builds the candidate partitions (the cover search of Step 46) and ranks them: within the "
     "mapping rules; fewest beads without an exact precedent; the SASA band (next step); rings with shared atoms before "
     "unshared ones; fewer references; the closest analogue (`similarity_to`).",
     "For CHXO: P1 `1,2|3,4,5|6,7` (all three beads exact; SASA −6.6 %, review) and P2 `1,2,3,4|5,6,7` (one bead "
     "without an exact precedent; SASA −5.0 %, pass): exact precedents rank before SASA.",
     "The SASA of each candidate comes from Step 37.")
step([("core/sasa_check.py", "partition_sasa"), ("core/derive_bonded.py", "derive_ensemble"), ("core/derive_bonded.py", "mapping_matrix"),
      ("core/sasa_check.py", "checked_sasa")],
     "**SASA before any type exists.** Builds the stage-4 atomistic ensemble once (same function, seed and frames as "
     "Step 60; kept in `research/ensemble_atoms.npz`), computes the atomistic SASA once (`research/sasa_aa.json`), maps "
     "each candidate onto the same 200 frames and compares the bead surface (radius from the size letter of the bead's "
     "exact precedents when they agree, else from its heavy-atom weight). It reproduces the final SASA of Step 96 when "
     "typing keeps those sizes.",
     "`[(−6.6, 'review'), (−5.0, 'pass')]` for P1 and P2; about 1 s for CHXO, up to a minute for long chains.",
     "Back to the ranking in Step 36.")
step([("core/design.py", "cmd_research"), ("core/design.py", "precedents"), ("core/design.py", "mark_opened")],
     "Chooses what to open: the source of every bead of the top partitions, up to two references holding each bead's "
     "fragment exactly (atom memberships first), and the five closest other search hits; marks each opened and "
     "annotates it with the reason (`mark_opened`). Prints one compact block per reference (SMILES, source and "
     "locator, beads with signatures and atoms; variants with identical beads collapsed).",
     "12 references opened and annotated, e.g. `SM3:BZQU:cog` 'source of bead 1,2 in projected partition P1 (same fragment)'.",
     "The evidence text.")
step([("core/design.py", "cmd_research"), ("core/design.py", "sasa_text"), ("core/design.py", "save")],
     "**Records the choice.** Writes the best complete, rule-abiding candidates (at most two, so an agent can add one) "
     "as `P1`, `P2` with `proposed_by: pipeline`, each bead's source, the SASA, and chooses P1: `chosen_candidate` "
     "and `pipeline_choice` P1, with a rationale giving the exact-precedent count and SASA. One log line, so a replay "
     "re-runs the step.",
     "Design log line 2 (`research`); the mapping agent reviews this choice (Part E).",
     "Back to {nodes.py|Pipeline.research}.")
step([("nodes.py", "Pipeline.run_agent"), ("models.py", "node_models"), ("models.py", "chat_model"),
      ("models.py", "load_dotenv"), ("models.py", "_limiter")],
     "(Reference for every agent node.) Creates the chat models: the node's model and its fallbacks "
     "(`config/haiku.json`: Haiku 5.5; `config/luna.json`: GPT-6 Luna, 20 requests a minute; `config/nemotron.json`: "
     "Nemotron 3 Ultra free; `config/harness.json`: free models with fallbacks). `load_dotenv` reads "
     "`customized_harness/.env` if present (else `OPENROUTER_API_KEY` from the environment); `_limiter` is one shared "
     "rate limiter. Each model is a `ChatOpenRouter` (temperature 0, 4096 tokens, reasoning effort low, timeout "
     "`request_timeout_s` × 1000 because `ChatOpenRouter.request_timeout` is in milliseconds).",
     "Primary model and fallback list.",
     "`create_agent` in Step 43.")
step([("nodes.py", "Pipeline.run_agent"), ("system_prompts.py", "system_prompt"), ("system_prompts.py", "_read")],
     "Builds the system prompt from the files in `martini_harness/prompts/` (`_read` caches each file): "
     "`harness.md`, `tasks/<node>.md`, `rules.md` and the node's stages from `NODE_STAGES`.",
     "Mapping 15.4k characters, typing 10.3k.",
     "`create_agent` in Step 43.")
step([("nodes.py", "Pipeline.tools_for"), ("tools/design_tools.py", "make_design_tools"), ("tools/common.py", "more_output_tool"),
      ("tools/reference_tools.py", "make_reference_tools"), ("tools/reference_tools.py", "_resolve")],
     "Gives an agent node its tools from `AGENT_TOOLS`: the node's design commands, `more_output`, and the read-only "
     "reference tools ({tools/reference_tools.py|list_references}, {tools/reference_tools.py|read_reference}, "
     "{tools/reference_tools.py|grep_references}, {tools/reference_tools.py|pdf_page_text}), limited by `_resolve` to "
     "`generation_reference_paths`.",
     "Mapping cannot record beads, typing cannot record candidates.",
     "`create_agent` in Step 43.")
step([("nodes.py", "Pipeline.run_agent"), ("trace.py", "JsonlTracer")],
     "`create_agent(model, tools, system_prompt, middleware)` with `ModelCallLimitMiddleware`, `ModelRetryMiddleware` "
     "and `ModelFallbackMiddleware`; `agent.invoke({'messages': [HumanMessage(task)]})` with the tracer. The loop: the "
     "model answers; requested tool calls are validated against their schemas and run (in parallel threads; core calls "
     "wait for each other in {runner.py|call}); results return as tool messages; until the model answers without tool "
     "calls or reaches the limit. {trace.py|JsonlTracer.on_llm_end} and {trace.py|JsonlTracer.on_tool_end} write "
     "`harness/trace.jsonl`; {nodes.py|Pipeline._transcript} saves `harness/transcripts/NN_<node>.json`.",
     "The final answer of the node.",
     "The calling node.")
step([("nodes.py", "Pipeline.replay"), ("tools/design_tools.py", "make_design_tools")],
     "(Replay mode only, replacing Parts D–F.) Reads each line of a recorded `design_log.jsonl` (except `init`), "
     "keeps the arguments the tool's schema knows, and invokes the same `design_<command>` tool (a logged `research` "
     "is re-run). The replay behind Parts G–J reproduced the recorded design this way.",
     "Counts of commands and errors.",
     "{nodes.py|Pipeline.mapping_gate}.")

h2("Part E. Mapping: the agent confirms or overrides the pipeline's partition")
step([("nodes.py", "Pipeline.mapping"), ("nodes.py", "Pipeline.design"), ("core/design.py", "cmd_propose"), ("nodes.py", "Pipeline.run_agent")],
     "Builds the task: a head 'The pipeline has recorded and chosen P1' with the pipeline's rationale and what "
     "confirm or override means; the atom table; the ranked partitions (`design('propose')`, next step); the research "
     "evidence. Tools: design `atoms`, `hits`, `open`, `annotate`, `match`, `propose`, `candidate`, `choose`, "
     "`hydrogens`, `vsite`, `note`, `show`, plus reference tools.",
     "Task of 8,858 characters; 1 model call in the live run.",
     "The model; the summary to the state as `mapping_summary`.")
step([("core/design.py", "cmd_propose"), ("core/partition.py", "projections"), ("core/partition.py", "_place"),
      ("core/partition.py", "_bead_query"), ("core/partition.py", "bead_pool"), ("core/partition.py", "bead_maker"),
      ("core/partition.py", "_connected_sets"), ("core/partition.py", "cover_search"), ("core/partition.py", "assemble"),
      ("core/partition.py", "building_blocks")],
     "**The cover search.** `projections` places the beads of the 25 most similar models with atom memberships on the "
     "target (`_bead_query`, `_place`: shared atoms stay shared, bonded atoms bonded). `bead_pool` collects every bead a "
     "partition may use: projected beads, every other placement of their fragments with the same signature, every "
     "connected set of 2–5 atoms whose fragment has an indexed precedent, and 2–4-atom sets without one; `bead_maker` "
     "drops beads that cut an indivisible group or break the size rules. `cover_search` finds, by backtracking from the "
     "most constrained atom (exact beads first), the sets of beads whose weights sum to one on every heavy atom, also "
     "closing a branch with a filler bead. The search is bounded by exactness: a branch with more non-exact beads than "
     "the best cover found so far plus one (`COVER_SLACK`) is not explored, so the fewest non-exact beads found does not "
     "depend on the search order; only covers distinct up to symmetry (`cover_key`) are kept and counted (at most 500, "
     "a better cover replacing a worse one); 50,000 steps limit the work. `assemble` ranks them (Step 36). "
     "`building_blocks` lists Alessandri Table 1 rows for filler beads.",
     "P1 `1,2|3,4,5|6,7`: C=O from `SM3:BZQU:cog:O1`, CCC from `BIBLE:row163:SC3#2`, CC from `SM3:CYPE:opt:C1`, all "
     "`same`, SASA −6.6 % (review); P2 `1,2,3,4|5,6,7` (−5.0 %, pass); then the best projection per reference.",
     "Into the mapping task message.")
step([("core/design.py", "cmd_candidate"), ("core/design.py", "partition"), ("core/partition.py", "issues"),
      ("core/partition.py", "size_of"), ("core/design.py", "save")],
     "(Used when the agent overrides with a partition of its own; not called in the live run.) `design_candidate` "
     "checks that weights sum to one, then the mapping rules ({core/partition.py|issues}): a lone-atom bead, a bead "
     "above R size or a divided carbonyl, carboxyl, ester, amide, nitro, nitrile, sulfonyl, sulfoxide or phosphate "
     "group is refused (`[exit 2]`) unless `exception` names an indexed reference that does the same. At most 3 "
     "candidates.",
     "A candidate in `design.json`, its per-bead size, signature, precedents and Table 1 blocks printed.",
     "Back to the model.")
step([("core/design.py", "cmd_choose")],
     "**Confirm or override.** The agent confirms by finishing without changing the choice (the live run: one model "
     "call, 'confirm P1'). An override is `design_choose` of another candidate; it is refused when the rationale is "
     "under 40 characters, so the reason for not using the pipeline's choice is recorded.",
     "`chosen_candidate` stays P1.",
     "The model stops.")
step([("nodes.py", "Pipeline.run_agent"), ("nodes.py", "Pipeline._transcript")],
     "Saves the transcript and returns the final text.",
     "`harness/transcripts/01_mapping.json`; state `{mapping_summary}`.",
     "Fixed edge mapping → {nodes.py|Pipeline.mapping_gate}.")
step([("nodes.py", "Pipeline.mapping_gate"), ("nodes.py", "_rjson"), ("graph.py", "after_mapping")],
     "Reads `decisions/design.json`: is `chosen_candidate` set, and is it the pipeline's choice? Without a choice it "
     "returns feedback with `design('show')` and counts the attempt.",
     "`feedback: ''`; event 'mapping gate: candidate P1 chosen (pipeline's choice confirmed)'.",
     "`after_mapping`: no feedback → {nodes.py|Pipeline.typing}; with feedback → mapping again (up to "
     "`gate_retries` = 2), then report.")

h2("Part F. Typing: the harness selects evidence per bead, the agent records types")
step([("nodes.py", "Pipeline.typing"), ("core/design.py", "cmd_evidence"), ("core/design.py", "applies"),
      ("core/design.py", "surroundings"), ("core/design.py", "precedent_surroundings"), ("core/cgbuild.py", "method_evidence"),
      ("core/design.py", "cite"), ("nodes.py", "Pipeline.run_agent")],
     "Builds the task: atom table, the chosen candidate, **the evidence per bead** (`design('evidence')`), the "
     "summaries. Per bead the evidence gives its fragment, signature and **size** (T, S or R; a type chosen without an "
     "exact precedent must have that size); the indexed beads holding the fragment; when they **disagree on the type**, "
     "per type the count, how many have the same **surroundings** (atoms one bond outside the bead: element, aromatic, "
     "double bond; `surroundings`, `precedent_surroundings`), the partition's source for the bead and its type, and the "
     "type the instruction's order gives (the most precedents with the same surroundings, then the partition's source "
     "as tie-break; identical fragments take one type); then the Table 24/25 and Alessandri Table 1 rows whose "
     "`applies_to` holds (`applies`), with citations, and the C2 rules.",
     "Task of 15,093 characters. B1 `1,2` (*C(*)=O): TN6a 8 precedents, 0 with the same C,C surroundings (quinone "
     "carbonyls), TN4a 1 with them → TN4a. B2 `3,4,5`: SC3 24 of 34. B3 `6,7`: TC3 14, the partition's source.",
     "The model: 4 model calls, no document reads.")
step([("core/design.py", "cmd_bead"), ("core/design.py", "parse_atoms"), ("core/design.py", "signature"), ("core/design.py", "precedents"),
      ("core/cgbuild.py", "core_types"), ("core/design.py", "refs"), ("core/design.py", "save")],
     "Tool calls `design_open` of the four sources (log lines 3–6), then `design_bead(name='B1', atoms='1,2', rung=1, "
     "source_bead='BIBLE:row327:TN4a#2', rationale)`. Checks: rationale of at least 25 characters, unique; the source "
     "record has beads, was opened, has the bead, and its signature equals the target bead's. Then **the type is "
     "copied, not chosen**: TN4a. Records `transferred`, the typing ladder with every bead holding the fragment, the "
     "sources, marks the reference used, and keeps beads in the chosen candidate's order.",
     "Bead B1 TN4a, rung 1 (log line 7).",
     "Back to the model.")
step([("core/design.py", "cmd_bead"), ("core/design.py", "parse_source")],
     "Tool calls for B2 (`3,4,5`, source `BIBLE:row163:SC3#2` → SC3) and B3 (`6,7`, source `SM3:CYPE:opt:C1` → TC3), "
     "both rung 1. (A rung 2 or 3 bead would cite `MEV:` locators from the evidence block; `parse_source` checks each "
     "cited file exists under the project and has a locator.)",
     "Beads B2 SC3 and B3 TC3 (log lines 8–9).",
     "Back to the model.")
step([("core/design.py", "cmd_check"), ("core/design.py", "problems"), ("core/design.py", "run_search"), ("core/design.py", "save")],
     "Tool call `design_check()`. `problems` lists what is missing: a choice, beads that partition the molecule exactly "
     "as the chosen candidate, every heavy atom allocated, a reason for every opened reference, charges summing to the "
     "formal charge. It refreshes `analogue_search.json` (Step 23) and saves.",
     "`design complete: 3 beads` (log line 12).",
     "Back to the model.")
step([("core/design.py", "cmd_note")],
     "Tool calls `design_note(limitation=...)` (log lines 10–11): the SASA review band of P1, and that TN4a rests on one "
     "precedent with matching surroundings (`BIBLE:row327`) while the eight TN6a precedents are quinone carbonyls. Both "
     "are listed in `report.md`.",
     "Two limitations in `design.json`.",
     "The model stops; {nodes.py|Pipeline._transcript} writes `02_typing.json`; state `{typing_summary}`.")
step([("nodes.py", "Pipeline.typing_gate"), ("tools/design_tools.py", "run_design"), ("core/design.py", "cmd_check")],
     "Runs the check itself, `run_design(ctx, 'check')` (not trusting the agent's word).",
     "Exit 0 → `feedback: ''` (log line 13).",
     "{graph.py|after_typing}: no feedback → {nodes.py|Pipeline.bonded_build}; otherwise typing again with "
     "the check output (up to 2 retries), then report.")
p("**State of the decisions in the live run** (`decisions/design.json`): B1 = atoms 1 (O), 2 (C), TN4a; B2 = 3, 4, 5, "
  "SC3; B3 = 6, 7, TC3; all rung 1; charges 0. Everything that follows is deterministic. **Parts G–J follow the "
  "recorded two-bead design of the golden test** (O1 TN6a = 1, 2, 3 (½), 7 (½); R2 C3 = 3 (½), 4, 5, 6, 7 (½)) through "
  "the same functions; the live run's three beads go through them the same way.")

# ----------------------------------------------------------------- Part G
story.append(PageBreak())
h2("Part G. Stage 4: SMILES + AA topology + mapping → bonded terms (no MD)")
p("This is where the SMILES and the AA topology meet again, now together with the mapping. The SMILES gives "
  "the conformers; the AA topology gives the energy that weights them; the mapping turns atoms into beads.")
step([("nodes.py", "Pipeline.bonded_build"), ("nodes.py", "Pipeline.stage"), ("runner.py", "call"), ("core/cgbuild.py", "cmd_bonded")],
     "`stage('bonded')` → `call(moldir, cgbuild.cmd_bonded, SimpleNamespace(moldir))`. `cmd_bonded` calls "
     "`derive_bonded.derive(moldir, ENV_PATH)` in the same process, with its printed output captured; output "
     "and any traceback are kept in `logs/derive_bonded.stdout` and `.stderr`.",
     "A call of {core/derive_bonded.py|derive}. On any exception: `decisions/bonded_failure.json` and a "
     "`StageError`, so the node reports stage 4 failed and the run is blocked.",
     "{core/derive_bonded.py|derive}.")
step([("core/derive_bonded.py", "derive")],
     "Reads the environment, `input/request.json` (SMILES `O=C1CCCCC1`, the `aa_topology` record) and "
     "`decisions/design.json` (beads O1, R2). Requires one connected molecule. Rebuilds `mol_h = "
     "AddHs(MolFromSmiles(SMILES))`, the same atom order as `atomistic.sdf` (heavy 0–6, H 7–16). T = 298.15 K; "
     "`bonded` settings: 300 conformers, 200 samples per minimum, 8 kcal/mol window.",
     "`smiles`, `req`, `des`, `mol_h`, settings.",
     "{core/derive_bonded.py|derive_ensemble}.")
step([("core/derive_bonded.py", "derive_ensemble"), ("core/derive_bonded.py", "get_topology"), ("core/d5bonded/opls.py", "load_supplied_topology"),
      ("core/d5bonded/opls.py", "check_supplied_topology"), ("core/d5bonded/opls.py", "OplsTopology")],
     "`get_topology`: the request has an `aa_topology` record, so `load_supplied_topology` checks that "
     "`input/aa_topology.top` exists and its SHA-256 equals the record from Step 16 (unchanged since input), "
     "then runs `check_supplied_topology` again (Steps 14–15: `GmxTopology`, `atom_permutation`).",
     "An `OplsTopology`: engine `supplied`, charge model `not stated`, `top` = `itp` = the file, `perm`, "
     "charges, source `supplied`, notes.",
     "{core/derive_bonded.py|energy_model}.")
step([("core/derive_bonded.py", "energy_model"), ("core/d5bonded/energy.py", "build_model"), ("core/d5bonded/energy.py", "GmxTopology.__init__"),
      ("core/d5bonded/energy.py", "OplsObc2.__init__"), ("core/d5bonded/energy.py", "GmxTopology.neighbours"),
      ("core/d5bonded/energy.py", "GmxTopology.excluded"), ("core/d5bonded/energy.py", "NumpyEnergy.__init__")],
     "**The AA topology becomes an energy function.** `build_model` parses the topology again and builds "
     "`OplsObc2`: polar hydrogens (H on N, O, S with σ = ε = 0) get σ 0.1 nm, ε 0.192 kJ/mol (none in CHXO); "
     "non-bonded pairs = all pairs not excluded within nrexcl = 3 bonds (`excluded` uses `neighbours`), with "
     "Coulomb `qq` and LJ A, C from the geometric combination rule; 1–4 pairs scaled by fudgeQQ and fudgeLJ "
     "0.5; bond, angle, RB and periodic parameters as arrays; GBSA-OBC2 radii (mbondi2) and screening factors. "
     "`NumpyEnergy` wraps it with `perm`, so it accepts coordinates in RDKit order, in Å and kcal/mol.",
     "`em`, named `supplied OPLS-AA (not stated) + GBSA-OBC2 + polar-H LJ ...`.",
     "{core/d5bonded/ensemble.py|d5_ensemble} as `energy_model`.")
step([("core/d5bonded/ensemble.py", "d5_ensemble"), ("core/d5bonded/ensemble.py", "dedup")],
     "**The SMILES becomes conformers again, now 300.** `AddHs`, ETKDGv3 with seed 20261031, 300 conformers "
     "without pruning; MMFF94 with distance-dependent dielectric ε = 4; each conformer minimised to "
     "convergence; `dedup` merges minima within 0.001 kcal/mol and heavy-atom best RMSD below 0.1 Å.",
     "The unique MMFF94 minima (chair and twist forms for cyclohexanone).",
     "Re-minimisation under the AA energy model (next step).")
step([("core/d5bonded/energy.py", "NumpyEnergy.minimize"), ("core/d5bonded/energy.py", "NumpyEnergy.energy_grad"),
      ("core/d5bonded/energy.py", "OplsObc2.energy_terms"), ("core/d5bonded/energy.py", "OplsObc2._bonded"),
      ("core/d5bonded/energy.py", "_angles"), ("core/d5bonded/energy.py", "_dihedrals"), ("core/d5bonded/energy.py", "OplsObc2._pairs"),
      ("core/d5bonded/energy.py", "OplsObc2._gb"), ("core/d5bonded/energy.py", "OplsObc2.born_radii")],
     "**The AA topology's energy reshapes each minimum.** `energy_grad` reorders RDKit coordinates to topology "
     "order (`perm`), converts Å to nm and calls `energy_terms`: `_bonded` (harmonic bonds, harmonic angles "
     "via `_angles`, RB and periodic dihedrals via `_dihedrals`, each with analytic gradient), `_pairs` "
     "(Coulomb + LJ for non-bonded pairs and for 1–4 pairs), `_gb` (Born radii from `born_radii`, the "
     "generalised-Born pair and self energies, ACE non-polar term). Returns energy in kcal/mol and gradient "
     "in RDKit order.",
     "Energy and gradient for the minimiser.",
     "The minimiser in the next step.")
step([("core/d5bonded/energy.py", "NumpyEnergy.minimize"), ("core/d5bonded/energy.py", "NumpyEnergy.preconditioner"),
      ("core/d5bonded/energy.py", "OplsObc2.bonded_gauss_newton"), ("core/d5bonded/energy.py", "NumpyEnergy.grad"),
      ("core/d5bonded/energy.py", "fy")],
     "30 plain L-BFGS-B iterations; then a preconditioner: `bonded_gauss_newton` builds Σ k·JᵀJ from the "
     "bonded terms, regularised and Cholesky-factored; L-BFGS-B in the whitened coordinates (`fy`); a plain "
     "polish if the largest gradient is still above 1e-4 kcal/mol/Å. Back in `d5_ensemble`: a minimum where "
     "atoms 3 or more bonds apart come closer than 1 Å is discarded (`collapsed`); energies are replaced by "
     "`NumpyEnergy.energy` and minima are de-duplicated again.",
     "CHXO: 3 unique minima under the OPLS + GBSA model, none collapsed.",
     "Hessians and weights (next step).")
step([("core/d5bonded/ensemble.py", "d5_ensemble"), ("core/d5bonded/ensemble.py", "_hessian"), ("core/d5bonded/ensemble.py", "modes"),
      ("core/d5bonded/ensemble.py", "_rigid_basis")],
     "For each minimum within 8 kcal/mol of the lowest: Hessian by central finite differences of "
     "`NumpyEnergy.grad` (51 × 51 for 17 atoms); `modes` projects out the 6 rigid-body directions "
     "(`_rigid_basis`) and diagonalises. A minimum with a non-positive eigenvalue is refined along that mode "
     "(up to 2 tries) or rejected. Log weight: −E/kT + ½ ln det I + ½ Σ ln(2πkT/λ) (harmonic superposition).",
     "Normalised weights: CHXO top weight 0.988 (chair), effective number of minima 1.02.",
     "Thermal sampling (next step).")
step([("core/d5bonded/ensemble.py", "d5_ensemble"), ("core/d5bonded/ensemble.py", "_rotors"), ("core/d5bonded/ensemble.py", "_torsion_generators"),
      ("core/d5bonded/ensemble.py", "_rotate"), ("core/d5bonded/ensemble.py", "_is_achiral"), ("core/d5bonded/ensemble.py", "D5Ensemble")],
     "200 samples per minimum from the harmonic distribution: `_rotors` finds rotatable acyclic single bonds "
     "(none in CHXO: ring bonds are not rotors and C–H/C=O ends have degree 1); stiff modes are drawn as small "
     "linear displacements (capped at 0.3 Å per mode); rotors would be applied as exact rotations "
     "(`_torsion_generators`, `_rotate`). Samples that stretch any bond by more than 0.3 Å are rejected (none). "
     "`_is_achiral` → true, so every sample is added again mirrored (z → −z).",
     "`D5Ensemble`: `xyz_nm` [1200 frames × 17 atoms × 3], `weights`, `minima`, `info` (n_conf 300, n_used 3, "
     "top_weight 0.988, mirrored).",
     "Back to {core/derive_bonded.py|derive_ensemble}, which returns `(em, t, ens, tried)` to "
     "{core/derive_bonded.py|derive}.")
step([("core/derive_bonded.py", "mapping_matrix")],
     "**The mapping enters stage 4.** Builds M [2 beads × 17 atoms] from the bead members; a hydrogen "
     "inherits its heavy atom's weight (unless its parent is in `hydrogen_excluded_parents`); each row is "
     "normalised to sum 1, so a bead position is the centre of geometry including hydrogens.",
     "M: O1 = O(1) + C(1) + C3(½) + C7(½) + the 4 H on C3 and C7 (½ each); R2 = C3(½) + C4 + C5 + C6 + "
     "C7(½) + their H.",
     "{core/d5bonded/terms.py|rigid_groups}, {core/d5bonded/terms.py|bead_masses}, {core/d5bonded/terms.py|build_terms}.")
step([("core/d5bonded/terms.py", "rigid_groups"), ("core/d5bonded/terms.py", "bead_masses")],
     "`rigid_groups`: rings that are aromatic or all-sp2, as sets of the beads that own their atoms; cyclohexanone "
     "has sp3 ring carbons → no rigid group. `bead_masses`: standard size masses (`SIZE_MASS`: R 72, S 54, T 36), "
     "virtual sites 0 with their mass passed to real beads (none here).",
     "`groups` [] ; masses [36, 72] (O1 TN6a is T, R2 C3 is R).",
     "`build_terms` and later `bonded.json` `masses`.")
step([("core/d5bonded/terms.py", "read_sigma"), ("core/d5bonded/terms.py", "sigma")],
     "Reads `[ nonbond_params ]` of `martini_v3.0.0.itp` for the bead types present.",
     "A function σ(i, j) in nm for the TN6a–C3 pair.",
     "`build_terms` (close-pair exclusion rule).")
step([("core/d5bonded/terms.py", "build_terms"), ("core/d5bonded/terms.py", "bead_graph")],
     "Bead coordinates `R = M·x` for every frame (nm). 2000 weighted frames give the mean bead-distance matrix "
     "`mean_d` and a representative frame `rep`. `bead_graph` joins two beads if an atom bond crosses between "
     "them or they share an atom.",
     "Bead graph `[(0, 1)]`; no rigid groups, no virtual beads.",
     "The term rules below, inside `build_terms`.")
step([("core/d5bonded/terms.py", "bond_term"), ("core/d5bonded/terms.py", "dist_vals"), ("core/d5bonded/geometry.py", "distances"),
      ("core/d5bonded/geometry.py", "_take"), ("core/d5bonded/fit.py", "fit_bond"), ("core/d5bonded/fit.py", "_norm"),
      ("core/d5bonded/terms.py", "bond_k_cap"), ("core/d5bonded/terms.py", "bead_size")],
     "Edge (0, 1) is outside any rigid group → a chain bond. `distances` measures the O1–R2 distance in every "
     "frame; `fit_bond` takes the weighted mean b0 and kb = kT / variance; `bond_k_cap` caps kb by bead size "
     "(T 20,000, R 40,000 → harmonic mean 26,667 kJ mol⁻¹ nm⁻²); a kb below 700 would be raised to 700.",
     "Bond b0 = 0.2045 nm, kb fitted 188,865 → capped to 26,667 (`capped` note kept, `kb_fit` kept).",
     "The term list of `build_terms`.")
step([("core/d5bonded/terms.py", "build_terms")],
     "Angles need a bead with two bonded neighbours, and dihedrals a chain of four beads: none with 2 beads. "
     "Close-pair rule: 2nd and 3rd bead neighbours closer than σ get an exclusion: none. Ring check: a ring whose "
     "atoms belong to exactly two bonded beads gets the `two_bead_ring_cog_length` flag.",
     "`dict(terms=[bond 0–1], dropped=[], exclusions=[], close_pairs=[], groups=[], flags=[two_bead_ring_cog_length "
     "0.204 nm])`.",
     "Back to {core/derive_bonded.py|derive}.")
step([("core/derive_bonded.py", "virtual_site_parameters"), ("core/derive_bonded.py", "to_record"), ("core/derive_bonded.py", "stats")],
     "Virtual-site coefficients by least squares (none here). Each term → `to_record`: term id `b1`, beads "
     "one-based [1, 2], parameters, evidence class, `limitations`, `fitted_before_limit`, and `stats` (weighted "
     "mean and spread of the ensemble).",
     "`b1`: bonds funct 1, b0 0.2045 nm, k 23687.1, limitations `bead-type cap 23687 kJ/mol/nm2 (TN6a-C3)` (the cap keeps a vibration period of at least 10 timesteps of 20 fs: reduced mass × (2π / 0.2 ps)²), "
     "ensemble mean 0.2045 std 0.0036 nm, kb_fit 188864.69.",
     "The output dictionary (next step).")
step([("core/derive_bonded.py", "derive"), ("core/derive_bonded.py", "software_versions")],
     "Saves 4000 weighted frames as bead and atom coordinates; collects flags (large charge, topology notes, "
     "collapsed minima, unsaturated conformer search: none apply); writes the record.",
     "`bonded/ensemble_beads.npz`, `bonded/ensemble_atoms.npz`, `decisions/bonded.json` (method, ensemble info, "
     "energy model, software, seed, rigid groups [], terms [b1], exclusions [], masses [36, 72], nrexcl 1, "
     "dropped [], flags). Prints `bonded CHXO: 1 terms, 0 exclusions, 0 dropped, engine supplied, 3 minima, "
     "neff 1.0, ...`.",
     "{core/cgbuild.py|cmd_bonded} prints it and returns; `bonded.json` is read by the build (Part H), the test, "
     "finalize and the SASA check; the `.npz` files by the SASA check (Step 96).")
step([("core/d5bonded/geometry.py", "angles"), ("core/d5bonded/geometry.py", "dihedrals"), ("core/d5bonded/fit.py", "fit_angle"),
      ("core/d5bonded/fit.py", "fit_dihedral"), ("core/d5bonded/terms.py", "angle_k_limit")],
     "(Not reached for CHXO; listed so the code path is complete.) With three or more beads, `build_terms` "
     "would fit angles with `fit_angle` (maximum-likelihood truncated Gaussian in cos θ, then the timestep "
     "cap `angle_k_limit`) and dihedrals with `fit_dihedral` (harmonic if single narrow peak, else a Fourier "
     "series; `dihedral_k_limit` caps the harmonic form), using `angles` and `dihedrals` from `geometry.py`. "
     "Rigid rings would use `triangulate`, `_improper` and `_position_term`. See Appendix B.",
     "Nothing for CHXO.",
     "–")

# ----------------------------------------------------------------- Part H
h2("Part H. Build: writing the Martini topology")
step([("nodes.py", "Pipeline.bonded_build"), ("nodes.py", "Pipeline.stage"), ("runner.py", "call"), ("core/cgbuild.py", "cmd_build"),
      ("core/cgbuild.py", "rjson")],
     "`stage('build')`. `cmd_build` reads `design.json` (beads, types, members), "
     "`request.json` and `bonded.json`; copies virtual-site coefficients from `bonded.json` into the design "
     "(none).",
     "The three records in memory.",
     "{core/cgbuild.py|load_conformers}.")
step([("core/cgbuild.py", "load_conformers"), ("core/cgbuild.py", "core_types"), ("core/cgbuild.py", "bead_weights")],
     "Reads the 10 conformers (`input/conformers.sdf`) and the selected one (`input/atomistic.sdf`). "
     "`bead_weights` builds, per bead, `{atom index: weight}` with hydrogens inheriting their heavy atom's "
     "weight (the same rule as `mapping_matrix`).",
     "`weights` (per bead) and `heavy` (per heavy atom, its beads and weights).",
     "The static checks (next step).")
step([("core/cgbuild.py", "chk"), ("core/cgbuild.py", "bead_size_issue"), ("core/cgbuild.py", "design_provenance"), ("core/cgbuild.py", "sha256")],
     "Static checks: heavy-atom coverage (every weight sum 1.0), bead members connected (search over atom "
     "neighbours), bead types in the core ITP, net charge 0 = formal charge 0. `bead_size_issue`: O1 has 3 heavy "
     "atoms in a T bead (issue) but carries a cited `size_exception` → pass; R2 has 4 in an R bead → no issue. "
     "`design_provenance`: the last `design_sha256` in `design_log.jsonl` equals the SHA-256 of `design.json` "
     "→ written by the design tool.",
     "Check records (all pass for CHXO).",
     "Collected in `static`, written in Step 84.")
step([("core/cgbuild.py", "bead_positions"), ("core/cgbuild.py", "cog")],
     "Bead positions for every conformer and the selected one: `cog` = weighted centre of the member atoms "
     "(nm). Virtual sites would be placed from their constructing beads, and their distance to the mapped "
     "position measured (none here).",
     "Selected-conformer bead centres: O1 (0.0685, −0.1256, 0.0097) nm, R2 (−0.0285, 0.0523, −0.0040) nm.",
     "The GRO writer (Step 83) and `mapping.json`.")
step([("core/cgbuild.py", "cmd_build"), ("core/cgbuild.py", "bead_size")],
     "Masses come from `bonded.json` (`masses.bead_amu` [36, 72]); a `mass_amu` in `design.json` would be "
     "ignored and listed. Total mass check: 108 = standard 36 + 72.",
     "`masses`.",
     "The `[ atoms ]` section (Step 82).")
step([("core/cgbuild.py", "cmd_build")],
     "Term records for `parameters.json`: each bonded term with bead ids and names; exclusions; nrexcl; "
     "virtual sites; masses. Term checks: no duplicates, no dihedral over an angle with θ0 > 160°, no bond k "
     "below 700, virtual-site distance below 0.05 nm, CG graph connected, rigid groups of at most 4 real beads.",
     "All term checks pass.",
     "`decisions/parameters.json` and the static check list.")
step([("core/cgbuild.py", "cmd_build")],
     "Writes the mapping and parameter records.",
     "`decisions/mapping.json` (beads with members, hydrogen members [O1: H 8, 9, 16, 17; R2: H 8–17], "
     "COG of the selected conformer, sources, typing ladder), `decisions/mapping_candidates.json`, "
     "`decisions/parameters.json`.",
     "The test (reads `parameters.json`) and `finalize`.")
step([("core/cgbuild.py", "cmd_build")],
     "**The topology is written.** Header with SMILES and energy model; `[ moleculetype ]` CHXO nrexcl 1; "
     "`[ atoms ]` one line per bead (type, name, charge, mass); `[ bonds ]` from `bonded.json` (`val` reads a "
     "named parameter); constraints, angles, dihedrals, virtual sites and exclusions sections when present.",
     "`model/molecule.itp` (shown below).",
     "The test copies it to `test/molecule.itp` (Step 86).")
code("""[ moleculetype ]
; molname  nrexcl
  CHXO  1

[ atoms ]
; id type resnr resname atom cgnr charge mass
  1   TN6a   1  CHXO  O1   1    0.000   36.0
  2   C3     1  CHXO  R2   2    0.000   72.0

[ bonds ]
; i j funct b0(nm) k(kJ/mol/nm2)
  1 2  1  0.204  23687  ; b1 chain""")
step([("core/cgbuild.py", "cmd_build")],
     "Writes the coordinates: box = max(4.5 nm, molecule extent + 3 nm); bead centres of the selected "
     "conformer, centred in the box.",
     "`model/molecule.gro`: O1 (2.299, 2.161, 2.257), R2 (2.201, 2.339, 2.243), box 4.5 nm.",
     "The test (solute coordinates).")
step([("core/cgbuild.py", "draw_mapping"), ("core/cgbuild.py", "cmd_build")],
     "Draws the 2D molecule with each atom labelled by its bead (and weight) and coloured per bead; writes "
     "the static checks; prints a summary.",
     "`model/mapping.svg`; `test/static_checks.json` (no fail).",
     "{nodes.py|Pipeline.bonded_build} reads `static_checks.json`: no `fail` → event with the bonded flags; "
     "{graph.py|after_build} → {nodes.py|Pipeline.test} (a fail → repair agent, if repairs remain).")

# ----------------------------------------------------------------- Part I
h2("Part I. GROMACS execution checks")
step([("nodes.py", "Pipeline.test"), ("nodes.py", "Pipeline.stage"), ("core/cgbuild.py", "cmd_test"), ("core/cgbuild.py", "make_mdps"),
      ("core/cgbuild.py", "read_mdp"), ("core/cgbuild.py", "mdp_set")],
     "`stage('test')`. Reads `design.json` and `parameters.json`; keeps an earlier `test/` as "
     "`test_attempts/attemptN`. Smoke length 100 ps / 0.02 ps = 5000 steps. `make_mdps` adapts the tutorial EM "
     "and equilibration MDPs and the production MDP with `mdp_set` (removes obsolete options, C-rescale "
     "barostat, 298.15 K, seed 20261031; eq1 10 fs × 10,000; eq2 20 fs × 25,000; smoke 20 fs × 5000, a frame "
     "every 1 ps).",
     "`test/em.mdp`, `eq1.mdp`, `eq2.mdp`, `smoke.mdp`, `mdp_adaptations.json`.",
     "The GROMACS runs.")
step([("core/cgbuild.py", "cmd_test"), ("core/cgbuild.py", "run_cmd")],
     "Copies `model/molecule.gro` → `test/solute.gro` and `model/molecule.itp` → `test/molecule.itp`; "
     "`gmx solvate` with the tutorial's Martini water box in a 4.5 nm box; counts W beads; writes the system "
     "topology with `#include` of the core, solvent and ion ITPs and `molecule.itp`.",
     "`test/solvated.gro` (885 W), `test/system.top` (`CHXO 1`, `W 885`).",
     "The four stages. (A charged molecule would first get NA/CL from `gmx genion`; CHXO is neutral.)")
step([("core/cgbuild.py", "cmd_test"), ("core/cgbuild.py", "run_cmd"), ("core/cgbuild.py", "grompp_notes"), ("core/cgbuild.py", "count_in"),
      ("core/cgbuild.py", "parse_em")],
     "For em, eq1, eq2 and smoke: `gmx grompp -maxwarn 0` (with the previous checkpoint for eq2 and smoke), "
     "`grompp_notes` collects NOTE/WARNING/ERROR text; `gmx mdrun -ntmpi 1 -ntomp GMX_THREADS -nb "
     "cpu` (a separate GROMACS process, started by `run_cmd`); `count_in` counts LINCS warnings; `Finished mdrun` must appear; `parse_em` reads the EM result.",
     "All four stages pass with the first seed (`test/retries.json`: one attempt). EM did not reach Fmax < 10 in 2001 steps (Fmax 45.5): recorded, not blocking; above 100 × the target, `report.md` would add an information note.",
     "Trajectory analysis (next step).")
step([("core/cgbuild.py", "cmd_test"), ("core/cgbuild.py", "read_gro_frames"), ("core/cgbuild.py", "measure"), ("core/cgbuild.py", "dist"),
      ("core/cgbuild.py", "xvg_avg")],
     "`gmx trjconv -pbc mol` → `smoke_frames.gro`; `read_gro_frames` reads the first 2 particles of each frame "
     "(101 frames); for every bonded term in `parameters.json` `measure` computes its value per frame "
     "(`dist` for bonds; `angle`, `dihedral`, `circ_mean` for angles and dihedrals); `gmx energy` and `xvg_avg` "
     "give potential, temperature, pressure and density.",
     "`test/execution.json`: b1 smoke mean 0.2031 nm (sd 0.009) against b0 0.2045 (ensemble sd 0.0036); "
     "T 298.8 K; density 988 kg/m³; finite coordinates. (These dynamics numbers differ slightly from run to "
     "run: GROMACS is multithreaded.)",
     "{nodes.py|Pipeline.test}.")
step([("nodes.py", "Pipeline.test"), ("graph.py", "after_test")],
     "Reads `execution.json`: every stage `pass` and exit 0. GROMACS runs are not bit-reproducible, so a failure is "
     "run again with `random_seed` + 1 and + 2 (`cgbuild.TEST_RETRY_SEEDS`) before repair; a pass with any seed "
     "continues and the attempts in `test/retries.json` become a flagged check (marginal stability) in "
     "`validation.json`. Only a failure with all three seeds goes to repair.",
     "`{stage_failed: '', events: ['test: all stages pass ...']}` and `test/retries.json`.",
     "`after_test` → {nodes.py|Pipeline.finalize} (a failure with repairs left → repair agent → "
     "{nodes.py|Pipeline.typing_gate} → stage 4 again).")
step([("nodes.py", "Pipeline.repair"), ("tools/reference_tools.py", "make_run_file_tool"), ("tools/reference_tools.py", "read_run_file")],
     "(Not reached for CHXO.) The repair agent gets the failure text and `design('show')`; it can read run "
     "files with `read_run_file` and change candidates, beads (`replace`), virtual sites or hydrogens through "
     "the design tools; bonded values cannot be edited.",
     "A changed design and `repairs` + 1.",
     "{nodes.py|Pipeline.typing_gate}, then Part G again.")

# ----------------------------------------------------------------- Part J
h2("Part J. Finalize, multi-seed and SASA checks, final message")
step([("nodes.py", "Pipeline.finalize"), ("nodes.py", "Pipeline.stage"), ("core/cgbuild.py", "cmd_finalize"), ("core/cgbuild.py", "classify")],
     "`stage('finalize')`. Reads design, request, parameters, mapping, analogue search, bonded, static "
     "checks and execution records. `classify` turns them into one check list (static checks, each stage, "
     "grompp warnings, LINCS, EM convergence, smoke geometry: bond mean within max(0.02 nm, half the bond's ensemble standard deviation) of b0, finite energies; a test that passed only with a later seed adds a flagged marginal-stability check) "
     "and a status: no static fail and all stages pass → `execution_checked`.",
     "`checks`, `status` = execution_checked.",
     "`validation.json` (next step).")
step([("core/cgbuild.py", "cmd_finalize"), ("core/cgbuild.py", "harness_provenance"),
      ("core/cgbuild.py", "gmx_version"), ("core/cgbuild.py", "design_provenance")],
     "Writes the validation record (status, checks, tested dynamics, provisional types, warnings) and the "
     "manifest: hashes of the model and Bible indexes, simulation dependencies, request, design, bonded, "
     "AA topology and code, the harness's version and source tree hash (`harness_provenance`: SHA-256 over every "
     "`.py`, `.md` and `.json` file of `martini_harness/`, prompts included), software versions, seeds, the "
     "authored-by record, the `cli replay` command that reproduces the model from its design log, flags.",
     "`validation.json` (provisional `R2:C3`; eq1 100 ps, eq2 500 ps, smoke 100 ps), `manifest.json`.",
     "{core/cgbuild.py|write_report}.")
step([("core/cgbuild.py", "write_report"), ("core/cgbuild.py", "fmt_params"), ("core/cgbuild.py", "file_hashes")],
     "Writes the report from the records only (status, SMILES, beads table, bonded terms with `fmt_params`, "
     "flags, checks, tested dynamics, unverified statements, limitations). An unverified statement is printed "
     "as `statement (label)`, the keys `design_note --unverified` stores; the code copied from the skill read "
     "`text`, `location` and `later_status` and raised `KeyError` (fixed 2026-11-20). CHXO's replay has none. Freezes `baseline/` (input, "
     "decisions, model, validation, manifest, report) and hashes it. (No code is copied into the run: the tree "
     "hash in the manifest identifies it.)",
     "`report.md`, `baseline/`, `baseline_hashes.json`.",
     "{nodes.py|Pipeline.finalize}, which next runs the multi-seed check.")
step([("nodes.py", "Pipeline.finalize"), ("runner.py", "call"), ("core/multi_seed_check.py", "check"), ("core/multi_seed_check.py", "run")],
     "`call(moldir, multi_seed_check.check, moldir/'multi_seed', [moldir])`. For seeds 11, 22, 33, 44 in "
     "parallel threads (each starting its own GROMACS processes): copies `test/em.mdp`, `eq2.mdp`, `system.top`, `molecule.itp`; "
     "`eq1.mdp` with `gen_seed` replaced; starts from `solvated.gro`; runs grompp and mdrun for em, eq1, eq2.",
     "`multi_seed/results.json`: 4 of 4 seeds `ok`, 0 LINCS warnings.",
     "{nodes.py|Pipeline.finalize}, which next runs the SASA check.")
step([("nodes.py", "Pipeline.finalize"), ("runner.py", "call"), ("core/sasa_check.py", "check"), ("core/sasa_check.py", "self_test"),
      ("core/sasa_check.py", "gmx_sasa")],
     "Self-test: an isolated R, S and T bead must give 4π(r + 0.191)² within 0.5% (`gmx sasa` silently "
     "guesses radii if names do not match).",
     "Passed: R 2.602, S 2.227, T 1.834 nm².",
     "`check_one` for the molecule, in the same process (a pool is used only for several molecules).")
step([("core/sasa_check.py", "check_one"), ("core/derive_bonded.py", "mapping_matrix"), ("core/sasa_check.py", "frames_vs_saved"),
      ("core/sasa_check.py", "aa_radii"), ("core/sasa_check.py", "bead_radius"), ("core/sasa_check.py", "checked_sasa"),
      ("core/sasa_check.py", "shrake_rupley"), ("core/sasa_check.py", "sphere_points"), ("core/sasa_check.py", "band")],
     "Reads request, design, bonded; the same mapping matrix M; the saved atom frames "
     "`bonded/ensemble_atoms.npz` (`regenerate_atoms` only if missing); maps them to beads and checks they match "
     "`ensemble_beads.npz` (`frames_vs_saved`); 200 frames; SASA of atoms (Rowland–Taylor radii, `aa_radii`) "
     "and of beads (R 0.264, S 0.230, T 0.191 nm, `bead_radius`) with `checked_sasa` = `gmx_sasa` cross-checked "
     "on 3 frames by `shrake_rupley`; `band` classifies the difference.",
     "Atoms 3.2931 nm², beads 2.8227 nm², difference −14.3% → band `flag`. `sasa/<label>/sasa.json`, "
     "`sasa/summary.json`.",
     "{nodes.py|Pipeline.finalize}, which reads `validation.json` and returns `status: execution_checked`.")
step([("nodes.py", "Pipeline.report"), ("models.py", "chat_model"), ("system_prompts.py", "system_prompt")],
     "Collects the events, status, `report.md`, `multi_seed/results.json`, `sasa/summary.json` and the bonded "
     "flags. In LLM mode the report model writes the final message from these records only (system prompt: "
     "`harness.md`, `tasks/report.md`, `stages/6_deliver.md`); in replay mode the records themselves are the "
     "message.",
     "`harness/final_message.md`; state `final_message`.",
     "END. {cli.py|run} then reads the final state and writes `status` and wall time into "
     "`harness/run.json`.")

# ----------------------------------------------------------------- Appendix A
story.append(PageBreak())
h2("Appendix A. Files: who writes them, who reads them")
table([["File (in the molecule folder)", "Written in step", "Read in steps"],
       ["`input/aa_topology.top`", "13 (flattened copy of the user's file)", "14, 59, 60 (and `regenerate_atoms` if needed)"],
       ["`input/atomistic.sdf`", "18", "20 and every design command (`target`), 76"],
       ["`input/conformers.sdf`", "18", "76"],
       ["`input/request.json`", "18", "20, 23, 54, 58, 59, 75, 91, 96"],
       ["`input/atoms.json`, `conformers.json`", "18", "records only"],
       ["`decisions/design.json`", "22 and every recording command (Parts D–F)", "23, 50, 51, 54, 56, 58, 75, 85, 91, 96"],
       ["`decisions/design_log.jsonl`", "22 and every recording command", "77 (`design_provenance`), 92"],
       ["`decisions/analogue_search.json`", "23, 54", "25, 35, 91"],
       ["`references/index/models.jsonl`, `ff300.jsonl`, `bible.jsonl` (prepared offline, Appendix D)", "—", "26 (once), then 23, 25, 40, 42, 46, 47, 51, 52"],
       ["`references/index/method_evidence.jsonl`", "—", "26, 47, 51, 52"],
       ["`decisions/bonded.json`", "73", "75, 79, 82, 91, 96, 97"],
       ["`bonded/ensemble_beads.npz`, `ensemble_atoms.npz`", "73", "96"],
       ["`decisions/mapping.json`, `parameters.json`, `mapping_candidates.json`", "81", "85, 88, 91"],
       ["`model/molecule.itp`", "82", "85, 86, 94"],
       ["`model/molecule.gro`", "83", "86"],
       ["`model/mapping.svg`", "84", "report"],
       ["`test/static_checks.json`", "84", "84 (node), 91"],
       ["`test/*.mdp`, `system.top`, `solvated.gro`", "85, 86", "87, 94"],
       ["`test/execution.json`", "88", "89, 91"],
       ["`validation.json`, `manifest.json`, `report.md`, `baseline/`", "92, 93", "97"],
       ["`logs/derive_bonded.*`, `logs/commands.jsonl` (GROMACS calls)", "57, 86, 87", "the reader"],
       ["`multi_seed/results.json`", "94", "97"],
       ["`sasa/summary.json`", "96", "97"],
       ["`harness/commands.jsonl` (every core call)", "8 (every `call`)", "the reader"],
       ["`harness/*` (state, events, trace, transcripts, run.json)", "6, 39, 43", "the reader"]],
      [62 * mm, 48 * mm, WIDTH - 110 * mm])

# ----------------------------------------------------------------- Appendix B
h2("Appendix B. Functions on the path that CHXO did not reach")
p("These functions are part of the same code path; a different molecule, an input without a topology, or a "
  "failure would run them. Line numbers as above.")
table([["Function", "Runs when", "What it does"],
       ["{core/d5bonded/opls.py|build_topology}, {core/d5bonded/opls.py|run_opls_ff_gen}, {core/d5bonded/opls.py|parse_itp}, "
        "{core/d5bonded/opls.py|has_charged_group}", "No AA topology supplied and `opls_ff_gen_command` set (Step 59)",
        "Runs the OPLS engine on the SMILES, parses its ITP, maps atoms with `atom_permutation`."],
       ["{core/d5bonded/terms.py|triangulate}, {core/d5bonded/terms.py|_improper}, {core/d5bonded/terms.py|_position_term}, "
        "{core/d5bonded/terms.py|_within_group_plus_one}, {core/d5bonded/terms.py|dihedral_k_limit}",
        "A ring that is aromatic or all-sp2 (rigid group), or a substituent on one",
        "Constraint triangle or rhombus, planarity improper, substituent bridge and position term."],
       ["{core/d5bonded/terms.py|angle_k_limit}, {core/d5bonded/fit.py|fit_angle}, {core/d5bonded/geometry.py|angles}",
        "Three or more beads in a chain", "Angle terms, capped by the 20 fs timestep rule."],
       ["{core/d5bonded/fit.py|fit_dihedral}, {core/d5bonded/fit.py|_circ_stats}, {core/d5bonded/fit.py|_hist}, "
        "{core/d5bonded/fit.py|n_peaks_circular}, {core/d5bonded/fit.py|potential}, {core/d5bonded/geometry.py|dihedrals}",
        "Four beads in a chain", "Harmonic or Fourier dihedrals."],
       ["{core/derive_bonded.py|virtual_site_parameters} (fit part)", "`design_vsite` with `virtual_sites3`",
        "Coefficients a, b by least squares on the ensemble."],
       ["{core/design.py|main}, {core/cgbuild.py|main}, {core/derive_bonded.py|main}, "
        "{core/multi_seed_check.py|main}, {core/sasa_check.py|main}", "Run by hand as `python -m martini_harness.core.<module>`",
        "Command-line wrappers around the same functions, for debugging; the harness does not use them."],
       ["{core/design.py|cmd_query}, {core/design.py|cmd_vsite}, {core/design.py|cmd_hydrogens}, {core/design.py|cmd_note}, "
        "{core/design.py|cmd_show}", "The agent calls those tools", "Add a query; declare a virtual site; exclude "
        "hydrogens; record a note (unverified notes are listed in `report.md`, Step 93); show the design (`show` is "
        "also used by the gates and repair)."],
       ["{core/cgbuild.py|angle}, {core/cgbuild.py|dihedral}, {core/cgbuild.py|circ_mean}", "Angle or dihedral terms exist",
        "Measure them in the smoke trajectory (Step 88)."],
       ["`cmd_test` ion branch (`grompp_ions`, `genion`)", "Net charge not 0", "Adds NA/CL counterions."],
       ["{core/sasa_check.py|regenerate_atoms}", "`bonded/ensemble_atoms.npz` missing", "Rebuilds the ensemble with "
        "the same seed."],
       ["{nodes.py|Pipeline.repair}", "A static check or a test fails", "Repair agent (Step 90); its task also carries the evidence per bead."],
       ["{core/design.py|cmd_candidate} refusal and `exception`", "A candidate breaks a mapping rule (Step 47)",
        "`[exit 2]` with the issues; accepted only with an `exception` naming an indexed reference."],
       ["{core/partition.py|_components} without a filler", "A leftover piece below 1.5 or above 4.5 heavy atoms",
        "The atoms stay `uncovered`; `building_blocks` lists Table 1 rows that fit them."],
       ["{core/design.py|print_method_record} with `values`", "`design_open` of a data table (`MEV:souza-si:T17/18/19`)",
        "Prints the partitioning free energies of every bead type (rung 3)."],
       ["{core/d5bonded/ensemble.py|D5Ensemble.as_trajectory}, {core/d5bonded/fit.py|fit_term}, "
        "{core/d5bonded/fit.py|implied_distribution}, {core/d5bonded/mapping.py|Mapping}", "Not called by the workflow",
        "Utilities kept in the package."]],
      [70 * mm, 45 * mm, WIDTH - 115 * mm])


# ----------------------------------------------------------------- Appendix C
story.append(PageBreak())
h2("Appendix C. Every Python file: what it is for and where to look")
p("Paths are relative to `customized_harness/`. Line counts on the build date. 'Called by' says who enters the file; "
  "the functions named are the places to put a breakpoint or a print when debugging.")


def nlines(rel):
    return sum(1 for _ in open(ROOT / rel))


PYFILES = [
    ("Orchestration (LangGraph, LangChain)", [
        ("martini_harness/__init__.py", "Package docstring and `__version__`; nothing else is imported at package level.", "—", "all"),
        ("martini_harness/cli.py", "Command line: `run` (live), `replay` (recorded design log, optional `--compare`), `graph` (Mermaid). Creates "
         "`runs/<label>-<UTC>/<ID>/`, writes `harness/run.json`, streams the graph and saves every state update.",
         "{cli.py|main}, {cli.py|run}, {cli.py|compare_designs}", "you"),
        ("martini_harness/config.py", "Reads `config/*.json` and the `environment.json` it names into {config.py|HarnessConfig}: models per "
         "node, limits, reference roots (`reference_roots`).", "{config.py|load_config}", "cli, nodes, tools, build_index"),
        ("martini_harness/graph.py", "Builds and compiles the `StateGraph`: nodes, fixed edges, routing functions (LLM and replay variants).",
         "{graph.py|build_graph}, {graph.py|after_mapping}, {graph.py|after_typing}, {graph.py|after_build}, {graph.py|after_test}", "cli"),
        ("martini_harness/nodes.py", "The state (`MolState`), the tools per agent node (`AGENT_TOOLS`) and every node as a `Pipeline` "
         "method; builds task messages (including the harness-prepared `propose` and `evidence` blocks) and runs agents.",
         "{nodes.py|Pipeline.run_agent}, {nodes.py|Pipeline.mapping}, {nodes.py|Pipeline.typing}, {nodes.py|Pipeline.typing_gate}", "graph"),
        ("martini_harness/runner.py", "The single bridge to `core`: runs a function in-process with output captured, errors turned into exit "
         "codes, one call at a time (lock), and logs each call to `harness/commands.jsonl`.", "{runner.py|call}, {runner.py|configure}", "nodes, design tools"),
        ("martini_harness/models.py", "OpenRouter chat models: API key from the environment or `.env`, one shared rate limiter, timeout in ms.",
         "{models.py|chat_model}, {models.py|node_models}", "nodes"),
        ("martini_harness/system_prompts.py", "Joins `prompts/harness.md`, `tasks/<node>.md`, `rules.md` and the node's stage files.",
         "{system_prompts.py|system_prompt}", "nodes"),
        ("martini_harness/trace.py", "LangChain callback writing every model and tool call to `harness/trace.jsonl`.",
         "{trace.py|JsonlTracer.on_llm_end}, {trace.py|JsonlTracer.on_tool_end}", "nodes"),
        ("martini_harness/tools/__init__.py", "Re-exports the tool factories.", "—", "nodes"),
        ("martini_harness/tools/common.py", "`ToolContext`: binds tools to one molecule folder and pages long outputs (`more_output`).",
         "{tools/common.py|ToolContext.page}", "all tools"),
        ("martini_harness/tools/design_tools.py", "One LangChain tool per design command (`SPECS`, pydantic schemas named like the command's "
         "arguments, so replay can feed logs back).", "{tools/design_tools.py|run_design}, {tools/design_tools.py|make_design_tools}", "nodes"),
        ("martini_harness/tools/reference_tools.py", "Read-only tools over `generation_reference_paths` (list, numbered read, grep, PDF page "
         "text) and `read_run_file` for repair.", "{tools/reference_tools.py|_resolve}, {tools/reference_tools.py|read_reference}", "nodes"),
    ]),
    ("Science (core): every deterministic calculation and check", [
        ("martini_harness/core/__init__.py", "Origin note (copied from build-martini-agent v16.2 on 2026-11-18, maintained here).", "—", "—"),
        ("martini_harness/core/cgbuild.py", "Stages `input`, `search`, `bonded`, `build`, `test`, `finalize`; loads the prepared indexes "
         "(`examples`, `method_evidence`); bead-size rule; ITP/GRO writing; GROMACS runs; provenance.",
         "{core/cgbuild.py|configure}, {core/cgbuild.py|examples}, {core/cgbuild.py|cmd_input}, {core/cgbuild.py|cmd_build}, "
         "{core/cgbuild.py|cmd_test}, {core/cgbuild.py|cmd_finalize}", "nodes (stages), design.py"),
        ("martini_harness/core/design.py", "The design record (`design.json` + `design_log.jsonl`): one `cmd_*` per decision; derives search "
         "queries; prints hits, references, precedents, projected partitions (`propose`) and per-bead evidence (`evidence`); verifies rung-1 "
         "claims by signature; checks completeness.",
         "{core/design.py|cmd_init}, {core/design.py|cmd_propose}, {core/design.py|cmd_candidate}, {core/design.py|cmd_evidence}, "
         "{core/design.py|cmd_bead}, {core/design.py|problems}", "design tools, nodes"),
        ("martini_harness/core/partition.py", "Mapping help: rule checks of a partition, bead-by-bead projection of reference models onto the "
         "target, candidate assembly and ranking, Table 1 building blocks inside a set of atoms.",
         "{core/partition.py|issues}, {core/partition.py|projections}, {core/partition.py|_place}, {core/partition.py|assemble}", "design.py"),
        ("martini_harness/core/refbeads.py", "Fragment signatures; parsers that turn `.ndx` mappings, CGSmiles and ITPs into bead views; "
         "CGSmiles placement and its symmetry test.",
         "{core/refbeads.py|fragment_signature}, {core/refbeads.py|ndx_beads}, {core/refbeads.py|resolve_on_molecule}", "design.py, partition.py, build_index"),
        ("martini_harness/core/derive_bonded.py", "Stage 4 driver: ensemble → bead positions → terms → `decisions/bonded.json`.",
         "{core/derive_bonded.py|derive}", "cgbuild `bonded`"),
        ("martini_harness/core/d5bonded/__init__.py", "Package note of the D5 bonded method (no MD).", "—", "—"),
        ("martini_harness/core/d5bonded/opls.py", "OPLS-AA topology: the supplied one (flatten, check, match atoms to the SMILES) or the "
         "engine fallback.", "{core/d5bonded/opls.py|check_supplied_topology}, {core/d5bonded/opls.py|atom_permutation}", "cgbuild `input`, stage 4"),
        ("martini_harness/core/d5bonded/energy.py", "OPLS-AA + GBSA-OBC2 energy, gradients, minimisation in NumPy (`GmxTopology`).",
         "{core/d5bonded/energy.py|GmxTopology.__init__}", "opls.py, ensemble.py"),
        ("martini_harness/core/d5bonded/ensemble.py", "Conformer minima, Hessians and the harmonic-superposition ensemble.",
         "{core/d5bonded/ensemble.py|D5Ensemble}", "derive_bonded"),
        ("martini_harness/core/d5bonded/mapping.py", "Atom-to-bead weight matrix (centre of geometry with hydrogens).",
         "{core/d5bonded/mapping.py|Mapping}", "derive_bonded"),
        ("martini_harness/core/d5bonded/geometry.py", "Distances, angles, dihedrals on bead trajectories.", "{core/d5bonded/geometry.py|distances}", "terms, fit"),
        ("martini_harness/core/d5bonded/terms.py", "Which bonded terms exist (rigid rings, chains, substituents) and their limits.",
         "{core/d5bonded/terms.py|triangulate}", "derive_bonded"),
        ("martini_harness/core/d5bonded/fit.py", "Boltzmann inversion of bonds, angles, dihedrals.", "{core/d5bonded/fit.py|fit_angle}", "terms"),
        ("martini_harness/core/multi_seed_check.py", "The model under four seeds.", "{core/multi_seed_check.py|check}", "nodes.finalize"),
        ("martini_harness/core/sasa_check.py", "SASA of the CG model against the atomistic ensemble.", "{core/sasa_check.py|check}", "nodes.finalize"),
    ]),
    ("Offline preparation", [
        ("martini_harness/build_index.py", "Builds `references/index/{models,ff300,bible,method_evidence}.jsonl` and `build_report.json` from "
         "`references/index/src/` and the Bible workbook (Appendix D). Deterministic; fails if a cited phrase is missing.",
         "{build_index.py|main}, {build_index.py|build_ff300}, {build_index.py|build_method_evidence}", "you (`python -m martini_harness.build_index`)"),
    ]),
    ("Tests and tools around the package", [
        ("tests/test_calls.py", "Refusals and failures as exit codes, argument checks, parallel tool calls, Bible lookups without openpyxl.", "—", "pytest"),
        ("tests/test_index.py", "Indexes rebuild byte-identically; memberships reproduce signatures; FF300 types from the ITPs; method "
         "excerpts equal the cited lines; Table 1 and Table 24 rows share one structure; the CHXO evidence selects the ketone row.", "—", "pytest"),
        ("tests/test_partition.py", "Projections find the recorded partitions of CHXO, PHAC, PIPL; candidate refusals and exceptions.", "—", "pytest"),
        ("tests/test_golden.py", "Replays the recorded CHXO, PHAC and PIPL designs and compares with `tests/golden/expected/`.", "—", "pytest"),
        ("tests/golden/golden.py", "Replay, snapshot (what must not change) and diff for the golden tests.", "—", "test_golden, make_golden"),
        ("tests/golden/make_golden.py", "Rewrites the expected snapshots; only for an intended change of outputs.", "—", "you"),
        ("docs/build_flow_pdf.py", "Builds this PDF; looks up line numbers at build time.", "—", "you"),
        ("runs/compare-*/analyze.py", "Summaries of comparison runs (calls, tokens, cost, beads, SASA, identical models).", "—", "you"),
        ("test.py", "An early one-call check of OpenRouter; not used by the harness.", "—", "—"),
    ]),
]
for title, rows in PYFILES:
    story.append(Paragraph(md(f"**{title}**"), BODY))
    story.append(Spacer(1, 2))
    data = [["File (lines)", "What it is for", "Where to look", "Called by"]]
    for rel, what, where, by in rows:
        n = nlines(rel) if (ROOT / rel).exists() else ""
        data.append([f"`{rel.replace('martini_harness/', '')}` ({n})", what, where, by])
    table(data, [42 * mm, 66 * mm, 50 * mm, WIDTH - 158 * mm])

# ----------------------------------------------------------------- Appendix D
story.append(PageBreak())
h2("Appendix D. Offline: how the reference indexes are built")
p("`python -m martini_harness.build_index` (about 2 s) turns hand-edited inputs into the four files runs read. It is "
  "the only place where mapping files, CGSmiles and ITPs are parsed; a run never re-derives them. Building twice gives "
  "byte-identical files (`tests/test_index.py`).")
table([["Input (edited by hand)", "Output", "Built by"],
       ["`references/index/src/models_catalog.jsonl` (SM3 models, PEO)", "`models.jsonl` (177 records)", "{build_index.py|build_models}"],
       ["`src/ff300_catalog.jsonl` + `src/ff300_curated.jsonl` (6 ionic-liquid mappings from Souza SI Fig. 16)", "`ff300.jsonl` (74)", "{build_index.py|build_ff300}"],
       ["Bible workbook `references/original/bible/src/MartiniCGSmilesDB_v6.xlsx`", "`bible.jsonl` (334)", "{build_index.py|build_bible}"],
       ["`src/method_evidence.jsonl` (IDs, locating phrases, statements, SMARTS)", "`method_evidence.jsonl` (130)", "{build_index.py|build_method_evidence}"],
       ["all of the above", "`build_report.json` (counts per support, every diagnostic)", "{build_index.py|report}"]],
      [80 * mm, 45 * mm, WIDTH - 125 * mm])
chain([
    ("build_index.py", "main", "configures `cgbuild` (core bead types), builds the four files, writes them atomically"),
    ("build_index.py", "build_models", "SM3: {core/refbeads.py|ndx_beads} per catalog entry; PEO: bead types from the polyply `.ff` ({core/refbeads.py|itp_moleculetype})"),
    ("build_index.py", "build_ff300", "per FF300 entry: curated mapping, or a single bead, or {build_index.py|placed_beads} of its CGSmiles; ITP types win ({build_index.py|itp_types_win})"),
    ("build_index.py", "build_bible", "per workbook row: {build_index.py|placed_beads} → {core/refbeads.py|cgsmiles_beads} + {core/refbeads.py|resolve_on_molecule}"),
    ("build_index.py", "example", "the common record; {build_index.py|support_of}; downgrade when a heavy atom is in no bead"),
    ("build_index.py", "build_method_evidence", "locates each phrase ({build_index.py|_find}, numbering as `grep -n`), copies the exact lines, parses Tables 17–19 ({build_index.py|_table_values}), checks SMARTS"),
    ("build_index.py", "write_jsonl", "one compact JSON record per line, no timestamps"),
])
table([["Field of an example record", "Meaning"],
       ["`id`, `collection`, `name`, `variant`", "`SM3:CYPO:opt`, `FF300:solvent:DMSO`, `BIBLE:row169`; a bead is `<id>:<bead name>`"],
       ["`molecule` {smiles, formal_charge, constitution, tautomer, smiles_check}", "member atoms are 1-based positions in this SMILES; identity keys for exposure"],
       ["`source` {path, locator, sha256, mapping_path, mapping_figure, aa_topology, doi, mapping_cgsmiles, mapping}", "where the model and its mapping come from"],
       ["`mapping_support`", "`atom_membership` (mapping precedent and rung-1 source), `fragment_signature` (rung 1 only), `bead_types_only`, `none`"],
       ["`mapping_origin`", "`ndx`, `single_bead`, `cgsmiles_placement`, `curated`"],
       ["`beads[]` {id, name, type, charge_e, signature, members, neighbours, source_atoms, fragment_cgsmiles, placement, diagnostic}", "the bead view"],
       ["`diagnostics`", "why a record is limited (e.g. SM3:4NIAN leaves a ring carbon in no bead)"]],
      [80 * mm, WIDTH - 80 * mm])
table([["Field of a method record", "Meaning"],
       ["`id`, `kind` (`method_rule`, `table_row`, `data_table`), `stage`", "`MEV:souza-si:T24:ketone`, `MEV:alessandri:T1:aromatic-c-oh`, `MEV:souza-si:T18`"],
       ["`statement`, `row` {bead, group, example, example_mapping, example_ref}", "what it says; for table rows the structured row (Table 1 rows name an example model)"],
       ["`applies_to` {core, all, bead_size}", "SMARTS the harness uses to select the row for a bead (Step 51)"],
       ["`source` {path, locator, sha256}, `excerpt`, `values`", "the exact cited lines; Tables 17–19 as numbers"]],
      [80 * mm, WIDTH - 80 * mm])

# ----------------------------------------------------------------- Appendix E
h2("Appendix E. Debugging guide: where to look when something goes wrong")
table([["Symptom", "Look at", "Then"],
       ["A run stops early or `status: blocked`", "`harness/events.log`, the last `harness/state/NN_*.json` (`failure`)", "The node named there; Parts B, C, G"],
       ["An agent made a wrong or odd decision", "`harness/transcripts/NN_<node>.json` (task message, every tool call and result), `decisions/design_log.jsonl`",
        "Replay the log (`cli replay --log`) to reproduce without a model"],
       ["A tool result surprised the agent", "`harness/trace.jsonl` (`tool_start`/`tool_end`), `harness/commands.jsonl` (exit code, output tails)",
        "Call the same command by hand: `run_design(ctx, '<cmd>', ...)` or `python -m martini_harness.core.design <cmd> <moldir> ...`"],
       ["Model errors, timeouts, rate limits", "`trace.jsonl` events `model_error`, `agent_error`", "{models.py|chat_model}, the config's limits"],
       ["Projected partitions look wrong", "`design propose` output in the mapping transcript", "{core/partition.py|_place} (placements), {core/partition.py|assemble} (completion, ranking)"],
       ["A rung-1 claim is refused", "the `[exit 2]` text: target vs source signature", "{core/design.py|cmd_bead}; `design_match` on the same atoms"],
       ["A reference record looks wrong", "`references/index/build_report.json` diagnostics; the record in `*.jsonl`", "{build_index.py|build_ff300} / `build_models` / `build_bible`; edit `src/`, rebuild"],
       ["Bonded terms look wrong", "`decisions/bonded.json`, `logs/derive_bonded.*`", "Part G; {core/derive_bonded.py|derive}"],
       ["A GROMACS stage fails", "`test/execution.json`, `logs/commands.jsonl`, `test/*.log`", "Part I; {core/cgbuild.py|cmd_test}"],
       ["Outputs changed after a code change", "`pytest tests` (golden diffs name the field)", "`tests/golden/make_golden.py` only for an intended change"]],
      [45 * mm, 70 * mm, WIDTH - 115 * mm])


def on_page(c, doc):
    c.saveState()
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(15 * mm, 9 * mm, f"Flow of information, CHXO — martini_harness {VERSION} — {BUILT}")
    c.drawRightString(A4[0] - 15 * mm, 9 * mm, f"page {doc.page}")
    c.restoreState()


OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                        bottomMargin=16 * mm, title="Flow of information: SMILES to Martini topology (CHXO)",
                        author="martini_harness documentation")
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print("steps:", step_no[0], "->", OUT)
