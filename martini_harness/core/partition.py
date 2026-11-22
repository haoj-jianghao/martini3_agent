"""Deterministic help for the mapping step (stage 2): checks of a proposed partition, and partitions projected
from reference models onto the target. No bead types are chosen here (partition first, type second).

- `issues(mol, beads)`: what is wrong with a partition before any type exists: a bead of one heavy atom, a bead
  too large for an R bead, or an indivisible chemical group (carbonyl, carboxyl, ester, amide, nitro, nitrile,
  sulfonyl, sulfoxide, phosphate) divided between beads (Souza 2021 SI section C1). Same size thresholds as
  cgbuild.bead_size_issue, which checks the typed beads at `build`.
- `projections(mol, records)`: for the reference models with atom memberships most similar to the target, each
  reference bead's atoms (element, aromaticity, ring or chain, bonds) are matched in the target, and one
  placement per bead is chosen so that shared atoms stay shared and bonded atoms stay bonded; beads that do not
  fit are left out. This carries the reference's beads onto target atoms with their allocation weights.
- `bead_pool(...)`: every bead a partition may use: the projected beads; every other place in the target where a
  projected bead's fragment fits with the same signature; every connected set of 2-5 heavy atoms whose fragment
  has an indexed precedent; and connected sets of 2-4 heavy atoms without one (marked not exact). Beads that would
  cut an indivisible group or break the size rules are left out.
- `cover_search(...)`: exact cover with weights: sets of pool beads in which every heavy atom's weights sum to
  one, found by backtracking from the most constrained atom (exact beads tried first), bounded by exactness
  (branches with more than one non-exact bead beyond the best cover found are not explored), keeping covers that
  differ up to symmetry, with a step limit.
- `assemble(...)`: the covers as ranked candidate partitions (with today's greedy assembly as the fallback when no
  cover is found); atoms left uncovered by a fallback candidate are reported with the Alessandri 2022 Table 1
  building blocks that fit them.

Atoms are the target's 1-based atom ids (design.py numbering); every function works on the heavy-atom graph.
"""
from collections import defaultdict

from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

from . import refbeads as R

_FP = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

# Groups a bead boundary must not cut (Souza SI C1: "avoid dividing chemical groups (e.g., amides or carboxylates)")
INDIVISIBLE = [
    ('carboxyl', '[CX3](=[OX1])[OX2H1,OX1-]'), ('ester', '[CX3](=[OX1])[OX2;H0]'), ('amide', '[CX3](=[OX1])[NX3]'),
    ('carbonyl', '[CX3]=[OX1]'), ('nitro', '[N+](=O)[O-]'), ('nitrile', 'C#N'), ('sulfonyl', '[SX4](=O)=O'),
    ('sulfoxide', '[SX3]=O'), ('phosphate', '[PX4](=O)([OX1,OX2])[OX1,OX2]'),
]


class Heavy:
    """The heavy-atom graph of a molecule read with hydrogens, and the map between its indices and atom ids."""

    def __init__(self, mol):
        self.ids = [a.GetIdx() + 1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1]   # heavy index -> atom id
        self.pos = {aid: k for k, aid in enumerate(self.ids)}                           # atom id -> heavy index
        self.mol = Chem.RemoveHs(mol)

    def atom(self, aid):
        return self.mol.GetAtomWithIdx(self.pos[aid])


def size_of(n):
    """Bead size implied by its heavy-atom weight (Souza SI C1: 2-1 T, 3-1 S, 4-1 R)."""
    return 'T' if n <= 2.5 else 'S' if n <= 3.5 else 'R'


def groups(mol):
    """Atom-id sets of the indivisible groups present in the molecule."""
    hv = Heavy(mol)
    return [set(hv.ids[i] for i in t) for _, sm in INDIVISIBLE for t in hv.mol.GetSubstructMatches(Chem.MolFromSmarts(sm))]


def issues(mol, beads):
    """Problems of a partition: beads are {atom id: weight}. Returns a list of messages (empty when fine)."""
    hv = Heavy(mol)
    out = []
    for k, b in enumerate(beads):
        n = sum(b.values())
        atoms = [hv.atom(i) for i, w in b.items() if w > 0]
        ring5_het = len(atoms) == 1 and atoms[0].GetAtomicNum() != 6 and atoms[0].GetIsAromatic() and atoms[0].IsInRingSize(5)
        if n < 1.5 and not ring5_het:
            out.append(f'bead {k + 1} ({_ids(b)}) holds {n:g} heavy atom(s): a bead is a fragment of 2-4 heavy atoms, '
                       f'not a lone atom (only a lone heteroatom of a five-membered aromatic ring, as in thiophene, is published)')
        branched = any(sum(nb.GetAtomicNum() > 1 for nb in a.GetNeighbors()) == 4 for a in atoms)
        if n > (5.5 if branched else 4.5):
            out.append(f'bead {k + 1} ({_ids(b)}) holds {n:g} heavy atoms: more than an R bead represents (4, or 5 when fully branched)')
    divided = []          # larger groups come first in INDIVISIBLE; a carbonyl inside a divided ester is not repeated
    for name, smarts in INDIVISIBLE:
        for t in hv.mol.GetSubstructMatches(Chem.MolFromSmarts(smarts)):
            ids = sorted(hv.ids[i] for i in t)
            whole = any(all(b.get(i, 0.0) > 0.999 for i in ids) for b in beads)
            if not whole and not any(set(ids) <= d for d in divided):
                divided.append(set(ids))
                out.append(f'the {name} group (atoms {",".join(map(str, ids))}) is divided between beads '
                           f'(Souza SI C1: keep a chemical group in one bead)')
    return out


def _ids(b):
    return ','.join(f'{i}' if w == 1 else f'{i}:{w:g}' for i, w in sorted(b.items()))


def spec(beads):
    """design_candidate's `beads` string for a partition, beads ordered by their lowest atom id."""
    return '|'.join(_ids(b) for b in sorted(beads, key=lambda b: min(b)))


def signature(hv, members):
    return R.fragment_signature(hv.mol, {hv.pos[i]: w for i, w in members.items()})


def _bead_query(ref, mem):
    """Query for one reference bead: its atoms (element, aromatic or not, ring or not) and the bonds among them."""
    idx = sorted(mem)
    pos = {i: k for k, i in enumerate(idx)}
    q = Chem.RWMol()
    for i in idx:
        a = ref.GetAtomWithIdx(i)
        q.AddAtom(Chem.AtomFromSmarts(f"[#{a.GetAtomicNum()};{'a' if a.GetIsAromatic() else 'A'};{'R' if a.IsInRing() else '!R'}]"))
    for i in idx:
        for j in idx:
            bd = ref.GetBondBetweenAtoms(i, j) if i < j else None
            if bd is not None:
                sm = ':' if bd.GetIsAromatic() else {Chem.BondType.SINGLE: '-', Chem.BondType.DOUBLE: '=',
                                                     Chem.BondType.TRIPLE: '#'}.get(bd.GetBondType(), '~')
                q.AddBond(pos[i], pos[j], Chem.BondType.SINGLE)
                q.ReplaceBond(q.GetNumBonds() - 1, Chem.BondFromSmarts(sm))
    return idx, q.GetMol()


def _place(hv, ref, beads, max_steps=20000):
    """Placements of a reference's beads on the target: one match per placed bead, a skipped bead allowed.
    Placements agree with each other: one reference atom goes to one target atom (shared atoms stay shared),
    two reference atoms never go to the same target atom, and bonded reference atoms land on bonded target
    atoms. Returns (covered heavy-atom weight, [(bead, {ref atom: target heavy index})]) with the most weight."""
    opts = []
    for b in beads:
        mem = {int(i) - 1: w for i, w in b['members'].items()}
        idx, q = _bead_query(ref, mem)
        ms = [dict(zip(idx, m)) for m in hv.mol.GetSubstructMatches(q, uniquify=False, maxMatches=500)]
        if ms:
            opts.append((b, sum(mem.values()), ms))
    opts.sort(key=lambda o: len(o[2]))
    best, amap, inv, chosen, steps = [0.0, []], {}, {}, [], [0]
    left = [sum(o[1] for o in opts[k:]) for k in range(len(opts) + 1)]

    def fits(m):
        for r, t in m.items():
            if (r in amap and amap[r] != t) or (r not in amap and t in inv):
                return False
        for r, t in m.items():
            if r in amap:
                continue
            for r2, t2 in amap.items():
                if ref.GetBondBetweenAtoms(r, r2) is not None and hv.mol.GetBondBetweenAtoms(t, t2) is None:
                    return False
        return True

    def search(k, cov):
        steps[0] += 1
        if cov + left[k] <= best[0] + 1e-9 or steps[0] > max_steps:
            return
        if k == len(opts):
            best[:] = [cov, list(chosen)]
            return
        b, w, ms = opts[k]
        for m in ms:
            if fits(m):
                new = [r for r in m if r not in amap]
                for r in new:
                    amap[r] = m[r]
                    inv[m[r]] = r
                chosen.append((b, m))
                search(k + 1, cov + w)
                chosen.pop()
                for r in new:
                    del inv[amap.pop(r)]
        search(k + 1, cov)
    search(0, 0.0)
    return best


def projections(mol, records, top=25):
    """Projection of the `top` most similar reference models with atom memberships onto the target: a list of
    {reference_id, name, similarity, covered, beads: [{source, ref_type, members, same_fragment}]}."""
    hv = Heavy(mol)
    tfp = _FP.GetFingerprint(hv.mol)
    ranked = []
    for rid, r in records.items():
        if r['mapping_support'] != 'atom_membership' or not r['molecule']['smiles']:
            continue
        ref = Chem.MolFromSmiles(r['molecule']['smiles'])
        if ref is not None:
            ranked.append((DataStructs.TanimotoSimilarity(tfp, _FP.GetFingerprint(ref)), rid, ref))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for sim, rid, ref in ranked[:top]:
        cov, placed = _place(hv, ref, records[rid]['beads'])
        beads = []
        for b, m in placed:
            tm = {hv.ids[m[int(i) - 1]]: w for i, w in b['members'].items()}
            beads.append({'source': f"{rid}:{b['name']}", 'ref_type': b['type'], 'members': tm,
                          'same_fragment': signature(hv, tm) == b['signature']})
        if beads:
            out.append({'reference_id': rid, 'name': records[rid]['name'], 'similarity': round(sim, 2),
                        'covered': round(cov, 3), 'beads': sorted(beads, key=lambda b: min(b['members']))})
    return out


def _components(hv, left):
    """Connected pieces of the atoms not yet fully allocated: [{atom id: remaining weight}]."""
    todo, out = set(left), []
    while todo:
        stack, comp = [todo.pop()], set()
        while stack:
            a = stack.pop()
            comp.add(a)
            for nb in hv.atom(a).GetNeighbors():
                j = hv.ids[nb.GetIdx()]
                if j in todo:
                    todo.discard(j)
                    stack.append(j)
        out.append({i: left[i] for i in sorted(comp)})
    return out


def _greedy(mol, projs, n_seeds=6, precedents=None):
    """Fallback when no cover exists. Candidate partitions: each starts from one reference's projected beads and is completed with beads
    projected from the other references (largest coverage first) that keep every atom at weight one or less.
    Ordered: complete and free of rule issues first; then fewest beads without an exact precedent (filler beads,
    or beads whose bonding context differs from their source); then the SASA band (pass, review, flag) when
    `sasa(partitions, sizes)` is given (it returns [(difference %, band)] for the complete candidates; a bead's size
    is that of its exact precedents when they agree, else the one its heavy-atom weight implies); then the
    similarity of the starting reference. SASA is a second criterion, never the only one. A connected piece left over that fits one bead (1.5 to 4.5 heavy atoms) becomes a filler bead without a
    reference source; smaller or larger pieces stay uncovered for the agent. A filler bead, or a projected bead
    whose bonding context differs from its source, still counts as exact when `precedents(signature)` finds an
    indexed bead holding its fragment (that bead becomes its source). A projected bead that would cut an
    indivisible group is not used, so the group stays together for a filler bead."""
    hv = Heavy(mol)
    grp = groups(mol)

    def cuts(b):
        inside = {i for i, w in b['members'].items() if w > 0}
        return any((inside & g) and not (g <= {i for i, w in b['members'].items() if w > 0.999}) for g in grp)
    projs = [dict(p, beads=[b for b in p['beads'] if not cuts(b)]) for p in projs]
    projs = [p for p in projs if p['beads']]
    order = sorted(projs, key=lambda p: (-sum(sum(b['members'].values()) for b in p['beads']), -p['similarity'], p['reference_id']))
    seen, cands = set(), []
    for seed in order[:n_seeds]:
        total, chosen = defaultdict(float), []
        for p in [seed] + [p for p in order if p is not seed]:
            for b in p['beads']:
                if all(total[i] + w <= 1 + 1e-6 for i, w in b['members'].items()):
                    for i, w in b['members'].items():
                        total[i] += w
                    chosen.append(b)
        left = {i: round(1 - total[i], 3) for i in hv.ids if total[i] < 1 - 1e-6}
        for comp in _components(hv, left):
            if 1.5 <= sum(comp.values()) <= 4.5:
                chosen.append({'source': None, 'ref_type': None, 'members': comp, 'same_fragment': False})
                for i in comp:
                    del left[i]
        if precedents:
            for k, b in enumerate(chosen):
                if not b['same_fragment']:
                    pre = precedents(signature(hv, b['members']))
                    if pre:
                        chosen[k] = dict(b, source=f"{pre[0]['reference_id']}:{pre[0]['bead']}", ref_type=pre[0]['type'],
                                         same_fragment=True, n_precedents=len(pre))
        key = frozenset(frozenset(b['members'].items()) for b in chosen)
        if key in seen:
            continue
        seen.add(key)
        cands.append({'seed': seed['reference_id'], 'seed_similarity': seed['similarity'],
                      'beads': sorted(chosen, key=lambda b: min(b['members'])),
                      'uncovered': left, 'complete': not left, 'issues': issues(mol, [b['members'] for b in chosen])})
    return cands


def _bead_ok(hv, grp, members):
    """A bead the mapping rules allow on its own: 2-4 heavy atoms (5 when fully branched; a lone heteroatom of a
    five-membered aromatic ring), and no indivisible group cut by its boundary."""
    n = sum(members.values())
    atoms = [hv.atom(i) for i, w in members.items() if w > 0]
    ring5_het = len(atoms) == 1 and atoms[0].GetAtomicNum() != 6 and atoms[0].GetIsAromatic() and atoms[0].IsInRingSize(5)
    if n < 1.5 and not ring5_het:
        return False
    branched = any(sum(nb.GetAtomicNum() > 1 for nb in a.GetNeighbors()) == 4 for a in atoms)
    if n > (5.5 if branched else 4.5):
        return False
    inside = {i for i, w in members.items() if w > 0}
    whole = {i for i, w in members.items() if w > 0.999}
    return not any((inside & g) and not (g <= whole) for g in grp)


def _connected_sets(hv, lo, hi, cap=20000):
    """Connected sets of lo..hi heavy-atom ids."""
    out, frontier = [], {frozenset([i]) for i in hv.ids}
    for size in range(2, hi + 1):
        nxt = set()
        for st in frontier:
            for a in st:
                for nb in hv.atom(a).GetNeighbors():
                    j = hv.ids[nb.GetIdx()]
                    if j not in st:
                        nxt.add(st | {j})
        frontier = nxt
        if size >= lo:
            out += sorted(frontier, key=sorted)
        if len(out) > cap:
            break
    return out


def bead_maker(mol, precedents, similarity=None):
    """A function members -> bead dict (or None when the mapping rules do not allow the bead). A bead without a
    given source takes the closest indexed bead holding its fragment (atom memberships first) as its source."""
    hv, grp = Heavy(mol), groups(mol)
    sim = similarity or (lambda rid: 0.0)

    def make(members, source=None, ref_type=None):
        if not _bead_ok(hv, grp, members):
            return None
        pre = precedents(signature(hv, members))
        if not source and pre:
            best = max(pre, key=lambda x: (x['mapping_support'] == 'atom_membership', sim(x['reference_id'])))
            source, ref_type = f"{best['reference_id']}:{best['bead']}", best['type']
        return {'members': dict(members), 'source': source, 'ref_type': ref_type, 'same_fragment': bool(pre),
                'n_precedents': len(pre), 'sources': {source} if source else set()}
    return make


def bead_pool(mol, projs, precedents, similarity=None, max_exact=5, max_open=4):
    """Every bead a partition may use, merged by atoms and weights: {members, source, ref_type, same_fragment
    (an indexed bead holds exactly this fragment), n_precedents, sources}. Sources: the projected beads; their
    other exact placements; connected sets of 2..max_exact atoms with a precedent; connected sets of
    2..max_open atoms without one (not exact)."""
    hv, pool = Heavy(mol), {}
    make = bead_maker(mol, precedents, similarity)

    def add(members, source=None, ref_type=None):
        key = frozenset(members.items())
        if key in pool:
            if source:
                pool[key]['sources'].add(source)
            return
        b = make(members, source, ref_type)
        if b:
            pool[key] = b
    for p in projs:
        for b in p['beads']:
            add(b['members'], b['source'], b['ref_type'])
    for b in list(pool.values()):        # the same fragment elsewhere in the target
        sig = signature(hv, b['members'])
        idx, q = _bead_query(hv.mol, {hv.pos[i]: w for i, w in b['members'].items()})
        for m in hv.mol.GetSubstructMatches(q, uniquify=False, maxMatches=500):
            mm = dict(zip(idx, m))
            tm = {hv.ids[mm[hv.pos[i]]]: w for i, w in b['members'].items()}
            if signature(hv, tm) == sig:
                add(tm, b['source'], b['ref_type'])
    for st in _connected_sets(hv, 2, max(max_exact, max_open)):
        members = {i: 1.0 for i in st}
        if frozenset(members.items()) in pool:
            continue
        if len(st) <= max_open or precedents(signature(hv, members)):
            add(members)
    return list(pool.values())


COVER_SLACK = 1   # covers kept: at most this many non-exact beads more than the best cover found (alternatives)


def cover_key(hv, cover):
    """A cover's identity up to the molecule's symmetry: each bead as its multiset of (canonical atom rank, weight)."""
    ranks = list(Chem.CanonicalRankAtoms(hv.mol, breakTies=False))
    return frozenset(frozenset((ranks[hv.pos[i]], round(w, 3)) for i, w in b['members'].items()) for b in cover)


def cover_search(mol, pool, max_steps=50000, max_covers=500, make=None, slack=COVER_SLACK):
    """Sets of pool beads in which every heavy atom's weights sum to one. Backtracking: the open atom with the
    fewest fitting beads is covered next, trying exact beads first and larger beads before smaller ones. With
    `make` (bead_maker), a branch whose open atoms form one connected piece that the rules allow as a bead (with the
    weights left, for example half-shared ring atoms) is also closed with that piece as a filler bead.

    Bounded by exactness (user decision 2026-11-22): `best` is the fewest beads without an exact precedent in any
    cover found so far; a branch that already holds more than best + `slack` such beads is not explored, and covers
    beyond best + slack are dropped when a better cover appears. So the first ranking criterion does not depend on
    the order of the search. Only covers that differ up to symmetry (`cover_key`) are kept and counted; when
    `max_covers` are kept, a new cover replaces a kept one with more non-exact beads, or is skipped, and the search
    goes on. `max_steps` (calls of the search, dead ends included) is the only limit on the work."""
    hv = Heavy(mol)
    ranks = list(Chem.CanonicalRankAtoms(hv.mol, breakTies=False))
    left = {i: 1.0 for i in hv.ids}
    by_atom = {i: sorted((b for b in pool if i in b['members']),
                         key=lambda b: (not b['same_fragment'], -sum(b['members'].values())))
               for i in hv.ids}
    pool_keys = {frozenset(b['members'].items()) for b in pool}
    kept, chosen, steps = {}, [], [0]   # kept: symmetry key -> (non-exact count, cover)
    best = [len(hv.ids)]
    nonexact = [0]

    def fits(b):
        return all(left[i] - w >= -1e-6 for i, w in b['members'].items())

    def add(cover):
        n = sum(not b['same_fragment'] for b in cover)
        if n > best[0] + slack:
            return
        key = frozenset(frozenset((ranks[hv.pos[i]], round(w, 3)) for i, w in b['members'].items()) for b in cover)
        if key in kept:
            return
        if n < best[0]:
            best[0] = n
            for k in [k for k, (m, _) in kept.items() if m > n + slack]:
                del kept[k]
        if len(kept) >= max_covers:
            worst = max(kept, key=lambda k: kept[k][0])
            if kept[worst][0] <= n:
                return
            del kept[worst]
        kept[key] = (n, list(cover))

    def search():
        steps[0] += 1
        if steps[0] > max_steps or nonexact[0] > best[0] + slack:
            return
        open_ = [i for i in hv.ids if left[i] > 1e-6]
        if not open_:
            add(chosen)
            return
        if make and sum(left[i] for i in open_) <= 4.5:
            rest = {i: round(left[i], 3) for i in open_}
            comps = _components(hv, rest)
            if len(comps) == 1:
                filler = make(comps[0])
                if filler and frozenset(filler['members'].items()) not in pool_keys:
                    add(chosen + [filler])
        atom = min(open_, key=lambda a: sum(1 for b in by_atom[a] if fits(b)))
        for b in by_atom[atom]:
            if fits(b):
                for i, w in b['members'].items():
                    left[i] -= w
                chosen.append(b)
                nonexact[0] += not b['same_fragment']
                search()
                nonexact[0] -= not b['same_fragment']
                chosen.pop()
                for i, w in b['members'].items():
                    left[i] += w
    search()
    return [c for _, c in sorted(kept.values(), key=lambda x: x[0])]


def assemble(mol, projs, n_seeds=6, precedents=None, sasa=None, similarity=None, n_sasa=6):
    """Ranked candidate partitions. With `precedents`, the covers of the bead pool (`bead_pool`, `cover_search`),
    duplicates up to the molecule's symmetry removed; without a cover, the greedy assembly (`_greedy`).
    Ranked: complete and within the mapping rules; fewest beads without an exact precedent; the SASA band (pass,
    review, flag), computed by `sasa(partitions, sizes)` for the n_sasa best so far, a bead's size being that of
    its exact precedents when they agree, else the one its heavy-atom weight implies; ring beads sharing atoms
    before rings cut into unshared beads (user preference); fewer references; the
    closest analogue (mean similarity of the beads' sources, weighted by heavy atoms). SASA is a second criterion,
    never the only one."""
    hv = Heavy(mol)
    sim = similarity or {p['reference_id']: p['similarity'] for p in projs}.get
    simf = lambda rid: (sim(rid) or 0.0)       # noqa: E731
    cands = []
    if precedents:
        pool = bead_pool(mol, projs, precedents, simf)
        seen = set()
        for cover in cover_search(mol, pool, make=bead_maker(mol, precedents, simf)):
            key = cover_key(hv, cover)
            if key in seen:
                continue
            seen.add(key)
            refs = [b['source'].rsplit(':', 1)[0] for b in cover if b['source']]
            weight = {r: 0.0 for r in refs}
            for b in cover:
                if b['source']:
                    weight[b['source'].rsplit(':', 1)[0]] += sum(b['members'].values())
            seed = max(weight, key=lambda r: (weight[r], simf(r))) if weight else None
            heavy = len(hv.ids)
            analogue = sum(simf(b['source'].rsplit(':', 1)[0]) * sum(b['members'].values()) for b in cover if b['source']) / heavy
            cands.append({'seed': seed or 'remaining atoms', 'seed_similarity': round(analogue, 2),
                          'n_references': len(set(refs)), 'beads': sorted(cover, key=lambda b: min(b['members'])),
                          'uncovered': {}, 'complete': True, 'issues': issues(mol, [b['members'] for b in cover])})
    if not cands:
        cands = _greedy(mol, projs, n_seeds, precedents)
        for c in cands:
            c['n_references'] = len({b['source'].rsplit(':', 1)[0] for b in c['beads'] if b['source']})
    for c in cands:
        c['sasa'] = None
        for b in c['beads']:   # the size typing will most likely give: that of the exact precedents if they agree
            letters = {t[0] if t[0] in 'ST' else 'R' for t in
                       ([p['type'] for p in precedents(signature(hv, b['members']))] if precedents else [])}
            b['size'] = letters.pop() if len(letters) == 1 else size_of(sum(b['members'].values()))

    def base(c):
        return (not c['complete'], len(c['issues']), sum(not b['same_fragment'] for b in c['beads']))
    cands.sort(key=lambda c: (*base(c), c['n_references'], -c['seed_similarity']))
    top = [c for c in cands if c['complete']][:n_sasa]
    if sasa and top:
        try:
            for c, v in zip(top, sasa([[b['members'] for b in c['beads']] for c in top],
                                      [[b['size'] for b in c['beads']] for c in top])):
                c['sasa'] = {'difference_pct': v[0], 'band': v[1]}
        except Exception as e:  # noqa: BLE001  (no GROMACS or no ensemble: rank without SASA, say why)
            for c in top:
                c['sasa'] = {'error': f'{type(e).__name__}: {str(e)[:200]}'}
    band_rank = {'pass': 0, 'review': 1, 'flag': 2}
    ring_atoms = {hv.ids[i] for ring in hv.mol.GetRingInfo().AtomRings() for i in ring}

    def unshared_ring(c):
        """1 when the molecule has a ring and no ring atom is shared between beads (user preference, 2026-11-21:
        between equally exact partitions, the style with half-shared ring atoms comes first)."""
        if not ring_atoms:
            return 0
        return 0 if any(i in ring_atoms and w < 0.999 for b in c['beads'] for i, w in b['members'].items()) else 1
    cands.sort(key=lambda c: (*base(c), band_rank.get((c['sasa'] or {}).get('band'), 3), unshared_ring(c),
                              c['n_references'], -c['seed_similarity'], sum(c['uncovered'].values())))
    return cands


def building_blocks(mol, atoms, rows):
    """Alessandri 2022 Table 1 rows whose core lies inside `atoms` (atom ids): [(row, matched atom ids)]."""
    hv = Heavy(mol)
    inside = {hv.pos[i] for i in atoms}
    out = []
    for r in rows:
        for sm in (r.get('applies_to') or {}).get('core', []):
            for t in hv.mol.GetSubstructMatches(Chem.MolFromSmarts(sm)):
                if set(t) <= inside:
                    out.append((r, sorted(hv.ids[i] for i in t)))
                    break
            else:
                continue
            break
    return out
