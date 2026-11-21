"""Prepare the reference indexes offline: `python -m martini_harness.build_index [--config CONFIG]`.

Inputs (edited by hand) in references/index/src/, outputs in references/index/ (paths from environment.json
`indexes`):

  src/models_catalog.jsonl (SM3, POLYPLY-M3)          -> models.jsonl
  src/ff300_catalog.jsonl + src/ff300_curated.jsonl   -> ff300.jsonl
  the Bible workbook (references/original/bible/src)  -> bible.jsonl
  src/method_evidence.jsonl                           -> method_evidence.jsonl
  everything above                                    -> build_report.json (counts and every diagnostic)

The three example files share one schema, one record per reference model (see `example`). A record says what
it can support in `mapping_support`:
  atom_membership     every bead has its member atoms and weights: a mapping precedent and rung-1 typing
  fragment_signature  bead signatures are verified but the member atoms are not determined: rung-1 typing only
  bead_types_only     documented bead types without an atom mapping: an adaptation precedent only
  none                not resolved; `diagnostics` says why
and in `mapping_origin` where the memberships come from: ndx (mapping file), single_bead, cgsmiles_placement
(the CGSmiles fragments fit the molecule in one way, up to symmetry) or curated (src/ff300_curated.jsonl, with
its source). Member atoms are 1-based heavy-atom positions in `molecule.smiles` (RDKit MolFromSmiles order).

Method-evidence records are located in their source text by a phrase (`find`, optionally `after` and `until`);
the builder copies the exact lines as `excerpt` and fails if a phrase is not found. Table rows (Souza SI Tables
24/25, Alessandri 2022 Table 1) share one structure: `row` {bead, group[, example, example_mapping, example_ref]}
and `applies_to` {core: SMARTS lying inside the bead, all: atom SMARTS for every bead atom, bead_size: [T|S|R]}. Runs only read the outputs.
The output is deterministic: building twice gives identical files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

from rdkit import Chem

from .config import load_config
from .core import cgbuild, refbeads

SRC = Path("references/index/src")
WORKBOOK = Path("references/original/bible/src/MartiniCGSmilesDB_v6.xlsx")
TABLE_COLUMNS = ["HDW", "OCOW", "CLFW", "ETHW", "BENZW", "CHEXW", "hydration", "vaporization"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------------ example records

def identity(smiles):
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None, None, None
    return mol, Chem.MolToSmiles(mol, isomericSmiles=False), cgbuild.tautomer_key(mol)


def bead(rid, b, charge=None):
    out = {"id": f"{rid}:{b['name']}", "name": b["name"], "type": b.get("type"),
           "charge_e": b.get("charge_e", charge), "signature": b.get("signature"), "members": b.get("members"),
           "neighbours": b.get("neighbours", [])}
    for k in ("source_atoms", "fragment_cgsmiles", "placement"):
        if b.get(k) is not None:
            out[k] = b[k]
    if b.get("signature_error"):
        out["diagnostic"] = b["signature_error"]
    return out


def support_of(beads):
    if beads and all(b["members"] for b in beads):
        return "atom_membership"
    if any(b["signature"] for b in beads):
        return "fragment_signature"
    if beads and all(b["type"] for b in beads):
        return "bead_types_only"
    return "none"


def example(rid, collection, name, smiles, source, beads, origin, *, formal_charge=None, variant=None, motifs=(),
            smiles_check=None, notes=None, diagnostics=()):
    mol, constitution, tautomer = identity(smiles)
    support = support_of(beads)
    diagnostics = list(diagnostics)
    if support == "atom_membership" and mol is not None:
        covered = {int(i) for b in beads for i in b["members"]}
        missing = [a.GetIdx() + 1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1 and a.GetIdx() + 1 not in covered]
        if missing:   # the source mapping leaves atoms out: its beads still hold verified fragments
            support = "fragment_signature"
            diagnostics.append(f"heavy atoms {missing} are in no bead of the source mapping: not a complete mapping precedent")
    return {"id": rid, "kind": "example_model", "collection": collection, "name": name, "variant": variant,
            "molecule": {"smiles": smiles, "formal_charge": formal_charge if formal_charge is not None or mol is None
                         else Chem.GetFormalCharge(mol), "constitution": constitution, "tautomer": tautomer,
                         "smiles_check": smiles_check},
            "motifs": sorted(motifs or []), "source": source, "mapping_support": support,
            "mapping_origin": origin if support == "atom_membership" else None, "beads": beads,
            "diagnostics": diagnostics, "notes": notes}


def member_charge(mol, members):
    """Bead charge from the formal charges of its member atoms (weighted), for beads without an ITP charge."""
    return round(sum(mol.GetAtomWithIdx(int(i) - 1).GetFormalCharge() * w for i, w in members.items()), 3)


def placed_beads(rid, smiles, cgsmiles, valid_types):
    """Beads of a CGSmiles string placed on the molecule: (beads, diagnostics)."""
    raw = refbeads.cgsmiles_beads(cgsmiles, valid_types)
    refbeads.resolve_on_molecule(smiles, raw)
    mol = Chem.MolFromSmiles(smiles)
    names = [b["name"] for b in raw]
    beads = []
    for b in raw:
        b["neighbours"] = sorted(names[j] for j in b.get("cg_neighbours", []))
        beads.append(bead(rid, b, member_charge(mol, b["members"]) if b.get("members") else None))
    diags = []
    if raw and raw[0].get("placement") == "ambiguous":
        diags.append("CGSmiles fragments fit the molecule in non-equivalent ways: signatures only, no atom memberships")
    if any(b.get("signature_error") for b in raw):
        diags.append(next(b["signature_error"] for b in raw if b.get("signature_error")))
    return beads, diags


def source_of(e, project):
    path = project / e["source_path"]
    src = {"path": e["source_path"], "locator": e.get("source_locator"), "sha256": sha256(path),
           "mapping_path": e.get("mapping_path"), "mapping_figure": e.get("mapping_figure"),
           "aa_topology": e.get("mapping_atom_reference"), "doi": e.get("doi_url") or []}
    return {k: v for k, v in src.items() if v is not None}


def build_models(project):
    """SM3 models (atom membership from their .ndx mapping files) and the POLYPLY-M3 PEO building blocks."""
    out = []
    for e in read_jsonl(project / SRC / "models_catalog.jsonl"):
        rid, src = e["reference_id"], source_of(e, project)
        common = dict(variant=e.get("model_variant"), motifs=e.get("motifs"), smiles_check=e.get("smiles_verification"),
                      notes=e.get("notes"), formal_charge=e.get("formal_charge"))
        if rid.startswith("POLYPLY-M3"):
            beads = []
            for mt, scope in (("EO", "one bead per ethylene-oxide repeat unit (-CH2-CH2-O-)"), ("OHter", "hydroxyl end group")):
                atoms, _ = refbeads.itp_moleculetype(project / e["source_path"], mt)
                beads.append({**bead(rid, {"name": mt, "type": atoms[0]["type"], "charge_e": atoms[0]["charge"]}),
                              "scope": scope})
            out.append(example(rid, "POLYPLY-M3", e["name"], None, src, beads, None, **common,
                               diagnostics=["polymer building blocks: no atom-level mapping in the source; exact transfer "
                                            "needs a verified atom mapping"]))
            continue
        try:
            beads = [bead(rid, b) for b in refbeads.ndx_beads(e, project)]
            diags = []
        except Exception as ex:  # noqa: BLE001  (recorded in the record and the build report)
            beads, diags = [], [f"bead view not built: {ex}"]
        out.append(example(rid, "SM3", e["name"], e["canonical_isomeric_smiles"], src, beads, "ndx", **common,
                           diagnostics=diags))
    return out


def build_ff300(project, valid_types):
    """Molecules of the Martini 3.0.0 force-field files. Types and charges from the ITP; memberships from a single
    bead, a unique CGSmiles placement or a curated mapping."""
    curated = {c["id"]: c for c in read_jsonl(project / SRC / "ff300_curated.jsonl")}
    out = []
    for e in read_jsonl(project / SRC / "ff300_catalog.jsonl"):
        rid, smiles, src = e["reference_id"], e["canonical_isomeric_smiles"], source_of(e, project)
        mt = e["source_locator"].split()[1]
        atoms, bonds = refbeads.itp_moleculetype(project / e["source_path"], mt)
        names = {a["nr"]: a["name"] for a in atoms}
        mol = Chem.MolFromSmiles(smiles)
        heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
        diags, origin = [], None
        common = dict(motifs=e.get("motifs"), smiles_check=e.get("smiles_verification"), notes=e.get("notes"),
                      formal_charge=e.get("formal_charge"))
        if rid in curated:
            c = curated[rid]
            if c["smiles"] != smiles:
                raise ValueError(f"{rid}: curated SMILES {c['smiles']} differs from the catalog {smiles}")
            by_name = {a["name"]: a for a in atoms}
            beads, total = [], {}
            for cb in c["beads"]:
                a = by_name[cb["itp_name"]]
                mem = {}
                for tok in cb["members"].split(","):
                    i, _, w = tok.partition(":")
                    mem[int(i)] = float(w) if w else 1.0
                for i, w in mem.items():
                    total[i] = total.get(i, 0.0) + w
                beads.append(bead(rid, {"name": a["name"], "type": a["type"], "charge_e": a["charge"],
                                        "signature": refbeads.fragment_signature(mol, {i - 1: w for i, w in mem.items()}),
                                        "members": {str(i): w for i, w in sorted(mem.items())},
                                        "neighbours": refbeads.neighbours(a["nr"], bonds, names)}))
            bad = [i + 1 for i in heavy if abs(total.get(i + 1, 0.0) - 1.0) > 1e-6]
            if bad or len(c["beads"]) != len(atoms):
                raise ValueError(f"{rid}: curated mapping does not cover the molecule (atoms {bad}) or every ITP bead")
            src["mapping"] = c["source"]
            origin, common["notes"] = "curated", c["note"]
        elif len(atoms) == 1:
            beads = [bead(rid, {"name": atoms[0]["name"], "type": atoms[0]["type"], "charge_e": atoms[0]["charge"],
                                "signature": refbeads.fragment_signature(mol, {i: 1.0 for i in heavy}),
                                "members": {str(i + 1): 1.0 for i in heavy}, "neighbours": []})]
            origin = "single_bead"
        elif e.get("mapping_cgsmiles"):
            try:
                beads, diags = placed_beads(rid, smiles, e["mapping_cgsmiles"], valid_types)
            except Exception as ex:  # noqa: BLE001
                beads, diags = [], [f"CGSmiles not resolved: {ex}"]
            src["mapping_cgsmiles"] = e["mapping_cgsmiles"]
            origin = "cgsmiles_placement"
            beads, more = itp_types_win(rid, beads, atoms)
            diags += more
            q = sum(a["charge"] for a in atoms)
            if beads and all(b["charge_e"] is not None for b in beads) and abs(sum(b["charge_e"] for b in beads) - q) > 1e-6:
                diags.append(f"bead charges from formal charges sum to {sum(b['charge_e'] for b in beads)}, ITP to {q}")
        else:
            beads, diags = [], ["multi-bead model without an atom-level mapping"]
        out.append(example(rid, "FF300", e["name"], smiles, src, beads, origin, **common, diagnostics=diags))
    return out


def itp_types_win(rid, beads, atoms):
    """The ITP is the model; a CGSmiles string (taken from the Bible) only places its beads. Beads whose types
    agree are paired first; the rest are paired when one bead of each side is left. A CGSmiles with another
    number of beads describes another model: its placement is dropped and the ITP beads are kept as types only."""
    if not beads:
        return beads, []
    if len(beads) != len(atoms):
        kept = [bead(rid, {"name": a["name"], "type": a["type"], "charge_e": a["charge"]}) for a in atoms]
        return kept, [f"CGSmiles has {len(beads)} beads, the ITP {len(atoms)}: another model; ITP bead types only"]
    left = [a["type"] for a in atoms]
    odd = []
    for b in beads:
        if b["type"] in left:
            left.remove(b["type"])
        else:
            odd.append(b)
    if not odd:
        return beads, []
    if len(odd) == 1:
        was, odd[0]["type"] = odd[0]["type"], left[0]
        return beads, [f"bead {odd[0]['name']}: type {left[0]} from the ITP (CGSmiles says {was})"]
    if len(set(left)) == 1:
        for b in odd:
            b["type"] = left[0]
        return beads, [f"beads {[b['name'] for b in odd]}: type {left[0]} from the ITP (CGSmiles types differ)"]
    for b in beads:
        b["signature"], b["members"] = None, None
    return beads, [f"bead types differ from the ITP {sorted(a['type'] for a in atoms)} and cannot be paired: no placement kept"]


def build_bible(project, valid_types):
    from openpyxl import load_workbook
    out, sha = [], sha256(project / WORKBOOK)
    with closing(load_workbook(project / WORKBOOK, read_only=True)) as workbook:
        sheet = workbook["All"]
        for row, (name, moltag, smiles, cgsmiles) in enumerate(sheet.iter_rows(min_row=2, max_col=4, values_only=True), start=2):
            if not smiles:
                continue
            rid = f"BIBLE:row{row}"
            src = {"path": WORKBOOK.as_posix(), "locator": f"sheet {sheet.title}, row {row}", "sha256": sha,
                   "moltag": moltag, "cgsmiles": cgsmiles}
            try:
                if not cgsmiles:
                    raise ValueError("no CGSmiles")
                if Chem.MolFromSmiles(smiles) is None:
                    raise ValueError("SMILES does not parse")
                beads, diags = placed_beads(rid, smiles, cgsmiles, valid_types)
            except Exception as ex:  # noqa: BLE001
                beads, diags = [], [str(ex)]
            out.append(example(rid, "BIBLE", name, smiles, src, beads, "cgsmiles_placement", diagnostics=diags))
    return out


# ------------------------------------------------------------------ method evidence

def _norm(s):
    return " ".join(s.split())


def _find(lines, phrase, start):
    p = _norm(phrase)
    for i in range(start, len(lines)):
        if p in _norm(lines[i]):
            return i
    raise ValueError(f"phrase {phrase!r} not found after line {start + 1}")


def _table_values(lines):
    vals = {}
    for line in lines:
        f = line.split()
        if len(f) == 9 and re.match(r"^[A-Z][0-9]?(d/a)?$", f[0]):
            vals[f[0]] = dict(zip(TABLE_COLUMNS, [x if x in ("-", "gas") else float(x) for x in f[1:]]))
    return vals


def build_method_evidence(project):
    out, texts = [], {}
    for r in read_jsonl(project / SRC / "method_evidence.jsonl"):
        path = project / r["path"]
        lines = texts.setdefault(r["path"], path.read_text(encoding="utf-8").split("\n"))   # grep -n numbering
        start = _find(lines, r["after"], 0) + 1 if r.get("after") else 0   # search below the anchor line
        i = _find(lines, r["find"], start)
        j = _find(lines, r["until"], i) if r.get("until") else i
        for sm in (r.get("applies_to") or {}).get("core", []) + [x for x in [(r.get("applies_to") or {}).get("all")] if x]:
            if Chem.MolFromSmarts(sm) is None:
                raise ValueError(f"{r['id']}: invalid SMARTS {sm!r}")
        rec = {"id": r["id"], "kind": r["kind"], "stage": r["stage"], "statement": r["statement"],
               "applies_to": r.get("applies_to"), "row": r.get("row"),
               "source": {"path": r["path"], "locator": f"{r['section']}, " + (f"line {i + 1}" if i == j else f"lines {i + 1}-{j + 1}"),
                          "sha256": sha256(path)},
               "excerpt": "\n".join(lines[i:j + 1]), "diagnostics": []}
        if r["kind"] == "data_table":
            rec["values"] = _table_values(lines[i:j + 1])
        out.append(rec)
    ids = [r["id"] for r in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate method-evidence IDs")
    return out


# ------------------------------------------------------------------ main

def write_jsonl(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def report(files: dict[str, list[dict]], project: Path) -> dict:
    inputs = sorted(p.relative_to(project) for p in (project / SRC).glob("*.jsonl")) + [WORKBOOK]
    rep = {"inputs": {p.as_posix(): sha256(project / p) for p in inputs}, "files": {}}
    for name, rows in files.items():
        if name == "method_evidence":
            kinds = {}
            for r in rows:
                kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
            rep["files"][name] = {"records": len(rows), "by_kind": kinds}
            continue
        sup, ori = {}, {}
        for r in rows:
            sup[r["mapping_support"]] = sup.get(r["mapping_support"], 0) + 1
            if r["mapping_origin"]:
                ori[r["mapping_origin"]] = ori.get(r["mapping_origin"], 0) + 1
        rep["files"][name] = {"records": len(rows), "beads": sum(len(r["beads"]) for r in rows),
                              "beads_with_signature": sum(1 for r in rows for b in r["beads"] if b["signature"]),
                              "by_mapping_support": sup, "by_mapping_origin": ori,
                              "diagnostics": {r["id"]: r["diagnostics"] for r in rows if r["diagnostics"]}}
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="harness config (default config/harness.json)")
    ap.add_argument("--out", help="write the outputs into this folder instead of the configured paths (for comparison)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    cgbuild.configure(cfg.martini_env)
    project, valid = cfg.project, set(cgbuild.core_types())
    files = {"models": build_models(project), "ff300": build_ff300(project, valid), "bible": build_bible(project, valid),
             "method_evidence": build_method_evidence(project)}
    targets = {k: (Path(a.out) / Path(v).name if a.out else project / v) for k, v in cfg.env["indexes"].items()}
    for k, rows in files.items():
        targets[k].parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(targets[k], rows)
        print(f"{k}: {len(rows)} records -> {targets[k]}")
    rp = (Path(a.out) if a.out else targets["models"].parent) / "build_report.json"
    rp.write_text(json.dumps(report(files, project), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report -> {rp}")


if __name__ == "__main__":
    main()
