"""System prompts of the agent nodes, put together from the files in martini_harness/prompts/.

    harness.md         how the pipeline works: tools, references, `[exit N]`
    tasks/<node>.md    what this step does, what it must not do yet, what its final answer contains
    rules.md           rules, method and experiment boundary (every node except report)
    stages/*.md        the method's stages this node works on (NODE_STAGES)

The stage texts are the method's own (taken from build-martini-agent SKILL.md v16.2 and kept here); edit them
when the method changes, and the task files when a step should do something else.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"

NODE_STAGES = {
    "research": ["2_mapping"],
    "mapping": ["2_mapping", "4_bonded"],
    "mapping_open": ["2_mapping", "4_bonded"],     # the mapping node when the pipeline supplied no partition
    "typing": ["3_typing"],
    "repair": ["2_mapping", "3_typing", "4_bonded", "5_check"],
    "report": ["6_deliver"],
}


@lru_cache(maxsize=32)
def _read(prompts_dir: Path, rel: str) -> str:
    return (prompts_dir / rel).read_text().strip()


def system_prompt(prompts_dir: Path, node: str) -> str:
    """Raises KeyError for an unknown node and FileNotFoundError for a missing prompt file."""
    parts = [_read(prompts_dir, "harness.md"), _read(prompts_dir, f"tasks/{node}.md"), "# Method"]
    if node != "report":
        parts.append(_read(prompts_dir, "rules.md"))
    parts += [_read(prompts_dir, f"stages/{s}.md") for s in NODE_STAGES[node]]
    return "\n\n".join(parts) + "\n"
