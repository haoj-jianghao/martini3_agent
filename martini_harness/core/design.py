#!/usr/bin/env python3
"""Write decisions/design.json for ONE molecule, one decision at a time (SKILL.md stages 2-3).

The agent makes every chemical decision; this tool records it, supplies the evidence the decision needs
and checks that the record says only what the evidence supports:
- `init` derives the index queries from the molecule itself (its ring systems, ring-substituent junctions,
  functional groups with their neighbouring carbons, aliphatic chains) and runs the search;
- `open` shows a reference model bead by bead (type, member atoms, fragment signature) and records that it
  was opened, or shows a method-evidence record (MEV:...) with its source text;
- `match` lists every indexed bead that holds exactly the same fragment as a proposed bead;
- `propose` projects the bead memberships of the most similar reference models onto this molecule and assembles
  candidate partitions from them (core/partition.py): the harness puts this into the mapping task;
- `candidate` refuses a partition with a lone-atom bead, an oversized bead or a divided chemical group, unless
  `exception` cites a reference that does the same;
- `research` opens and annotates, without an agent, the references the later steps need (sources of the
  projected partitions, rung-1 sources of their beads, the closest other hits) and prints them; it records the
  three best complete partitions within the rules as P1-P3 and chooses P1 (`shortlist` records them without
  opening references). Once they are recorded, `candidate` is refused and `choose` accepts only P1-P3; when the
  pipeline supplies none, the mapping agent records its own with `candidate`;
- `evidence` gives, per bead of the chosen candidate, its rung-1 precedents and the method records (Souza SI
  Table 24/25 rows, Tables 17-19) that apply to it: the harness puts this into the typing task;
- `bead --rung 1 --from REF:BEAD` copies the type from that source bead after verifying that it holds the
  same atoms in the same bonding context; rung 2/3 record the named group, rule or table, and the rung-1
  precedents the agent decided not to use, with the reason.
Every command is appended to decisions/design_log.jsonl with the hash of the design it leaves, so
`cgbuild.py build` can tell whether design.json was written by this tool.

The harness calls the cmd_* functions directly (see `namespace`), with the molecule folder of its run; a
refused decision raises DesignError. `python -m martini_harness.core.design ...` runs the same commands by hand.

  design.py init      <moldir> [--agent A] [--model M]
  design.py atoms     <moldir>
  design.py hits      <moldir> [--query NAME] [--limit N]
  design.py query     <moldir> --name N --smarts S [--tags a,b]
  design.py open      <moldir> REF_ID | MEV_ID
  design.py annotate  <moldir> REF_ID --reason TEXT [--used-for TEXT]
  design.py match     <moldir> --atoms 1,2,3[:w]
  design.py evidence  <moldir> [--atoms 1,2,3[:w]]
  design.py research  <moldir> [--top N] [--precedents N] [--hits N]   (the pipeline's research step)
  design.py shortlist <moldir> [--top N]   (records P1-P3 and chooses P1, after a research agent)
  design.py propose   <moldir> [--top N]
  design.py candidate <moldir> --id ID --beads "1,2,3|4,5:0.5,6" --summary S --pros "a;b" --cons "c;d" [--exception TEXT]
  design.py choose    <moldir> --candidate ID --rationale TEXT
  design.py bead      <moldir> --name B1 --atoms 1,2,3 --rung 1 --from REF_ID:BEAD --rationale TEXT
  design.py bead      <moldir> --name B1 --atoms 1,2,3 --rung 2 --type T --group G --rule R --source PATH:LOCATOR
                      [--provisional] [--rung1-rejection TEXT] --rationale TEXT
  design.py bead      <moldir> --name B1 --atoms ... --rung 3 --type T --table TABLE --values V --rung2-finding TEXT
                      --source PATH:LOCATOR [--provisional] [--rung1-rejection TEXT] --rationale TEXT
                      (all rungs: [--charge Q] [--size-exception TEXT] [--replace])
  design.py vsite     <moldir> --site N --construction virtual_sitesn_cog|virtual_sites3 --constructing 1,2,3
                      --source PATH:LOCATOR --evidence-class C
  design.py hydrogens <moldir> --excluded-parents 3,4 --reason TEXT
  design.py note      <moldir> (--unverified TEXT | --limitation TEXT | --manual TEXT)
  design.py show      <moldir>
  design.py check     <moldir>
"""
import argparse, datetime, hashlib, json, os, sys
from pathlib import Path
from types import SimpleNamespace

from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

SCRIPT_DIR = Path(__file__).resolve().parent
from . import cgbuild as C  # noqa: E402  (shared paths, index search, core types)
from . import refbeads as R  # noqa: E402
from . import partition as P  # noqa: E402

DESIGN = 'decisions/design.json'
LOG = 'decisions/design_log.jsonl'
_FP = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

# Functional groups searched in every target; each matched group becomes a query made of the group and its
# neighbouring heavy atoms in the target (so a hydroxyl on a CH2 queries C-C-O, not every O).
GROUPS = [
    ('carboxylic_acid', '[CX3](=O)[OX2H1,OX1-]'), ('ester', '[#6][CX3](=O)[OX2][#6]'), ('amide', '[CX3](=O)[NX3]'),
    ('aldehyde', '[CX3H1](=O)'), ('ketone', '[#6][CX3](=O)[#6]'), ('hydroxyl', '[OX2H1][#6]'),
    ('ether', '[#6][OX2][#6]'), ('amine', '[NX3;!$(N-C=O);!$(N-a);!$([N]=*)]'), ('aniline_n', '[NX3;$(N-a)]'),
    ('ammonium', '[NX4+]'), ('nitrile', 'C#N'), ('nitro', '[N+](=O)[O-]'), ('halide', '[#6][F,Cl,Br,I]'),
    ('thiol', '[SX2H1]'), ('thioether', '[#6][SX2][#6]'), ('sulfonyl', '[SX4](=O)(=O)'), ('phosphate', 'P(=O)(O)O'),
    ('carbonate', 'O=C(O)O'), ('imine', '[CX3]=[NX2]'), ('alkene', '[CX3;!a]=[CX3;!a]'), ('alkyne', 'C#C'),
]


# ------------------------------------------------------------------ helpers

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DesignError(Exception):
    """A decision the evidence does not support, or a command given in the wrong order. The message says why;
    `code` is the exit status of the command line (2 refused, 1 design incomplete)."""

    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


def die(msg):
    raise DesignError(msg)


def load(md):
    p = md / DESIGN
    if not p.exists():
        die(f'{p} does not exist; the pipeline runs `design_init` first (cgbuild input must have run)')
    return json.loads(p.read_text())


def save(md, des, command, args):
    C.wjson(md / DESIGN, des)
    args = {k: v for k, v in args.items() if k != 'fn'}
    rec = {'utc': now(), 'command': command, 'args': args, 'design_sha256': sha(md / DESIGN)}
    with open(md / LOG, 'a') as f:
        f.write(json.dumps(rec) + '\n')


def target(md):
    mol = Chem.MolFromMolFile(str(md / 'input/atomistic.sdf'), removeHs=False)
    if mol is None:
        die('cannot read input/atomistic.sdf; run cgbuild.py input first')
    return mol


def heavy_ids(mol):
    return [a.GetIdx() + 1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1]


def parse_atoms(spec, mol):
    """'1,2,3:0.5' -> {1: 1.0, 2: 1.0, 3: 0.5} (one-based heavy-atom IDs)."""
    out = {}
    hv = set(heavy_ids(mol))
    for tok in [t for t in spec.replace(' ', '').split(',') if t]:
        i, _, w = tok.partition(':')
        i = int(i)
        if i not in hv:
            die(f'atom {i} is not a heavy atom of this molecule (see `design_atoms`)')
        out[i] = float(w) if w else 1.0
    if not out:
        die('no atoms given')
    return out


def frag_smiles(mol, ids):
    return Chem.MolFragmentToSmiles(mol, [i - 1 for i in ids], canonical=True)


def signature(mol, members):
    return R.fragment_signature(mol, {i - 1: w for i, w in members.items()})


def refs():
    """Prepared example records (models, FF300, Bible), by id."""
    return C.examples().records


def precedents(sig):
    """Every indexed bead holding exactly this fragment signature (rung-1 precedents)."""
    return C.examples().fragments.get(sig, [])


def n_signed():
    return sum(len(v) for v in C.examples().fragments.values())


def method_records():
    return {r['id']: r for r in C.method_evidence()}


def cite(rec):
    """A record's source as the PATH:LOCATOR citation design_bead accepts."""
    return f"{rec['source']['path']}:{rec['source']['locator']}"


def applies(rec, mol, members):
    """Whether a method record's `applies_to` holds for the bead with these 1-based heavy-atom members:
    `core` SMARTS (one match must lie inside the bead), `all` (every bead atom matches this atom SMARTS) and
    `bead_size` (the bead's heavy-atom weight: T up to 2.5, S up to 3.5, R above). Matching runs on the
    heavy-atom graph, so degree and ring tests ignore hydrogens."""
    app = rec.get('applies_to')
    if not app:
        return False
    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    pos = {orig: k for k, orig in enumerate(heavy)}
    m = Chem.RemoveHs(mol)
    inside = {pos[i - 1] for i, w in members.items() if w > 0}
    if app.get('bead_size'):
        n = sum(members.values())
        if ('T' if n <= 2.5 else 'S' if n <= 3.5 else 'R') not in app['bead_size']:
            return False
    if app.get('all'):
        ok = {t[0] for t in m.GetSubstructMatches(Chem.MolFromSmarts(app['all']))}
        if not inside <= ok:
            return False
    if app.get('core'):
        return any(set(t) <= inside for sm in app['core'] for t in m.GetSubstructMatches(Chem.MolFromSmarts(sm)))
    return True


def parse_source(s):
    path, _, loc = s.partition(':')
    if not (C.PROJECT / path).exists():
        die(f'source path {path} does not exist under {C.PROJECT}')
    if not loc.strip():
        die(f'source {s!r} needs a locator after the colon (section, page, table, moleculetype or line)')
    return {'path': path, 'locator': loc.strip()}


# ------------------------------------------------------------------ query derivation

def derive_queries(mol):
    m = Chem.RemoveHs(mol)
    qs, seen = [], set()

    def add(name, atoms, tags, origin):
        s = Chem.MolFragmentToSmiles(m, sorted(atoms), canonical=True)
        if s in seen or Chem.MolFromSmarts(s) is None:
            return
        seen.add(s)
        qs.append({'name': name, 'smarts': s, 'motif_tags': tags, 'origin': origin,
                   'target_atoms': sorted(a + 1 for a in atoms)})

    ri = m.GetRingInfo()
    rings = [set(r) for r in ri.AtomRings()]
    systems = []
    for r in rings:
        cur = set(r)
        for s in [s for s in systems if s & cur]:
            cur |= s
            systems.remove(s)
        systems.append(cur)
    for k, sys_atoms in enumerate(systems):
        add(f'ring_system_{k + 1}', sys_atoms, [], 'derived: ring system')
        if sum(1 for r in rings if r <= sys_atoms) > 1:
            for j, r in enumerate([r for r in rings if r <= sys_atoms]):
                add(f'ring_system_{k + 1}_ring_{j + 1}', r, [], 'derived: single ring of a fused system')
        for a in sys_atoms:
            for n in m.GetAtomWithIdx(a).GetNeighbors():
                if n.GetIdx() in sys_atoms:
                    continue
                sub = {n.GetIdx()} | {x.GetIdx() for x in n.GetNeighbors() if x.GetIdx() not in sys_atoms}
                add(f'ring_{k + 1}_substituent_at_{a + 1}', sys_atoms | sub, [], 'derived: ring-substituent junction')
    for name, smarts in GROUPS:
        patt = Chem.MolFromSmarts(smarts)
        matches = m.GetSubstructMatches(patt)
        if matches and smarts not in seen:
            seen.add(smarts)
            qs.append({'name': name, 'smarts': smarts, 'motif_tags': [],
                       'origin': 'derived: functional group (library SMARTS)',
                       'target_atoms': sorted({a + 1 for t in matches for a in t})})
        for t in matches:
            env = set(t)
            for a in t:
                env |= {n.GetIdx() for n in m.GetAtomWithIdx(a).GetNeighbors()}
            add(f'{name}_at_{"-".join(str(a + 1) for a in t)}', env, [], f'derived: functional group {name} with neighbouring atoms')
    # aliphatic chains: maximal runs of acyclic sp3 carbons, 3 atoms or more (capped at 6 atoms)
    chain = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == 'C' and not a.IsInRing()
             and a.GetHybridization() == Chem.HybridizationType.SP3]
    cs, left = [], set(chain)
    while left:
        st = [left.pop()]
        comp = set(st)
        while st:
            x = st.pop()
            for n in m.GetAtomWithIdx(x).GetNeighbors():
                if n.GetIdx() in left:
                    left.discard(n.GetIdx())
                    comp.add(n.GetIdx())
                    st.append(n.GetIdx())
        cs.append(comp)
    for k, comp in enumerate(cs):
        if len(comp) >= 3:
            add(f'aliphatic_chain_{k + 1}', set(sorted(comp)[:6]), [], 'derived: aliphatic carbon chain')
    return qs


# ------------------------------------------------------------------ search and display

def run_search(md):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        C.cmd_search(SimpleNamespace(moldir=str(md)))
    return json.loads((md / 'decisions/analogue_search.json').read_text())


def ranked_hits(md, ana, query=None):
    tgt = Chem.MolFromSmiles(json.loads((md / 'input/request.json').read_text())['original_smiles'])
    tfp = _FP.GetFingerprint(tgt)
    rows = []
    for h in ana['hits']:
        if query and query not in h['queries']:
            continue
        m = Chem.MolFromSmiles(h['canonical_smiles']) if h.get('canonical_smiles') else None
        sim = DataStructs.TanimotoSimilarity(tfp, _FP.GetFingerprint(m)) if m else 0.0
        rows.append((sim, h))
    rows.sort(key=lambda x: -x[0])
    return rows


SUPPORT = {'atom_membership': 'atoms', 'fragment_signature': 'fragments', 'bead_types_only': 'types', 'none': 'none'}


def print_hits(md, ana, query=None, limit=15):
    rows = ranked_hits(md, ana, query)
    ex = refs()
    print(f'{len(rows)} hits' + (f' for query {query}' if query else '') + ' (ranked by Morgan similarity to the target; '
          'support: atoms = bead member atoms known, fragments = bead signatures only, types = bead types only):')
    for sim, h in rows[:limit]:
        r = ex.get(h['reference_id'], {})
        types = ' '.join(b['type'] or '?' for b in r.get('beads', [])) or f"(no beads: {'; '.join(r.get('diagnostics', []))})"
        print(f"  {sim:.2f}  {h['reference_id']:<26} {(h['name'] or '')[:28]:<28} {h.get('canonical_smiles') or '':<26} "
              f"{SUPPORT.get(r.get('mapping_support'), '?'):<9} {types}")
    if len(rows) > limit:
        print(f'  ... {len(rows) - limit} more (`design_hits` with a larger limit)')


def atom_table(mol):
    m = Chem.Mol(mol)
    for a in m.GetAtoms():
        a.SetAtomMapNum(a.GetIdx() + 1 if a.GetAtomicNum() > 1 else 0)
    print('heavy atoms (one-based IDs as atom-map numbers):', Chem.MolToSmiles(Chem.RemoveHs(m), canonical=False))
    for a in mol.GetAtoms():
        if a.GetAtomicNum() > 1:
            nb = [n.GetIdx() + 1 for n in a.GetNeighbors() if n.GetAtomicNum() > 1]
            print(f'  {a.GetIdx() + 1:>3} {a.GetSymbol():<2} {"arom" if a.GetIsAromatic() else "    "} '
                  f'H{a.GetTotalNumHs(includeNeighbors=True)} ring={"y" if a.IsInRing() else "n"} neighbours={nb}')


# ------------------------------------------------------------------ commands

def cmd_init(a):
    md = Path(a.moldir)
    if (md / DESIGN).exists():
        die(f'{md / DESIGN} exists; continue with the other commands (`design_show`)')
    req = json.loads((md / 'input/request.json').read_text())
    mol = target(md)
    agent = a.agent or 'unknown'
    model = a.model or 'unknown'
    des = {'schema_version': 1, 'molecule_id': req['molecule_id'], 'resname': req['molecule_id'][:5],
           'authored_by': {'agent': agent, 'model': model, 'tool': 'martini_harness.core.design'},
           'analogue_queries': derive_queries(mol), 'analogue_annotations': {},
           'default_rejection_reason': 'not opened with design.py open (every opened reference has its own reason)',
           'mapping_candidates': [], 'chosen_candidate': None, 'selection_rationale': None, 'beads': [],
           'virtual_sites': [], 'mass_policy': {'source': 'computed by stage 4 (d5bonded.terms.bead_masses); none authored'},
           'hydrogen_excluded_parents': {'atom_ids': []}, 'unverified_statements': [], 'limitations': [],
           'manual_interventions': [], 'revisions': []}
    (md / 'decisions').mkdir(exist_ok=True)
    save(md, des, 'init', vars(a))
    ana = run_search(md)
    atom_table(mol)
    print(f"\n{len(des['analogue_queries'])} queries derived from the molecule:")
    for q in des['analogue_queries']:
        n = sum(1 for h in ana['hits'] if q['name'] in h['queries'])
        print(f"  {q['name']:<34} {q['smarts']:<30} {n} hits")
    print(f"exposure: exact {ana['exact_target_matches']} tautomer {ana['tautomer_target_matches']}")
    print()
    print_hits(md, ana)
    print('\nNext: `design_open` the relevant hits, `design_match` proposed beads, then candidate/choose/bead.')


def cmd_atoms(a):
    atom_table(target(Path(a.moldir)))


def cmd_hits(a):
    md = Path(a.moldir)
    print_hits(md, json.loads((md / 'decisions/analogue_search.json').read_text()), a.query, a.limit)


def cmd_query(a):
    md = Path(a.moldir)
    des = load(md)
    if Chem.MolFromSmarts(a.smarts) is None:
        die(f'invalid SMARTS {a.smarts!r}')
    if any(q['name'] == a.name for q in des['analogue_queries']):
        die(f'query {a.name} exists')
    des['analogue_queries'].append({'name': a.name, 'smarts': a.smarts,
                                    'motif_tags': [t for t in (a.tags or '').split(',') if t],
                                    'origin': 'agent'})
    save(md, des, 'query', vars(a))
    ana = run_search(md)
    print_hits(md, ana, a.name)


def print_method_record(rec):
    print(f"{rec['id']} ({rec['kind']}, {rec['stage']}): {rec['statement']}\n  cite as: {cite(rec)}")
    if rec.get('values'):
        cols = list(next(iter(rec['values'].values())))
        print('  ' + 'bead'.ljust(7) + ''.join(c.rjust(13) for c in cols))
        for b, v in rec['values'].items():
            print('  ' + b.ljust(7) + ''.join(str(v[c]).rjust(13) for c in cols))
    else:
        print('  source text:\n' + '\n'.join('    ' + line.strip() for line in rec['excerpt'].splitlines()))


def cmd_open(a):
    md = Path(a.moldir)
    if a.ref.startswith('MEV:'):
        rec = method_records().get(a.ref)
        if rec is None:
            die(f'{a.ref} is not a method-evidence record')
        print_method_record(rec)
        return
    des = load(md)
    ex = refs()
    if a.ref not in ex:
        die(f'{a.ref} is not in the prepared indexes (models, FF300, Bible)')
    opened = print_record(ex[a.ref])
    mark_opened(des, a.ref, opened)
    save(md, des, 'open', vars(a))
    print(f'\nRecorded as opened. Give it a reason with `design_annotate` (ref={a.ref}, reason=...) '
          '(used references are annotated automatically by `design_bead`).')


def mark_opened(des, ref, files, reason=None):
    ann = des['analogue_annotations'].setdefault(ref, {'used': False, 'used_for': [], 'opened': [], 'reason': None})
    ann['opened'] = sorted(set(ann.get('opened', [])) | set(files))
    if reason and not ann.get('reason'):
        ann['reason'] = reason


def print_record(r):
    """Print a prepared example record bead by bead; return the files it points to (for `opened`)."""
    src = r['source']
    print(f"{r['id']}: {r['name']}  SMILES {r['molecule']['smiles']}\n  source: {src['path']}  {src.get('locator') or ''}")
    for k in ('mapping_path', 'mapping_figure', 'mapping_cgsmiles'):
        if src.get(k):
            print(f"  {k.replace('_', ' ')}: {src[k]}")
    if src.get('mapping'):
        print(f"  mapping (curated): {src['mapping']['path']}  {src['mapping']['locator']}")
    print(f"  support: {r['mapping_support']}" + (f" (memberships from {r['mapping_origin']})" if r['mapping_origin'] else ''))
    for d in r['diagnostics']:
        print(f'  note: {d}')
    if r.get('notes') and r['mapping_origin'] == 'curated':
        print(f"  curation: {r['notes']}")
    opened = [src['path']] + [src[k] for k in ('mapping_path', 'mapping_figure') if src.get(k)]
    if not r['beads']:
        print('  no beads: read the source file itself; this model cannot support rung 1.')
    else:
        print('  beads (signature: heavy atoms, * = bond out of the bead, [50c] = atom shared at weight 0.5; '
              'atoms are 1-based positions in the SMILES above):')
        for b in r['beads']:
            sig = b['signature'] or f"(no signature{': ' + b['diagnostic'] if b.get('diagnostic') else ''}; cannot support rung 1)"
            mem = f"  atoms {b['members']}" if b['members'] else ''
            q = f" q={b['charge_e']:+g}" if b.get('charge_e') else ''
            scope = f"  ({b['scope']})" if b.get('scope') else ''
            print(f"    {b['name']:<8} {b['type'] or '?':<6} {sig:<24}{mem}{q}{scope}")
    return opened


def cmd_annotate(a):
    md = Path(a.moldir)
    des = load(md)
    ann = des['analogue_annotations'].get(a.ref)
    if ann is None:
        die(f'{a.ref} was not opened; `design_open` it first')
    ann['reason'] = a.reason
    if a.used_for:
        ann['used'] = True
        ann['used_for'] = sorted(set(ann.get('used_for', [])) | {a.used_for})
    save(md, des, 'annotate', vars(a))
    print('ok')


def cmd_match(a):
    md = Path(a.moldir)
    mol = target(md)
    mem = parse_atoms(a.atoms, mol)
    sig = signature(mol, mem)
    pre = precedents(sig)
    print(f'target fragment {frag_smiles(mol, list(mem))}  signature {sig}  ({sum(mem.values()):g} heavy atoms)')
    if not pre:
        print(f'no indexed bead holds this fragment ({n_signed()} reference beads checked): rung 1 is not available for it')
        return
    by = {}
    for p in pre:
        by.setdefault(p['type'], []).append(f"{p['reference_id']}:{p['bead']}")
    for t, lst in sorted(by.items(), key=lambda x: -len(x[1])):
        print(f'  {t:<6} {len(lst):>3}  {", ".join(lst[:8])}{" ..." if len(lst) > 8 else ""}')
    print('Rung 1 needs one of these, opened with `design_open`, cited as source_bead=REF_ID:BEAD.')


def ranked_candidates(md, mol, top=25):
    """Projected partitions (core/partition.py), ranked: complete and within the rules, exact precedents, SASA band
    (core/sasa_check.partition_sasa on the stage-4 ensemble), closest analogue. Returns (projections, candidates)."""
    from . import sasa_check
    projs = P.projections(mol, refs(), top=top)
    if not projs:
        return projs, []
    return projs, P.assemble(mol, projs, precedents=precedents, similarity=similarity_to(mol),
                             sasa=lambda parts, sizes: sasa_check.partition_sasa(md, parts, sizes=sizes))


def similarity_to(mol):
    """Morgan (radius 2) Tanimoto similarity of any indexed reference to the target, cached per call site."""
    tfp = _FP.GetFingerprint(Chem.RemoveHs(mol))
    cache = {}

    def sim(rid):
        if rid not in cache:
            smi = refs().get(rid, {}).get('molecule', {}).get('smiles')
            m = Chem.MolFromSmiles(smi) if smi else None
            cache[rid] = DataStructs.TanimotoSimilarity(tfp, _FP.GetFingerprint(m)) if m is not None else 0.0
        return cache[rid]
    return sim


N_SUPPLIED = 3   # partitions the research pipeline supplies to the mapping step (the agent chooses one of them)


def supplied(ranked):
    """The partitions the pipeline supplies, numbered P1.. in this order: the best-ranked complete partitions
    within the mapping rules. Returns (partitions, True), or (the top-ranked ones, False) when none qualifies, so
    that propose and research can still show and open what was found."""
    ok = [c for c in ranked if c['complete'] and not c['issues']][:N_SUPPLIED]
    return (ok, True) if ok else (ranked[:N_SUPPLIED], False)


def sasa_text(c):
    s = c.get('sasa')
    if not s:
        return 'SASA not computed (incomplete partition)'
    if 'error' in s:
        return f"SASA not available ({s['error']})"
    return f"SASA {s['difference_pct']:+.1f}% ({s['band']})"


def cmd_propose(a):
    """Candidate partitions projected from the most similar reference models (core/partition.py)."""
    md = Path(a.moldir)
    mol = target(md)
    projs, cands = ranked_candidates(md, mol, a.top)
    if not projs:
        print('no reference model with atom memberships shares a substructure of two or more atoms with this molecule')
        return
    t1 = [r for r in C.method_evidence() if r['id'].startswith('MEV:alessandri:T1:')]
    print(f'Partitions projected from reference models (atoms are this molecule\'s ids; "same" = the bead holds the same '
          f'fragment as its source bead, "context" = same atoms, other bonds out of the bead). Ranked: complete and within '
          f'the mapping rules, then fewest beads without an exact precedent, then the SASA band (mapped vs atomistic '
          f'surface on the stage-4 ensemble; pass within 5%, review to 10%, flag above), then the closest analogue. '
          f'Shown: the {N_SUPPLIED} best complete partitions within the rules, the ones the research step records:')
    shown, ok = supplied(cands)
    if not ok:
        print('NO complete partition within the mapping rules was found; the best incomplete ones:')
    for k, c in enumerate(shown):
        state = 'complete' if c['complete'] else f"incomplete, uncovered {P._ids(c['uncovered'])}"
        print(f"\nP{k + 1} ({state}; {sasa_text(c)}; started from {c['seed']}, similarity {c['seed_similarity']:.2f})"
              f"{'  ISSUES: ' + '; '.join(c['issues']) if c['issues'] else ''}")
        print(f"  beads={P.spec([b['members'] for b in c['beads']])}")
        for b in c['beads']:
            n = sum(b['members'].values())
            src = (f"from {b['source']} ({b['ref_type']}, {'same' if b['same_fragment'] else 'context'}"
                   + (f"; {b['n_precedents']} indexed beads hold this fragment" if b.get('n_precedents') else '') + ")"
                   if b['source'] else
                   'remaining atoms, no reference bead' + ''.join(f"; Table 1: {r['row']['group']} ({r['row']['bead']})"
                                                                 for r, _ in P.building_blocks(mol, list(b['members']), t1)))
            print(f"    {P._ids(b['members']):<18} {frag_smiles(mol, list(b['members'])):<12} {n:g} atoms ({b.get('size') or P.size_of(n)})  {src}")
        if c['uncovered']:
            blocks = P.building_blocks(mol, list(c['uncovered']), t1)
            for r, ids in blocks:
                print(f"    uncovered atoms {','.join(map(str, ids))}: Table 1 building block {r['row']['group']} "
                      f"({r['row']['bead']}, {r['id']})")
    print('\nBest projection per reference (coverage = heavy-atom weight carried over):')
    for p in sorted(projs, key=lambda p: (-p['covered'], -p['similarity']))[:6]:
        print(f"  {p['reference_id']:<24} {p['name'][:28]:<28} similarity {p['similarity']:.2f}  "
              f"coverage {p['covered']:g}  beads {', '.join(b['source'].rsplit(':', 1)[1] for b in p['beads'])}")
    print(f'\nThe research step records these as P1-P{len(shown)} (when complete and within the rules); the mapping step '
          f'chooses one of them with design_choose.')


def cmd_research(a):
    """Deterministic research step (the `research: pipeline` mode of the harness): opens the references the later
    steps need and annotates each with the reason it was opened, then prints one evidence block per reference.
    Opened: the source of every bead of the top projected partitions; for each of those beads, up to
    `precedents` indexed references holding exactly its fragment (atom memberships first); the `hits` most
    similar search hits not yet included. Logged as one command, so a replay re-runs it."""
    md = Path(a.moldir)
    des = load(md)
    mol = target(md)
    ex = refs()
    roles = {}                                   # reference id -> reasons, in order of discovery

    def add(rid, why):
        if rid in ex and why not in roles.setdefault(rid, []):
            roles[rid].append(why)
    _, ranked = ranked_candidates(md, mol, a.top)
    cands, _ = supplied(ranked)
    for k, c in enumerate(cands):
        for b in c['beads']:
            atoms = P._ids(b['members'])
            if b['source']:
                add(b['source'].rsplit(':', 1)[0], f"source of bead {atoms} in projected partition P{k + 1} "
                                                  f"({'same fragment' if b['same_fragment'] else 'same atoms, other context'})")
            pre = sorted(precedents(signature(mol, {int(i): w for i, w in b['members'].items()})),
                         key=lambda p: p['mapping_support'] != 'atom_membership')
            seen_refs = []
            for p in pre:
                if p['reference_id'] not in seen_refs:
                    seen_refs.append(p['reference_id'])
                if len(seen_refs) > a.precedents:
                    break
                add(p['reference_id'], f"rung-1 source for bead {atoms} of P{k + 1} (its bead {p['bead']} {p['type']} holds the same fragment)")
    ana = json.loads((md / 'decisions/analogue_search.json').read_text())
    n_hits = 0
    for sim, h in ranked_hits(md, ana):
        if n_hits >= a.hits:
            break
        if h['reference_id'] not in roles:
            add(h['reference_id'], f"search hit, similarity {sim:.2f}; no bead of the projected partitions comes from it")
            n_hits += 1
    print(f'Evidence prepared by the pipeline: {len(roles)} references opened and annotated (sources of the projected '
          f'partitions P1-P{len(cands)}, rung-1 sources of their beads, the closest other hits). Atoms of a reference bead '
          f'are 1-based positions in that reference\'s SMILES; `design_open` shows a record in full.\n')
    shown = {}                                  # bead view -> first reference printed with it
    for rid, why in roles.items():
        r = ex[rid]
        src = r['source']
        files = [src['path']] + [src[k] for k in ('mapping_path', 'mapping_figure') if src.get(k)]
        mark_opened(des, rid, files, reason='opened by the pipeline: ' + '; '.join(why))
        view = (r['molecule']['smiles'], tuple((b['name'], b['type'], json.dumps(b['members'], sort_keys=True)) for b in r['beads']))
        print(f"{rid}  {r['name']}  {r['molecule']['smiles']}  [{SUPPORT.get(r['mapping_support'], '?')}]")
        if view in shown:
            print(f"  same beads as {shown[view]}")
        else:
            shown[view] = rid
            print(f"  source {src['path']}: {src.get('locator') or ''}" + (f"; mapping {src['mapping_path']}" if src.get('mapping_path') else ''))
            for bd in r['beads']:
                mem = ','.join(f'{i}' if w == 1 else f'{i}:{w:g}' for i, w in (bd['members'] or {}).items())
                print(f"  {bd['name']:<8} {bd['type'] or '?':<6} {bd['signature'] or '(no signature)':<22} {mem}")
        print('  why: ' + '; '.join(why))
    print('\n' + record_supplied(des, ranked))
    save(md, des, 'research', vars(a))


def record_supplied(des, ranked):
    """Record the supplied partitions as candidates P1.. (proposed_by 'pipeline') and choose P1, unless a choice
    exists. The mapping step chooses among exactly these: `candidate` is refused once they are recorded. Returns
    a line for the output."""
    if des['chosen_candidate']:
        return f"A candidate is already chosen ({des['chosen_candidate']}); nothing recorded."
    ok, complete = supplied(ranked)
    if not complete:
        return ('NO complete partition within the mapping rules was found: nothing recorded. The mapping agent '
                'records its own partitions (design_candidate).')
    for k, c in enumerate(ok):
        srcs = sorted({b['source'] for b in c['beads'] if b['source']})
        exact = sum(b['same_fragment'] for b in c['beads'])
        rec = {'id': f'P{k + 1}', 'proposed_by': 'pipeline',
               'beads': [{'name': f'B{j + 1}', 'members': {str(i): w for i, w in b['members'].items()},
                          'source': b['source']}
                         for j, b in enumerate(c['beads'])],
               'summary': f"projected partition {P.spec([b['members'] for b in c['beads']])} (started from {c['seed']})",
               'pros': [f"{exact} of {len(c['beads'])} beads hold exactly the fragment of an indexed bead", sasa_text(c)],
               'cons': ([f"{len(c['beads']) - exact} bead(s) without an exact precedent"] if exact < len(c['beads']) else []),
               'sources': srcs, 'sasa': c.get('sasa')}
        des['mapping_candidates'] = [x for x in des['mapping_candidates'] if x['id'] != rec['id']] + [rec]
    top = ok[0]
    des['chosen_candidate'] = des['pipeline_choice'] = 'P1'
    des['selection_rationale'] = (f"chosen by the pipeline: the best-ranked projected partition (complete, within the mapping "
                                  f"rules, {sum(b['same_fragment'] for b in top['beads'])} of {len(top['beads'])} beads with "
                                  f"an exact precedent, {sasa_text(top)}); the mapping agent confirms it or chooses another "
                                  f"supplied partition")
    return (f"Recorded candidates P1-P{len(ok)} and chose P1 ({sasa_text(top)}); the mapping step confirms it or "
            f"chooses another of these.")


def cmd_shortlist(a):
    """Record the supplied partitions and choose P1 without opening references (after a research agent, which
    cannot record candidates). Logged as one command, so a replay re-runs it."""
    md = Path(a.moldir)
    des = load(md)
    _, ranked = ranked_candidates(md, target(md), a.top)
    print(record_supplied(des, ranked))
    save(md, des, 'shortlist', vars(a))


def surroundings(mol, members):
    """What lies one bond outside a bead: one label per bond leaving it, sorted, e.g. ['C', 'c(ar)', 'O='].
    Each label is the outside atom's element, '(ar)' if aromatic, '=' if it has a double bond. Members are
    1-based heavy-atom ids of `mol` (hydrogens ignored)."""
    inside = {i for i, w in members.items() if w > 0}
    out = []
    for i in inside:
        for nb in mol.GetAtomWithIdx(i - 1).GetNeighbors():
            j = nb.GetIdx() + 1
            if nb.GetAtomicNum() > 1 and j not in inside:
                dbl = any(bd.GetBondType() == Chem.BondType.DOUBLE for bd in nb.GetBonds())
                out.append(nb.GetSymbol() + ('(ar)' if nb.GetIsAromatic() else '') + ('=' if dbl else ''))
    return sorted(out)


def precedent_surroundings(p):
    """Surroundings of an indexed bead in its own molecule, or None when its atoms are not known."""
    r = refs().get(p['reference_id'])
    bead = next((b for b in (r or {}).get('beads', []) if b['name'] == p['bead']), None)
    if not bead or not bead.get('members') or not r['molecule']['smiles']:
        return None
    m = Chem.MolFromSmiles(r['molecule']['smiles'])
    return surroundings(m, {int(i): w for i, w in bead['members'].items()}) if m is not None else None


def cmd_evidence(a):
    """Per bead (the chosen candidate's, or --atoms): rung-1 precedents and the method records that apply."""
    md = Path(a.moldir)
    des = load(md)
    mol = target(md)
    if a.atoms:
        beads = [('bead', parse_atoms(a.atoms, mol))]
    else:
        cand = next((c for c in des['mapping_candidates'] if c['id'] == des['chosen_candidate']), None)
        if cand is None:
            die('no chosen candidate; give atoms=... or choose a candidate first')
        beads = [(b['name'], {int(i): w for i, w in b['members'].items()}) for b in cand['beads']]
        bead_source = {b['name']: b.get('source') or '' for b in cand['beads']}   # 'REF_ID:BEAD' of the pipeline's partition
    if a.atoms:
        bead_source = {}
    rows = [r for r in C.method_evidence() if r['stage'] == 'typing']
    tables = {n: next(r for r in rows if r['id'] == f'MEV:souza-si:T{n}') for n in (17, 18, 19)}

    def source_type(name, pre):
        rid, _, bead = (bead_source.get(name) or '').rpartition(':')
        return next((p['type'] for p in pre if p['reference_id'] == rid and p['bead'] == bead), None)
    by_sig = {}                     # fragment signature -> (bead, its source's type): identical fragments, one type
    for nm, mm in beads:
        sg = signature(mol, mm)
        st = source_type(nm, precedents(sg))
        if st and sg not in by_sig:
            by_sig[sg] = (nm, st)
    for name, mem in beads:
        sig = signature(mol, mem)
        n = sum(mem.values())
        print(f"{name}: atoms {','.join(f'{i}' if w == 1 else f'{i}:{w:g}' for i, w in mem.items())}  "
              f"fragment {frag_smiles(mol, list(mem))}  {n:g} heavy atoms  signature {sig}")
        size = P.size_of(n)
        print(f"  size: {size} bead ({n:g} heavy atoms; T up to 2.5, S up to 3.5, R above). A type chosen without an exact "
              f"precedent (rung 2 or 3) must be a {size}-size type" + {'T': ' (T prefix)', 'S': ' (S prefix)', 'R': ' (no prefix)'}[size] + ".")
        pre = precedents(sig)
        if pre:
            by = {}
            for p in pre:
                by.setdefault(p['type'], []).append(p)
            print(f'  rung 1, {len(pre)} indexed bead(s) hold this fragment (source_bead=REF_ID:BEAD after design_open):')
            if len(by) == 1:
                for t, lst in by.items():
                    ids = [f"{p['reference_id']}:{p['bead']}" for p in lst]
                    print(f'    {t:<6} {len(lst):>3}  {", ".join(ids[:6])}{" ..." if len(ids) > 6 else ""}')
            else:
                env = surroundings(mol, mem)
                src = bead_source.get(name) or ''
                src_type = source_type(name, pre)
                print(f"    the precedents DISAGREE on the type. This bead's surroundings (atoms one bond outside): "
                      f"{', '.join(env) or 'none'}. Per type: count, how many have the same surroundings, examples:")
                stats = {}
                for t, lst in sorted(by.items(), key=lambda x: -len(x[1])):
                    envs = [precedent_surroundings(p) for p in lst]
                    match = [p for p, e in zip(lst, envs) if e == env]
                    known = sum(e is not None for e in envs)
                    stats[t] = (len(match), len(lst))
                    first = (match or lst)[:4]
                    print(f"    {t:<6} {len(lst):>3}  surroundings match {len(match)} of {known} known  e.g. " +
                          ', '.join(f"{p['reference_id']}:{p['bead']}" for p in first))
                sibling = by_sig.get(sig) if not src_type else None
                if src_type:
                    print(f"    The partition took this bead from {src}, whose type is {src_type}.")
                elif sibling and sibling[0] != name:
                    src_type = sibling[1]
                    print(f"    The partition took this bead from {src or 'no indexed bead'}, which holds a different fragment; "
                          f"bead {sibling[0]} holds the same fragment and its source's type is {src_type} "
                          f"(identical fragments in one molecule take one type).")
                else:
                    print(f"    The partition took this bead from {src or 'no indexed bead'}, which is not among these precedents.")
                # majority among the precedents with the same surroundings; all precedents when none has them
                matched = any(m for m, _ in stats.values())
                count = {t: (m if matched else n) for t, (m, n) in stats.items()}
                top = max(count.values())
                most = [t for t in stats if count[t] == top]
                order = src_type if src_type in most else most[0]
                why = (('the most precedents with the same surroundings' if matched
                        else 'no precedent has the same surroundings: the most precedents')
                       + (', and the partition\'s source breaks the tie' if len(most) > 1 and order == src_type else ''))
                print(f"    In the instruction's order (the most precedents with the same surroundings, then the partition's "
                      f"source as tie-break), that gives {order} ({why}). The choice and its reason are yours; name the "
                      f"types not used.")
        else:
            print(f'  rung 1: no indexed bead holds this fragment ({n_signed()} checked)')
        hits = [r for r in rows if r['kind'] == 'table_row' and applies(r, mol, mem)]
        hits.sort(key=lambda r: not r['id'].startswith('MEV:alessandri'))   # size-specific building blocks first
        if hits:
            print('  rung 2, matching chemical groups (Souza SI Table 24/25 defaults; Alessandri 2022 Table 1 building '
                  'blocks of this bead size), cite as sources=PATH:LOCATOR:')
            for r in hits:
                print(f"    {r['id']}: {r['statement']}\n      cite: {cite(r)}")
        else:
            t = tables[17 if n >= 4 else 18 if n >= 3 else 19]
            print(f"  rung 2: no table group matches; rung 3 uses {t['id']} (design_open it for the values)\n"
                  f"      cite: {cite(t)}")
    rules = [r for r in rows if r['kind'] == 'method_rule']
    print('\nRung-2 refinement rules (Souza SI C2), cite as sources=PATH:LOCATOR:')
    for r in rules:
        print(f"  {r['id']}: {r['statement']}\n    cite: {cite(r)}")


def partition(spec, mol):
    beads = [parse_atoms(p, mol) for p in spec.split('|') if p.strip()]
    tot = {}
    for b in beads:
        for i, w in b.items():
            tot[i] = tot.get(i, 0.0) + w
    miss = [i for i in heavy_ids(mol) if abs(tot.get(i, 0.0) - 1.0) > 1e-6]
    if miss:
        die(f'allocation weights do not sum to one for atoms {miss}')
    return beads


def cmd_candidate(a):
    md = Path(a.moldir)
    des = load(md)
    mol = target(md)
    if des.get('pipeline_choice'):
        die(f"the research pipeline supplied the candidates "
            f"({', '.join(c['id'] for c in des['mapping_candidates'] if c.get('proposed_by') == 'pipeline')}); "
            f"choose one of them with design_choose. Recording another partition is not allowed.")
    beads = partition(a.beads, mol)
    cands = [c for c in des['mapping_candidates'] if c['id'] != a.id]
    if len(cands) >= 3:
        die('at most three mapping candidates (SKILL.md stage 2.4)')
    found = P.issues(mol, beads)
    if found:
        if not a.exception:
            die('this partition breaks the mapping rules:\n' + '\n'.join('  - ' + x for x in found) +
                '\nChange the partition, or pass exception=... naming a reference (REF_ID) whose published mapping does the same.')
        if not any(rid in a.exception for rid in refs()):
            die('exception must name the reference (REF_ID, for example SM3:THIO:opt) whose mapping does the same')
    rec = {'id': a.id, 'proposed_by': 'agent',
           'beads': [{'name': f'B{k + 1}', 'members': {str(i): w for i, w in b.items()}} for k, b in enumerate(beads)],
           'summary': a.summary, 'pros': [x.strip() for x in a.pros.split(';') if x.strip()],
           'cons': [x.strip() for x in a.cons.split(';') if x.strip()]}
    if found:
        rec['exception'] = {'issues': found, 'reason': a.exception}
    des['mapping_candidates'] = cands + [rec]
    save(md, des, 'candidate', vars(a))
    t1 = [r for r in C.method_evidence() if r['id'].startswith('MEV:alessandri:T1:')]
    for k, b in enumerate(beads):
        sig = signature(mol, b)
        pre = precedents(sig)
        types = sorted({p['type'] for p in pre})
        ids = ', '.join(f"{p['reference_id']}:{p['bead']}" for p in pre[:3]) + (' ...' if len(pre) > 3 else '')
        n = sum(b.values())
        blocks = [f"{r['row']['bead']} {r['row']['group']}" for r, _ in P.building_blocks(mol, [i for i, w in b.items() if w > 0], t1)
                  if r['row']['bead'][0] == P.size_of(n) or (P.size_of(n) == 'R' and r['row']['bead'][0] not in 'ST')]
        print(f"  B{k + 1}: {frag_smiles(mol, list(b)):<14} {n:g} heavy atoms ({P.size_of(n)} bead)  signature {sig:<22} "
              f"rung-1 precedents: {len(pre)} {types if types else ''}{'  e.g. ' + ids if ids else ''}"
              + (f"\n      Table 1 building blocks of this size inside it: {'; '.join(blocks)}" if blocks else ''))
    if found:
        print('accepted with exception: ' + a.exception)


def cmd_choose(a):
    md = Path(a.moldir)
    des = load(md)
    if a.candidate not in [c['id'] for c in des['mapping_candidates']]:
        die(f'no candidate {a.candidate}')
    pick = des.get('pipeline_choice')
    if pick and next(c for c in des['mapping_candidates'] if c['id'] == a.candidate).get('proposed_by') != 'pipeline':
        die(f'{a.candidate} was not supplied by the research pipeline; choose one of the pipeline\'s candidates')
    if pick and a.candidate != pick and len(a.rationale.strip()) < 40:
        die(f'{a.candidate} overrides the pipeline\'s choice {pick}: the rationale must say why {pick} is not used '
            f'(at least 40 characters)')
    des['chosen_candidate'] = a.candidate
    des['selection_rationale'] = a.rationale
    save(md, des, 'choose', vars(a))
    print('ok')


def cmd_bead(a):
    md = Path(a.moldir)
    des = load(md)
    mol = target(md)
    mem = parse_atoms(a.atoms, mol)
    sig = signature(mol, mem)
    pre = precedents(sig)
    types = C.core_types()
    others = [b for b in des['beads'] if b['name'] != a.name]
    exists = len(others) != len(des['beads'])
    if exists and not a.replace:
        die(f'bead {a.name} exists; pass replace=true to redefine it')
    if len(a.rationale.strip()) < 25:
        die('the rationale must say, for this bead, why these atoms and this type')
    if any(b['rationale'].strip() == a.rationale.strip() for b in others):
        die('another bead of this molecule has the same rationale; write the reason for this bead')
    rec = {'name': a.name, 'charge_e': a.charge, 'members': {str(i): w for i, w in mem.items()},
           'rationale': a.rationale, 'fragment_signature': sig}
    pre_txt = ', '.join(f"{p['reference_id']}:{p['bead']} {p['type']}" for p in pre[:12]) + (' ...' if len(pre) > 12 else '')
    ex = refs()
    used = []
    if a.rung == 1:
        if not a.source_bead or ':' not in a.source_bead:
            die('rung 1 needs source_bead=REF_ID:BEAD (see `design_match`)')
        rid, _, bname = a.source_bead.rpartition(':')
        r = ex.get(rid)
        if r is None or not r['beads']:
            why = '; '.join(r['diagnostics']) if r else 'unknown reference'
            die(f'{rid} has no beads ({why}); it cannot support rung 1. Use rung 2 and cite it.')
        if rid not in des['analogue_annotations']:
            die(f'{rid} was not opened; `design_open` (ref={rid}) first')
        sb = next((b for b in r['beads'] if b['name'] == bname), None)
        if sb is None:
            die(f'{rid} has no bead {bname}; its beads: {[b["name"] for b in r["beads"]]}')
        if not sb['signature']:
            die(f'{rid}:{bname} has no verified signature ({sb.get("diagnostic") or r["mapping_support"]}); it cannot support rung 1')
        if sb['signature'] != sig:
            die(f'not the same fragment: target {sig} vs {rid}:{bname} {sb["signature"]}. Rung 1 needs the same heavy atoms '
                f'in the same bonding context. Precedents that do match: {pre_txt or "none"}; otherwise use rung 2.')
        if a.type and a.type != sb['type']:
            die(f'rung 1 copies the source type {sb["type"]}; type={a.type} contradicts it (leave type out at rung 1)')
        rec.update({'type': sb['type'], 'evidence_status': 'transferred', 'provisional_type': False,
                    'typing_ladder': {'rung_used': 1, 'rung_results': {
                        'rung_1': f'same fragment {sig} as {rid} bead {bname} ({sb["type"]}); verified by design.py '
                                  f'signature match. All indexed beads holding it: {pre_txt}'}},
                    'sources': [{'path': r['source']['path'], 'locator': f"{r['source'].get('locator') or ''}; bead {bname}".strip('; ')}]
                    + ([{'path': r['source']['mapping_path'], 'locator': f'group of bead {bname}'}] if r['source'].get('mapping_path') else [])
                    + ([{'path': r['source']['mapping']['path'], 'locator': r['source']['mapping']['locator']}] if r['source'].get('mapping') else [])})
        used.append(rid)
    elif a.rung in (2, 3):
        if not a.type or a.type not in types:
            die(f'type must be a bead type of the core ITP ({a.type!r} is not)')
        if pre and not a.rung1_rejection:
            die(f'rung 1 is available for this fragment ({pre_txt}). Use it, or say why not with rung1_rejection.')
        if not a.sources:
            die('sources is required: one or more PATH:LOCATOR citations')
        srcs = [parse_source(s) for s in a.sources]
        r1 = (f'indexed beads holding {sig}: {pre_txt}; not used: {a.rung1_rejection}' if pre else
              f'no indexed bead holds fragment {sig} ({n_signed()} reference beads checked)')
        if a.rung == 2:
            if not (a.group and a.rule):
                die('rung 2 needs group (the documented chemical group, Souza SI Table 24/25) and rule (the SI C2 proximity rule applied)')
            res = {'rung_1': r1, 'rung_2': f'group: {a.group}; rule: {a.rule}'}
        else:
            if not (a.table and a.values and a.rung2_finding):
                die('rung 3 needs table, values and rung2_finding (why no documented group fits)')
            res = {'rung_1': r1, 'rung_2': a.rung2_finding, 'rung_3': f'{a.table}: {a.values}'}
        rec.update({'type': a.type, 'evidence_status': 'adapted', 'provisional_type': bool(a.provisional),
                    'typing_ladder': {'rung_used': a.rung, 'rung_results': res}, 'sources': srcs})
        index_paths = {x['source']['path']: k for k, x in ex.items()}
        used += [index_paths[s['path']] for s in srcs if s['path'] in index_paths and index_paths[s['path']] in des['analogue_annotations']]
    else:
        die('rung must be 1, 2 or 3 (a rung-4 bead is unresolved: record it with `design_note` limitation=... and stop; the model is blocked)')
    if a.size_exception:
        rec['size_exception'] = a.size_exception
    for rid in used:
        ann = des['analogue_annotations'][rid]
        ann['used'] = True
        ann['used_for'] = sorted(set(ann.get('used_for', [])) | {f'{a.name} type {rec["type"]} (rung {a.rung})'})
        ann['reason'] = ann.get('reason') or f'source of bead {a.name}'
    des['beads'] = [rec if b['name'] == a.name else b for b in des['beads']] if exists else des['beads'] + [rec]
    cand = next((c for c in des['mapping_candidates'] if c['id'] == des['chosen_candidate']), None)
    if cand:   # the chosen candidate's order, so two identical models write identical files
        order = [tuple(sorted(cb['members'].items())) for cb in cand['beads']]
        des['beads'].sort(key=lambda b: order.index(tuple(sorted(b['members'].items())))
                          if tuple(sorted(b['members'].items())) in order else len(order))
    save(md, des, 'bead', vars(a))
    print(f"{a.name}: {rec['type']} rung {a.rung}  fragment {frag_smiles(mol, list(mem))}  signature {sig}")


def cmd_vsite(a):
    md = Path(a.moldir)
    des = load(md)
    src = parse_source(a.source)
    des['virtual_sites'] = [v for v in des['virtual_sites'] if v['site'] != a.site] + [{
        'site': a.site, 'construction': a.construction, 'constructing': [int(x) for x in a.constructing.split(',')],
        'evidence_class': a.evidence_class, 'source': src}]
    save(md, des, 'vsite', vars(a))
    print('ok')


def cmd_hydrogens(a):
    md = Path(a.moldir)
    des = load(md)
    des['hydrogen_excluded_parents'] = {'atom_ids': [int(x) for x in a.excluded_parents.split(',') if x], 'reason': a.reason}
    save(md, des, 'hydrogens', vars(a))
    print('ok')


def cmd_note(a):
    md = Path(a.moldir)
    des = load(md)
    if a.unverified:
        des['unverified_statements'].append({'statement': a.unverified, 'label': 'agent background knowledge, unverified'})
    if a.limitation:
        des['limitations'].append(a.limitation)
    if a.manual:
        des['manual_interventions'].append({'utc': now(), 'what': a.manual})
    save(md, des, 'note', vars(a))
    print('ok')


def problems(md, des, mol):
    p = []
    if not des['mapping_candidates']:
        p.append('no mapping candidate (`design_candidate`)')
    if not des['chosen_candidate']:
        p.append('no chosen candidate (`design_choose`)')
    else:
        cand = next(c for c in des['mapping_candidates'] if c['id'] == des['chosen_candidate'])
        cs = sorted(tuple(sorted(b['members'].items())) for b in cand['beads'])
        bs = sorted(tuple(sorted(b['members'].items())) for b in des['beads'])
        if cs != bs:
            p.append(f"the beads do not partition the molecule as candidate {des['chosen_candidate']} does")
    tot = {}
    for b in des['beads']:
        for i, w in b['members'].items():
            tot[int(i)] = tot.get(int(i), 0.0) + w
    miss = [i for i in heavy_ids(mol) if abs(tot.get(i, 0.0) - 1.0) > 1e-6]
    if miss:
        p.append(f'heavy atoms not fully allocated to beads: {miss}')
    for rid, ann in des['analogue_annotations'].items():
        if not ann.get('reason'):
            p.append(f'opened reference {rid} has no reason (`design_annotate`)')
    req = json.loads((md / 'input/request.json').read_text())
    q = sum(b.get('charge_e', 0.0) for b in des['beads'])
    if abs(q - req['formal_charge']) > 1e-9:
        p.append(f"bead charges sum to {q}, formal charge is {req['formal_charge']}")
    return p


def cmd_show(a):
    md = Path(a.moldir)
    des = load(md)
    mol = target(md)
    print(json.dumps({k: des[k] for k in ('molecule_id', 'authored_by', 'chosen_candidate', 'selection_rationale')}, indent=1))
    print(f"queries {len(des['analogue_queries'])}; opened {list(des['analogue_annotations'])}")
    for c in des['mapping_candidates']:
        print(f"candidate {c['id']}: {' | '.join(frag_smiles(mol, [int(i) for i in b['members']]) for b in c['beads'])}  {c['summary']}")
    for b in des['beads']:
        print(f"  {b['name']} {b['type']} rung {b['typing_ladder']['rung_used']} {frag_smiles(mol, [int(i) for i in b['members']])}: {b['rationale']}")
    for x in problems(md, des, mol):
        print('  TODO:', x)


def cmd_check(a):
    md = Path(a.moldir)
    des = load(md)
    mol = target(md)
    p = problems(md, des, mol)
    run_search(md)
    save(md, des, 'check', vars(a))
    if p:
        raise DesignError('design incomplete:\n' + '\n'.join('  - ' + x for x in p), code=1)
    print(f"design complete: {len(des['beads'])} beads; analogue_search.json refreshed. Next: cgbuild.py bonded {md}")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)

    def p(name, fn):
        q = sp.add_parser(name)
        q.add_argument('moldir')
        q.set_defaults(fn=fn)
        return q
    q = p('init', cmd_init); q.add_argument('--agent'); q.add_argument('--model')
    p('atoms', cmd_atoms)
    q = p('hits', cmd_hits); q.add_argument('--query'); q.add_argument('--limit', type=int, default=25)
    q = p('query', cmd_query); q.add_argument('--name', required=True); q.add_argument('--smarts', required=True)
    q.add_argument('--tags')
    q = p('open', cmd_open); q.add_argument('ref')
    q = p('annotate', cmd_annotate); q.add_argument('ref'); q.add_argument('--reason', required=True); q.add_argument('--used-for')
    q = p('match', cmd_match); q.add_argument('--atoms', required=True)
    q = p('evidence', cmd_evidence); q.add_argument('--atoms')
    q = p('research', cmd_research); q.add_argument('--top', type=int, default=25); q.add_argument('--precedents', type=int, default=2)
    q.add_argument('--hits', type=int, default=5)
    q = p('propose', cmd_propose); q.add_argument('--top', type=int, default=25)
    q = p('shortlist', cmd_shortlist); q.add_argument('--top', type=int, default=25)
    q = p('candidate', cmd_candidate); q.add_argument('--id', required=True); q.add_argument('--beads', required=True)
    q.add_argument('--summary', required=True); q.add_argument('--pros', required=True); q.add_argument('--cons', required=True)
    q.add_argument('--exception')
    q = p('choose', cmd_choose); q.add_argument('--candidate', required=True); q.add_argument('--rationale', required=True)
    q = p('bead', cmd_bead); q.add_argument('--name', required=True); q.add_argument('--atoms', required=True)
    q.add_argument('--rung', type=int, required=True); q.add_argument('--rationale', required=True)
    q.add_argument('--from', dest='source_bead'); q.add_argument('--type'); q.add_argument('--group'); q.add_argument('--rule')
    q.add_argument('--table'); q.add_argument('--values'); q.add_argument('--rung2-finding')
    q.add_argument('--source', dest='sources', action='append'); q.add_argument('--provisional', action='store_true')
    q.add_argument('--rung1-rejection'); q.add_argument('--charge', type=float, default=0.0)
    q.add_argument('--size-exception'); q.add_argument('--replace', action='store_true')
    q = p('vsite', cmd_vsite); q.add_argument('--site', type=int, required=True)
    q.add_argument('--construction', required=True, choices=['virtual_sitesn_cog', 'virtual_sites3'])
    q.add_argument('--constructing', required=True); q.add_argument('--source', required=True)
    q.add_argument('--evidence-class', required=True)
    q = p('hydrogens', cmd_hydrogens); q.add_argument('--excluded-parents', required=True); q.add_argument('--reason', required=True)
    q = p('note', cmd_note); q.add_argument('--unverified'); q.add_argument('--limitation'); q.add_argument('--manual')
    p('show', cmd_show)
    p('check', cmd_check)
    return ap


def namespace(cmd, moldir, **kw):
    """The arguments of one command as the command line would give them: the parser's defaults for `cmd`,
    overridden by the keyword arguments that are not None. The cmd_* functions and design_log.jsonl see exactly
    what a command-line call records."""
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)).choices[cmd]
    ns = {x.dest: x.default for x in sub._actions if x.dest != 'help'}
    unknown = set(kw) - set(ns)
    if unknown:
        raise TypeError(f'design {cmd}: unknown argument(s) {sorted(unknown)}')
    ns.update({k: v for k, v in kw.items() if v is not None})
    ns.update({'cmd': cmd, 'moldir': str(moldir), 'fn': sub.get_default('fn')})
    return SimpleNamespace(**ns)


def main():
    a = build_parser().parse_args()
    if C.ENV is None:
        sys.exit('design: set MARTINI_ENV to the environment.json')
    try:
        a.fn(a)
    except DesignError as e:
        print('design.py: ' + str(e), file=sys.stderr)
        sys.exit(e.code)


if __name__ == '__main__':
    main()
