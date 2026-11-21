"""Read-only access to the pinned references, and to this molecule's own run folder.

Paths are given and shown relative to the Martini project root, which is the form design.py expects in
`--source PATH:LOCATOR`. Any path outside the environment's generation_reference_paths is refused, so an agent
cannot read other runs, benchmarks or the skill's code.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .common import ToolContext


def _resolve(root: Path, allowed: list[Path], rel: str) -> Path | str:
    p = (root / rel.strip().lstrip("/")).resolve()
    if not any(p == a or a in p.parents for a in allowed):
        return f"[exit 1]\n{rel!r} is outside the readable folders: " + ", ".join(str(a.relative_to(root)) for a in allowed)
    if not p.exists():
        return f"[exit 1]\n{rel!r} does not exist"
    return p


class ListArgs(BaseModel):
    path: str = Field("", description="folder relative to the project root; empty lists the readable roots")


class ReadArgs(BaseModel):
    path: str = Field(description="text file relative to the project root")
    start_line: int = Field(1, description="first line (one-based)")
    n_lines: int = Field(150, description="number of lines")


class GrepArgs(BaseModel):
    pattern: str = Field(description="extended regular expression (case-insensitive)")
    path: str = Field("references/derived", description="file or folder relative to the project root")
    max_hits: int = Field(40)


class PdfArgs(BaseModel):
    path: str = Field(description="PDF relative to the project root")
    page: int = Field(description="one-based page number of the PDF file")


class RunFileArgs(BaseModel):
    path: str = Field(description="file relative to the molecule folder, for example 'test/static_checks.json'")
    start_line: int = 1
    n_lines: int = 200


def make_reference_tools(ctx: ToolContext) -> list[StructuredTool]:
    root = ctx.cfg.project
    allowed = ctx.cfg.reference_roots()

    def rel(p: Path) -> str:
        return str(p.relative_to(root))

    def list_references(path: str = "") -> str:
        if not path.strip():
            return "\n".join(rel(a) + "/" for a in allowed)
        p = _resolve(root, allowed, path)
        if isinstance(p, str):
            return p
        if p.is_file():
            return rel(p)
        rows = [rel(c) + ("/" if c.is_dir() else "") for c in sorted(p.iterdir()) if c.name != ".git"]
        return ctx.page("\n".join(rows) or "(empty)")

    def read_reference(path: str, start_line: int = 1, n_lines: int = 150) -> str:
        p = _resolve(root, allowed, path)
        if isinstance(p, str):
            return p
        if p.is_dir() or p.suffix.lower() in (".pdf", ".zip", ".xlsx", ".png", ".jpg"):
            return f"[exit 1]\n{path} is not a text file (use pdf_page_text for PDFs)"
        lines = p.read_text(errors="replace").split("\n")   # numbered as grep -n does (form feeds are not line breaks)
        s = max(1, start_line)
        chunk = lines[s - 1: s - 1 + max(1, min(n_lines, 400))]
        body = "\n".join(f"{s + i:6d}  {l}" for i, l in enumerate(chunk))
        return ctx.page(f"{rel(p)} lines {s}-{s + len(chunk) - 1} of {len(lines)}\n{body}")

    def grep_references(pattern: str, path: str = "references/derived", max_hits: int = 40) -> str:
        p = _resolve(root, allowed, path)
        if isinstance(p, str):
            return p
        r = subprocess.run(["grep", "-rniIE", "--exclude-dir=.git", "-m", "20", pattern, str(p)],
                           capture_output=True, text=True, timeout=60)
        hits = [h.replace(str(root) + "/", "") for h in r.stdout.splitlines()]
        out = "\n".join(h[:300] for h in hits[:max_hits])
        more = f"\n[{len(hits) - max_hits} more hits; narrow the pattern or path]" if len(hits) > max_hits else ""
        return ctx.page((out or "no match") + more)

    def pdf_page_text(path: str, page: int) -> str:
        p = _resolve(root, allowed, path)
        if isinstance(p, str):
            return p
        r = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(p), "-"],
                           capture_output=True, text=True, timeout=60)
        return ctx.page(r.stdout if r.returncode == 0 else f"[exit {r.returncode}]\n{r.stderr}")

    return [
        StructuredTool.from_function(func=list_references, name="list_references", args_schema=ListArgs,
                                     description="List the readable reference folders, or the content of one."),
        StructuredTool.from_function(func=read_reference, name="read_reference", args_schema=ReadArgs,
                                     description="Read lines of a reference text file (numbered, for citing)."),
        StructuredTool.from_function(func=grep_references, name="grep_references", args_schema=GrepArgs,
                                     description="Search reference text files with a regular expression."),
        StructuredTool.from_function(func=pdf_page_text, name="pdf_page_text", args_schema=PdfArgs,
                                     description="Text of one page of a reference PDF."),
    ]


def make_run_file_tool(ctx: ToolContext) -> StructuredTool:
    md = ctx.moldir.resolve()

    def read_run_file(path: str, start_line: int = 1, n_lines: int = 200) -> str:
        p = (md / path.strip().lstrip("/")).resolve()
        if md not in p.parents or not p.is_file():
            return f"[exit 1]\n{path!r} is not a file of this molecule folder"
        lines = p.read_text(errors="replace").split("\n")   # numbered as grep -n does (form feeds are not line breaks)
        s = max(1, start_line)
        return ctx.page("\n".join(lines[s - 1: s - 1 + n_lines]) or "(empty)")

    return StructuredTool.from_function(func=read_run_file, name="read_run_file", args_schema=RunFileArgs,
                                        description="Read a file of this molecule's run folder (checks, logs, records).")
