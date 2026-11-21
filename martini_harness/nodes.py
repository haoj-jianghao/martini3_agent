"""The nodes of the per-molecule graph.

Deterministic nodes call martini_harness.core functions through `runner.call` and read the JSON records they write.
Agent nodes are LangChain agents (`create_agent`) that see only their own tools and the SKILL.md sections of
their stage. Gate nodes read the records to decide whether a step is complete; routing functions are in
graph.py.
"""
from __future__ import annotations

import json
import operator
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelFallbackMiddleware, ModelRetryMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, messages_to_dict

from .config import HarnessConfig
from .core import cgbuild, multi_seed_check, sasa_check
from .runner import call, configure
from .system_prompts import system_prompt
from .tools import (ToolContext, make_design_tools, make_reference_tools, make_run_file_tool, more_output_tool,
                    run_design)
from .trace import JsonlTracer


class MolState(TypedDict, total=False):
    mol_id: str
    name: str
    smiles: str
    aa_topology: str
    moldir: str
    mode: str                     # "llm" or "replay"
    replay_log: str
    init_output: str
    evidence: str                 # research agent's final answer
    mapping_summary: str          # mapping agent's final answer
    typing_summary: str
    feedback: str                 # gate message for the agent that is sent back
    attempts: dict
    repairs: int
    failure: str                  # what the last failed check reported
    stage_failed: str             # "build" or "test"
    status: str
    final_message: str
    events: Annotated[list[str], operator.add]


def _rjson(p: Path) -> Any:
    return json.loads(p.read_text()) if p.exists() else None


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n[... {len(s) - n} more characters]"


AGENT_TOOLS = {
    # node: (design.py commands, reference tools?, run-file tool?)
    "research": (["atoms", "hits", "query", "open", "annotate", "match", "note", "show"], True, False),
    "mapping": (["atoms", "hits", "open", "annotate", "match", "propose", "candidate", "choose", "hydrogens", "vsite", "note", "show"],
                True, False),
    "typing": (["atoms", "open", "annotate", "match", "evidence", "bead", "vsite", "note", "show", "check"], True, False),
    "repair": (["atoms", "open", "annotate", "match", "evidence", "propose", "candidate", "choose", "bead", "vsite", "hydrogens", "note", "show",
                "check"], True, True),
}


class Pipeline:
    def __init__(self, cfg: HarnessConfig, moldir: Path, mode: str = "llm", research: str | None = None):
        self.cfg = cfg
        self.moldir = moldir
        self.mode = mode
        self.ctx = ToolContext(cfg, moldir, max_chars=int(cfg.raw.get("tool_output_chars", 6000)))
        self.trace_path = moldir / "harness" / "trace.jsonl"
        self.max_repairs = int(cfg.env.get("max_repair_cycles", 3))
        self.research_mode = research or cfg.raw.get("research", "pipeline")   # "pipeline" (default) or "agent"
        if self.research_mode not in ("agent", "pipeline"):
            raise ValueError(f"research must be 'agent' or 'pipeline', not {self.research_mode!r}")
        configure(cfg)
        self._n = 0

    # ------------------------------------------------------------ helpers
    def _event(self, text: str) -> dict:
        return {"events": [text]}

    def _transcript(self, node: str, messages) -> None:
        self._n += 1
        p = self.moldir / "harness" / "transcripts" / f"{self._n:02d}_{node}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(messages_to_dict(messages), indent=1, default=str))

    def tools_for(self, node: str):
        cmds, refs, runfile = AGENT_TOOLS[node]
        tools = make_design_tools(self.ctx, cmds) + [more_output_tool(self.ctx)]
        if refs:
            tools += make_reference_tools(self.ctx)
        if runfile:
            tools.append(make_run_file_tool(self.ctx))
        return tools

    def run_agent(self, node: str, task: str, limit_key: str) -> str:
        from .models import node_models
        primary, fallbacks = node_models(self.cfg, node)
        middleware = [ModelCallLimitMiddleware(run_limit=self.cfg.limit(limit_key), exit_behavior="end"),
                      ModelRetryMiddleware(max_retries=int(self.cfg.raw.get("model_retries", 4)), initial_delay=5.0, max_delay=90.0)]
        if fallbacks:
            middleware.append(ModelFallbackMiddleware(*fallbacks))
        agent = create_agent(model=primary, tools=self.tools_for(node), system_prompt=system_prompt(self.cfg.prompts, node),
                             middleware=middleware, name=f"{node}_agent")
        tracer = JsonlTracer(self.trace_path, node)
        try:
            out = agent.invoke({"messages": [HumanMessage(task)]},
                               config={"callbacks": [tracer], "tags": [node], "recursion_limit": 4 * self.cfg.limit(limit_key) + 20})
        except Exception as e:  # recorded, the gate decides what happens next
            tracer._write({"event": "agent_error", "error": f"{type(e).__name__}: {e}"[:3000]})
            return f"[agent error] {type(e).__name__}: {e}"
        msgs = out["messages"]
        self._transcript(node, msgs)
        last = msgs[-1]
        text = getattr(last, "text", None)
        text = text() if callable(text) else text
        return text or str(last.content)

    def design(self, cmd: str, **kw) -> str:
        return run_design(self.ctx, cmd, **kw).text()

    def stage(self, cmd: str):
        """One cgbuild stage (bonded, build, test, finalize) on this molecule folder."""
        return call(self.moldir, cgbuild.COMMANDS[cmd], SimpleNamespace(moldir=str(self.moldir)), tag=f"cgbuild.{cmd}")

    # ------------------------------------------------------------ deterministic nodes
    def preflight(self, s: MolState) -> dict:
        if not Path(s["aa_topology"]).is_file():
            return {"status": "blocked", "failure": f"AA topology not found: {s['aa_topology']}",
                    **self._event("preflight: blocked")}
        return self._event("preflight: AA topology found")

    def intake(self, s: MolState) -> dict:
        a = SimpleNamespace(moldir=str(self.moldir), smiles=s["smiles"], id=s["mol_id"], name=s["name"], cls="",
                            stereo_note="", aa_topology=s["aa_topology"], aa_engine="", aa_charge_model="")
        r = call(self.moldir, cgbuild.cmd_input, a, tag="cgbuild.input")
        if not r.ok:
            return {"status": "blocked", "failure": "cgbuild input failed:\n" + r.text()[-3000:], **self._event("intake: failed")}
        model = "replay" if self.mode == "replay" else self.cfg.model_for("mapping")
        init = self.design("init", agent="langgraph-harness", model=model)
        if init.startswith("[exit"):
            return {"status": "blocked", "failure": "design init failed:\n" + init[-3000:], **self._event("intake: init failed")}
        return {"init_output": init, "attempts": {}, "repairs": 0, **self._event("intake: input frozen, design initialised")}

    def mapping_gate(self, s: MolState) -> dict:
        des = _rjson(self.moldir / "decisions/design.json") or {}
        att = dict(s.get("attempts") or {})
        if des.get("chosen_candidate"):
            pick, chosen = des.get("pipeline_choice"), des["chosen_candidate"]
            how = "" if not pick else (" (pipeline's choice confirmed)" if chosen == pick else f" (overrides the pipeline's {pick})")
            return {"feedback": "", **self._event(f"mapping gate: candidate {chosen} chosen{how}")}
        att["mapping"] = att.get("mapping", 0) + 1
        fb = ("No candidate was chosen. Record candidates with design_candidate and choose one with design_choose "
              "before finishing. Current design:\n" + self.design("show"))
        return {"attempts": att, "feedback": fb, **self._event(f"mapping gate: no choice (attempt {att['mapping']})")}

    def typing_gate(self, s: MolState) -> dict:
        r = run_design(self.ctx, "check")
        att = dict(s.get("attempts") or {})
        if r.ok:
            return {"feedback": "", **self._event("typing gate: design complete")}
        att["typing"] = att.get("typing", 0) + 1
        return {"attempts": att, "feedback": "design_check reports:\n" + r.text(),
                **self._event(f"typing gate: incomplete (attempt {att['typing']})")}

    def bonded_build(self, s: MolState) -> dict:
        r = self.stage("bonded")
        if not r.ok:
            fail = _rjson(self.moldir / "decisions/bonded_failure.json")
            return {"status": "blocked", "stage_failed": "bonded",
                    "failure": "stage 4 failed:\n" + (json.dumps(fail, indent=1) if fail else r.text()[-3000:]),
                    **self._event("bonded: failed")}
        r = self.stage("build")
        static = _rjson(self.moldir / "test/static_checks.json") or {"checks": []}
        fails = [c for c in static["checks"] if c.get("result") == "fail"]
        if not r.ok or fails:
            txt = (f"cgbuild build exit {r.code}\n{r.text()[-1500:]}\n" if not r.ok else "") + \
                  "failed static checks:\n" + json.dumps(fails, indent=1, default=str)
            return {"stage_failed": "build", "failure": _clip(txt, 6000),
                    **self._event(f"build: {len(fails)} static check(s) failed")}
        bonded = _rjson(self.moldir / "decisions/bonded.json") or {}
        flags = bonded.get("flags")
        return {"stage_failed": "", "failure": "", **self._event(f"bonded + build: ok; bonded flags: {flags}")}

    def test(self, s: MolState) -> dict:
        r = self.stage("test")
        exe = _rjson(self.moldir / "test/execution.json") or {}
        steps = {st.get("stage"): st.get("result") for st in exe.get("steps", [])}
        ok = r.ok and all(steps.get(k) == "pass" for k in ("em", "eq1", "eq2", "smoke"))
        if ok:
            return {"stage_failed": "", "failure": "", **self._event(f"test: all stages pass {steps}")}
        brief = {k: v for k, v in exe.items() if k in ("steps", "geometry_smoke")}
        return {"stage_failed": "test", "failure": _clip(f"cgbuild test exit {r.code}; stages {steps}\n"
                                                          + json.dumps(brief, indent=1, default=str), 6000),
                **self._event(f"test: failed {steps}")}

    def finalize(self, s: MolState) -> dict:
        r = self.stage("finalize")
        ev = [f"finalize: exit {r.code}"]
        if self.cfg.raw.get("run_multi_seed", True) and (self.moldir / "model/molecule.itp").exists():
            m = call(self.moldir, multi_seed_check.check, self.moldir / "multi_seed", [self.moldir], tag="multi_seed")
            ev.append(f"multi_seed: exit {m.code}")
        if self.cfg.raw.get("run_sasa", True) and (self.moldir / "bonded/ensemble_beads.npz").exists():
            m = call(self.moldir, sasa_check.check, self.moldir / "sasa", [self.moldir], tag="sasa")
            ev.append(f"sasa: exit {m.code}")
        val = _rjson(self.moldir / "validation.json") or {}
        return {"status": val.get("status", s.get("status") or "not_finalized"), "events": ev}

    # ------------------------------------------------------------ agent nodes
    def _fb(self, s: MolState) -> str:
        return f"\n\n# Feedback from the pipeline (fix this first)\n{s['feedback']}" if s.get("feedback") else ""

    def research(self, s: MolState) -> dict:
        if self.research_mode == "pipeline":
            # deterministic: open and annotate the references later steps need, and pass their evidence on
            out = self.design("research")
            if out.startswith("[exit"):
                return {"evidence": "", **self._event(f"research (pipeline): failed {out[:300]}")}
            n = out.count("\n  why: ")
            return {"evidence": out, **self._event(f"research (pipeline): {n} references opened and annotated")}
        # agent: a short first message, the atom table and the top hits only. The agent can list more with design_hits.
        n = int(self.cfg.raw.get("research_task_hits", 15))
        task = (f"Molecule {s['mol_id']} ({s['name']}), SMILES {s['smiles']}. `design.py init` has run.\n\n"
                f"# Atom table\n{self.design('atoms')}\n\n# Top {n} reference hits (design_hits lists more)\n"
                f"{self.design('hits', limit=n)}{self._fb(s)}")
        ans = self.run_agent("research", task, "research_model_calls")
        return {"evidence": ans, **self._event("research: done")}

    def mapping(self, s: MolState) -> dict:
        des = _rjson(self.moldir / "decisions/design.json") or {}
        pick = des.get("pipeline_choice")
        head = (f"# The pipeline has recorded and chosen {pick}\n{des.get('selection_rationale')}\n"
                f"Confirm it (finish without changing the choice) or override it (design_choose another recorded "
                f"candidate, or design_candidate a new one and choose it), with your reason.\n\n" if pick else "")
        task = (f"Molecule {s['mol_id']} ({s['name']}), SMILES {s['smiles']}.\n\n{head}# Atom table\n{self.design('atoms')}\n\n"
                f"# Partitions projected from reference models (prepared by the pipeline)\n{self.design('propose')}\n\n"
                f"# Evidence from the research step\n{s.get('evidence', '')}{self._fb(s)}")
        ans = self.run_agent("mapping", task, "mapping_model_calls")
        return {"mapping_summary": ans, **self._event("mapping: done")}

    def typing(self, s: MolState) -> dict:
        des = _rjson(self.moldir / "decisions/design.json") or {}
        cand = next((c for c in des.get("mapping_candidates", []) if c["id"] == des.get("chosen_candidate")), None)
        task = (f"Molecule {s['mol_id']} ({s['name']}), SMILES {s['smiles']}.\n\n# Atom table\n{self.design('atoms')}\n\n"
                f"# Chosen candidate (record exactly these beads)\n{json.dumps(cand, indent=1)}\n\n"
                f"# Evidence per bead (prepared by the pipeline: rung-1 precedents and the method records that apply)\n"
                f"{self.design('evidence')}\n\n"
                f"# Mapping step's summary\n{s.get('mapping_summary', '')}\n\n"
                f"# Evidence summary\n{s.get('evidence', '')}{self._fb(s)}")
        ans = self.run_agent("typing", task, "typing_model_calls")
        return {"typing_summary": ans, **self._event("typing: done")}

    def repair(self, s: MolState) -> dict:
        n = s.get("repairs", 0) + 1
        task = (f"Repair {n} of at most {self.max_repairs} for molecule {s['mol_id']} ({s['name']}), SMILES {s['smiles']}.\n\n"
                f"# What failed (stage: {s.get('stage_failed')})\n{s.get('failure', '')}\n\n# Current design\n{self.design('show')}\n\n"
                f"# Evidence per bead of the chosen candidate\n{self.design('evidence')}")
        ans = self.run_agent("repair", task, "repair_model_calls")
        return {"repairs": n, "feedback": "", **self._event(f"repair {n}: {ans[:300]}")}

    def replay(self, s: MolState) -> dict:
        """Re-issue a recorded design_log.jsonl through the same tools the agents use (no LLM)."""
        tools = {t.name: t for t in make_design_tools(self.ctx)}
        n_ok, errors = 0, []
        for line in Path(s["replay_log"]).read_text().splitlines():
            rec = json.loads(line)
            if rec["command"] == "init":
                continue
            tool = tools[f"design_{rec['command']}"]
            fields = tool.args_schema.model_fields
            args = {k: v for k, v in rec["args"].items() if k in fields}
            out = tool.invoke(args)
            if str(out).startswith("[exit") and rec["command"] != "check":
                errors.append(f"{rec['command']}: {str(out)[:400]}")
            else:
                n_ok += 1
        return {"evidence": "replayed", "mapping_summary": "replayed",
                **self._event(f"replay: {n_ok} commands ok, {len(errors)} errors" + ("".join("\n  " + e for e in errors)))}

    def report(self, s: MolState) -> dict:
        md = self.moldir
        parts = {"report.md": (md / "report.md"), "bonded flags": None, "multi_seed": md / "multi_seed/results.json",
                 "sasa": md / "sasa/summary.json"}
        rec = [f"Pipeline events:\n" + "\n".join(s.get("events", [])), f"Status: {s.get('status')}",
               f"Repairs: {s.get('repairs', 0)}"]
        if s.get("failure"):
            rec.append(f"Last failure:\n{s['failure']}")
        for k, p in parts.items():
            if p is not None and p.exists():
                rec.append(f"# {k}\n{_clip(p.read_text(), 12000)}")
        bonded = _rjson(md / "decisions/bonded.json")
        if bonded:
            rec.append(f"# bonded.json flags\n{json.dumps(bonded.get('flags'), indent=1, default=str)}")
        records = "\n\n".join(rec)
        if self.mode == "llm" and self.cfg.raw.get("run_report_agent", True):
            from .models import chat_model
            model = chat_model(self.cfg, self.cfg.model_for("report"))
            tracer = JsonlTracer(self.trace_path, "report")
            try:
                msg = model.invoke([SystemMessage(system_prompt(self.cfg.prompts, "report")), HumanMessage(records)],
                                   config={"callbacks": [tracer]})
                text = msg.text() if callable(getattr(msg, "text", None)) else (msg.text or str(msg.content))
            except Exception as e:
                text = f"[report model failed: {type(e).__name__}: {e}]\n\n{records}"
        else:
            text = records
        (md / "harness").mkdir(exist_ok=True)
        (md / "harness/final_message.md").write_text(text + "\n")
        return {"final_message": text, **self._event("report: written to harness/final_message.md")}
