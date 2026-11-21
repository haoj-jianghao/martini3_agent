"""Command line of the harness.

  python -m martini_harness.cli run    --id CHXO --name cyclohexanone --smiles 'O=C1CCCCC1' --aa-topology chxo.top \
                                       [--config config/haiku.json] [--research agent|pipeline]
  python -m martini_harness.cli replay --id CHXO --name cyclohexanone --smiles 'O=C1CCCCC1' --aa-topology chxo.top \
                                       --log path/to/design_log.jsonl [--compare path/to/design.json]
  python -m martini_harness.cli graph  [--mode llm|replay]       print the graph as Mermaid

Each run writes runs/<label>-<UTC>/<ID>/ : the skill's usual molecule folder, plus harness/ with
  run.json            configuration, models and timing of the run
  events.log          one line per node
  state/NN_node.json  the state update of every node, in order
  trace.jsonl         every model and tool call
  transcripts/        the full message list of every agent node
  commands.jsonl      every script the harness ran
  final_message.md    the report node's message
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

from .config import load_config
from .graph import build_graph
from .nodes import Pipeline


def _utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def compare_designs(new: Path, old: Path) -> dict:
    a, b = json.loads(new.read_text()), json.loads(old.read_text())
    key = lambda d: sorted((x["name"], x["type"], tuple(sorted(x["members"].items())), x["typing_ladder"]["rung_used"]) for x in d["beads"])
    same = {"beads": key(a) == key(b), "chosen_candidate": a["chosen_candidate"] == b["chosen_candidate"],
            "candidates": [c["beads"] for c in a["mapping_candidates"]] == [c["beads"] for c in b["mapping_candidates"]],
            "opened": sorted(a["analogue_annotations"]) == sorted(b["analogue_annotations"]),
            "virtual_sites": a.get("virtual_sites") == b.get("virtual_sites")}
    return {"identical_decisions": all(same.values()), "fields": same,
            "new_beads": key(a), "recorded_beads": key(b)}


def run(args, mode: str) -> int:
    cfg = load_config(args.config)
    label = args.label or ("replay" if mode == "replay" else "llm")
    root = Path(args.runs_root).resolve() if args.runs_root else cfg.runs_root
    moldir = (root / f"{label}-{_utc()}" / args.id).resolve()
    (moldir / "harness/state").mkdir(parents=True, exist_ok=True)
    pipe = Pipeline(cfg, moldir, mode=mode, research=getattr(args, "research", None))
    app = build_graph(pipe)
    (moldir / "harness/graph.mmd").write_text(app.get_graph().draw_mermaid())
    nodes = ["research", "mapping", "typing", "repair", "report"]
    info = {"started_utc": _utc(), "mode": mode, "config": str(cfg.path), "martini_env": str(cfg.martini_env),
            "models": {n: cfg.model_for(n) for n in nodes} if mode == "llm" else None,
            "fallbacks": cfg.fallbacks if mode == "llm" else None, "limits": cfg.raw["limits"],
            "research": pipe.research_mode if mode == "llm" else None,
            "molecule": {"id": args.id, "name": args.name, "smiles": args.smiles,
                         "aa_topology": str(Path(args.aa_topology).resolve())}}
    (moldir / "harness/run.json").write_text(json.dumps(info, indent=1))
    state = {"mol_id": args.id, "name": args.name, "smiles": args.smiles,
             "aa_topology": str(Path(args.aa_topology).resolve()), "moldir": str(moldir), "mode": mode,
             "replay_log": str(Path(args.log).resolve()) if mode == "replay" else "", "events": []}
    print(f"molecule folder: {moldir}", flush=True)
    t0, k = time.time(), 0
    cfgrun = {"configurable": {"thread_id": args.id}, "recursion_limit": 200}
    log = (moldir / "harness/events.log").open("a")
    for upd in app.stream(state, config=cfgrun, stream_mode="updates"):
        for node, delta in upd.items():
            k += 1
            (moldir / f"harness/state/{k:02d}_{node}.json").write_text(json.dumps(delta, indent=1, default=str))
            for ev in (delta or {}).get("events", []):
                line = f"[{time.time() - t0:7.0f} s] {ev}"
                print(line, flush=True)
                log.write(line + "\n")
                log.flush()  # so the log can be followed while the run goes on
    log.close()
    final = app.get_state(cfgrun).values
    info.update({"finished_utc": _utc(), "wall_s": round(time.time() - t0), "status": final.get("status"),
                 "repairs": final.get("repairs", 0)})
    if mode == "replay" and args.compare:
        info["replay_comparison"] = compare_designs(moldir / "decisions/design.json", Path(args.compare))
        print(json.dumps(info["replay_comparison"], indent=1))
    (moldir / "harness/run.json").write_text(json.dumps(info, indent=1))
    print(f"\nstatus: {final.get('status')}   ({info['wall_s']} s)\nfinal message: {moldir / 'harness/final_message.md'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "replay"):
        q = sp.add_parser(name)
        q.add_argument("--id", required=True)
        q.add_argument("--name", required=True)
        q.add_argument("--smiles", required=True)
        q.add_argument("--aa-topology", required=True)
        q.add_argument("--config")
        q.add_argument("--label", help="run folder prefix (default: llm or replay)")
        q.add_argument("--runs-root", help="where run folders are created (default: runs_root of the config)")
        if name == "run":
            q.add_argument("--research", choices=["agent", "pipeline"],
                           help="research step: the deterministic pipeline step, or an LLM agent (default: `research` of the config, else pipeline)")
        if name == "replay":
            q.add_argument("--log", required=True, help="design_log.jsonl to replay")
            q.add_argument("--compare", help="design.json of the recorded run, to compare decisions")
    g = sp.add_parser("graph")
    g.add_argument("--mode", default="llm", choices=["llm", "replay"])
    g.add_argument("--config")
    a = ap.parse_args(argv)
    if a.cmd == "graph":
        cfg = load_config(a.config)
        print(build_graph(Pipeline(cfg, cfg.runs_root / "_graph", mode=a.mode)).get_graph().draw_mermaid())
        return 0
    return run(a, a.cmd if a.cmd == "replay" else "llm")


if __name__ == "__main__":
    sys.exit(main())
