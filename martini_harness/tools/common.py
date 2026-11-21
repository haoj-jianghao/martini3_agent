"""Shared state of the tools of one molecule run: the folder they are bound to and long-output paging."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..config import HarnessConfig


@dataclass
class ToolContext:
    cfg: HarnessConfig
    moldir: Path
    max_chars: int = 6000
    _pages: dict = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def page(self, text: str) -> str:
        """Return text, or its first page plus a handle for `more_output` when it is long."""
        if len(text) <= self.max_chars:
            return text
        h = f"out{next(self._ids)}"
        self._pages[h] = text
        n = -(-len(text) // self.max_chars)
        return (text[: self.max_chars] + f"\n[output truncated: page 1 of {n}; "
                f"call more_output(handle='{h}', page=2) for the rest]")

    def more(self, handle: str, page: int) -> str:
        text = self._pages.get(handle)
        if text is None:
            return f"[exit 1]\nno output stored under handle {handle!r}"
        n = -(-len(text) // self.max_chars)
        if not 1 <= page <= n:
            return f"[exit 1]\npage must be between 1 and {n}"
        chunk = text[(page - 1) * self.max_chars: page * self.max_chars]
        tail = f"\n[page {page} of {n}" + (f"; next: more_output(handle='{handle}', page={page + 1})]" if page < n else "]")
        return chunk + tail


class MoreOutputArgs(BaseModel):
    handle: str = Field(description="handle given in a truncated tool result, for example 'out3'")
    page: int = Field(2, description="page number, starting at 1")


def more_output_tool(ctx: ToolContext) -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda handle, page=2: ctx.more(handle, page), name="more_output", args_schema=MoreOutputArgs,
        description="Show another page of a tool result that was truncated.")
