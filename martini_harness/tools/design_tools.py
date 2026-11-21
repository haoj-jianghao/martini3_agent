"""One LangChain tool per design command (martini_harness.core.design).

Each tool calls the command's cmd_* function directly, with the arguments `design.namespace` builds (the
command's defaults plus the tool's arguments), so every check in design.py applies unchanged and every call
lands in decisions/design_log.jsonl. Field names are design.py's own argument names, which lets the replay mode
feed a recorded design_log.jsonl straight back through these tools.
"""
from __future__ import annotations

from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core import design as D
from ..runner import CallResult, call
from .common import ToolContext


def run_design(ctx: ToolContext, cmd: str, **kw) -> CallResult:
    a = D.namespace(cmd, ctx.moldir, **kw)
    return call(ctx.moldir, a.fn, a, tag=f"design.{cmd}")


# ---------------------------------------------------------------- argument schemas
ATOMS = ("one-based atom ids from the atom table, comma separated; a shared atom carries its weight after a "
         "colon, for example '1,2,3:0.5'")


class NoArgs(BaseModel):
    pass


class HitsArgs(BaseModel):
    query: Optional[str] = Field(None, description="only hits of this query name")
    limit: int = Field(25, description="number of hits to list")


class QueryArgs(BaseModel):
    name: str = Field(description="short name for the new query")
    smarts: str = Field(description="SMARTS of the motif to search for")
    tags: Optional[str] = Field(None, description="comma-separated tags")


class RefArgs(BaseModel):
    ref: str = Field(description="reference id from design_hits or design_match, for example 'SM3:CHEX:opt' or "
                                 "'BIBLE:row169', or a method-evidence id such as 'MEV:souza-si:T18'")


class AnnotateArgs(BaseModel):
    ref: str = Field(description="an opened reference id")
    reason: str = Field(description="why this reference was used or not, for this molecule")
    used_for: Optional[str] = Field(None, description="what it was used for, if used")


class MatchArgs(BaseModel):
    atoms: str = Field(description=ATOMS)


class ProposeArgs(BaseModel):
    top: int = Field(25, description="number of most similar reference models to project")


class ResearchArgs(BaseModel):
    top: int = Field(25, description="number of most similar reference models to project")
    precedents: int = Field(2, description="references opened per bead as rung-1 sources")
    hits: int = Field(5, description="closest other search hits opened")


class EvidenceArgs(BaseModel):
    atoms: Optional[str] = Field(None, description="one bead's atoms (" + ATOMS + "); leave out for every bead of the chosen candidate")


class CandidateArgs(BaseModel):
    id: str = Field(description="candidate id, for example 'A'")
    beads: str = Field(description="beads separated by '|', each a list of atom ids with optional ':weight', "
                                   "for example '1,2,3|4,5:0.5,6'; weights of each atom must sum to one")
    summary: str = Field(description="one-sentence summary of this mapping")
    pros: str = Field(description="advantages separated by ';'")
    cons: str = Field(description="disadvantages separated by ';'")
    exception: Optional[str] = Field(None, description="only if the partition breaks a mapping rule on purpose: the reference "
                                                       "(REF_ID) whose published mapping does the same, and why")


class ChooseArgs(BaseModel):
    candidate: str = Field(description="id of the candidate to choose")
    rationale: str = Field(description="why this candidate over the others")


class BeadArgs(BaseModel):
    name: str = Field(description="bead name, for example 'B1'")
    atoms: str = Field(description=ATOMS + "; must equal a bead of the chosen candidate")
    rung: Literal[1, 2, 3] = Field(description="typing-ladder rung used")
    rationale: str = Field(description="for this bead: why these atoms and this type (unique per bead, at least 25 characters)")
    source_bead: Optional[str] = Field(None, description="rung 1 only: REF_ID:BEAD of an opened reference bead with the same fragment")
    type: Optional[str] = Field(None, description="rungs 2 and 3: bead type from the core force field (rung 1 copies it)")
    group: Optional[str] = Field(None, description="rung 2: documented chemical group (Souza SI Table 24/25)")
    rule: Optional[str] = Field(None, description="rung 2: SI C2 proximity rule applied")
    table: Optional[str] = Field(None, description="rung 3: partitioning table used")
    values: Optional[str] = Field(None, description="rung 3: values read from that table")
    rung2_finding: Optional[str] = Field(None, description="rung 3: why no documented group fits")
    sources: Optional[list[str]] = Field(None, description="rungs 2 and 3: one or more 'PATH:LOCATOR' citations")
    provisional: bool = Field(False, description="mark the type provisional (chemistry with no direct precedent)")
    rung1_rejection: Optional[str] = Field(None, description="rungs 2 and 3: why an available rung-1 precedent was not used")
    charge: float = Field(0.0, description="bead charge in e")
    size_exception: Optional[str] = Field(None, description="cited published model with the same atoms in a bead of this size")
    replace: bool = Field(False, description="redefine an existing bead of this name")


class VsiteArgs(BaseModel):
    site: int = Field(description="one-based index of the bead that becomes a virtual site")
    construction: Literal["virtual_sitesn_cog", "virtual_sites3"]
    constructing: str = Field(description="comma-separated one-based indices of the constructing beads")
    source: str = Field(description="PATH:LOCATOR of the published model or SI section followed")
    evidence_class: str = Field(description="evidence class, for example 'transferred' or 'adapted'")


class HydrogensArgs(BaseModel):
    excluded_parents: str = Field(description="comma-separated heavy-atom ids whose hydrogens are left out of bead centres")
    reason: str


class NoteArgs(BaseModel):
    unverified: Optional[str] = Field(None, description="a statement from background knowledge, not from a pinned file")
    limitation: Optional[str] = Field(None, description="an unresolved limitation")
    manual: Optional[str] = Field(None, description="a manual intervention (repairs)")


SPECS = [
    ("atoms", NoArgs, "Print the atom table of the molecule (one-based ids, elements, neighbours)."),
    ("hits", HitsArgs, "List reference hits ranked by similarity to the molecule."),
    ("query", QueryArgs, "Add a SMARTS query to the reference search when a motif is missing."),
    ("open", RefArgs, "Show a reference model bead by bead (type, member atoms, fragment signature) and record it as opened; "
                      "or show a method-evidence record (MEV:...) with its source text and citation."),
    ("annotate", AnnotateArgs, "Record why an opened reference was used or not."),
    ("match", MatchArgs, "List every indexed reference bead that holds exactly this fragment, with its type."),
    ("research", ResearchArgs, "The pipeline's research step: open and annotate the references the later steps need (no agent uses it; "
                               "replay re-runs it)."),
    ("evidence", EvidenceArgs, "Per bead: rung-1 precedents and the Souza SI Table 24/25 rows (or Tables 17-19) that apply, with citations."),
    ("propose", ProposeArgs, "Candidate partitions projected from the most similar reference models, with their sources."),
    ("candidate", CandidateArgs, "Record one mapping candidate (at most three); refused if it breaks the mapping rules."),
    ("choose", ChooseArgs, "Choose one recorded candidate."),
    ("hydrogens", HydrogensArgs, "Leave the hydrogens of some heavy atoms out of bead centres."),
    ("vsite", VsiteArgs, "Declare a virtual site and its construction."),
    ("bead", BeadArgs, "Record one bead with its type, typing rung, sources and charge."),
    ("note", NoteArgs, "Record an unverified statement, a limitation or a manual intervention."),
    ("show", NoArgs, "Show the current design and what it still lacks."),
    ("check", NoArgs, "Check the design; reports what is missing, or that it is complete."),
]


def make_design_tools(ctx: ToolContext, names: list[str] | None = None) -> list[StructuredTool]:
    tools = []
    for cmd, schema, desc in SPECS:
        if names is not None and cmd not in names:
            continue

        def fn(_cmd=cmd, **kw):
            return ctx.page(run_design(ctx, _cmd, **kw).text())

        tools.append(StructuredTool.from_function(func=fn, name=f"design_{cmd}", description=desc, args_schema=schema))
    return tools
