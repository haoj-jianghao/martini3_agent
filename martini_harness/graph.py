"""The per-molecule LangGraph.

    START -> preflight -> intake -> research -> mapping -> mapping_gate -> typing -> typing_gate
          -> bonded_build -> test -> finalize -> report -> END

    research      command fails -> report (blocked). No complete partition within the rules: mapping records its own
                  (profile mapping_open); otherwise mapping chooses among the supplied P1-P3
    mapping_gate  no choice     -> mapping again (up to gate_retries), then report (blocked)
    typing_gate   incomplete    -> typing again (up to gate_retries), then report (blocked)
    bonded_build  stage 4 fails -> report (blocked: not repairable by the agent)
                  static fail   -> repair (repairs left) or finalize (status blocked)
    test          fails         -> repair (repairs left) or finalize
    repair                      -> typing_gate (design_check, then bonded_build again)

In replay mode the three agent nodes are replaced by one `replay` node that re-issues a recorded
design_log.jsonl through the same tools; everything else is identical.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import MolState, Pipeline


def build_graph(p: Pipeline):
    g = StateGraph(MolState)
    det = ["preflight", "intake", "mapping_gate", "typing_gate", "bonded_build", "test", "finalize", "report"]
    for n in det:
        g.add_node(n, getattr(p, n))
    retries = p.cfg.limit("gate_retries")

    def blocked(s):
        return s.get("status") == "blocked"

    g.add_edge(START, "preflight")
    g.add_conditional_edges("preflight", lambda s: "report" if blocked(s) else "intake", ["intake", "report"])

    if p.mode == "replay":
        g.add_node("replay", p.replay)
        g.add_conditional_edges("intake", lambda s: "report" if blocked(s) else "replay", ["replay", "report"])
        g.add_edge("replay", "mapping_gate")
        g.add_conditional_edges("mapping_gate", lambda s: "typing_gate" if not s.get("feedback") else "report",
                                ["typing_gate", "report"])
    else:
        for n in ("research", "mapping", "typing", "repair"):
            g.add_node(n, getattr(p, n))
        g.add_conditional_edges("intake", lambda s: "report" if blocked(s) else "research", ["research", "report"])
        g.add_conditional_edges("research", lambda s: "report" if blocked(s) else "mapping", ["mapping", "report"])
        g.add_edge("mapping", "mapping_gate")

        def after_mapping(s):
            if not s.get("feedback"):
                return "typing"
            return "mapping" if s["attempts"].get("mapping", 0) <= retries else "report"

        g.add_conditional_edges("mapping_gate", after_mapping, ["typing", "mapping", "report"])
        g.add_edge("typing", "typing_gate")
        g.add_edge("repair", "typing_gate")

    def after_typing(s):
        if not s.get("feedback"):
            return "bonded_build"
        if p.mode == "llm" and s["attempts"].get("typing", 0) <= retries:
            return "typing"
        return "report"

    g.add_conditional_edges("typing_gate", after_typing, ["bonded_build", "report"] + (["typing"] if p.mode == "llm" else []))

    def can_repair(s):
        return p.mode == "llm" and s.get("repairs", 0) < p.max_repairs

    def after_build(s):
        if s.get("stage_failed") == "bonded":
            return "report"
        if s.get("stage_failed") == "build":
            return "repair" if can_repair(s) else "finalize"
        return "test"

    def after_test(s):
        if s.get("stage_failed") == "test" and can_repair(s):
            return "repair"
        return "finalize"

    targets_build = ["report", "finalize", "test"] + (["repair"] if p.mode == "llm" else [])
    targets_test = ["finalize"] + (["repair"] if p.mode == "llm" else [])
    g.add_conditional_edges("bonded_build", after_build, targets_build)
    g.add_conditional_edges("test", after_test, targets_test)
    g.add_edge("finalize", "report")
    g.add_edge("report", END)
    # In-memory checkpoints: every step's state can be inspected during the run (app.get_state_history).
    return g.compile(checkpointer=InMemorySaver())
