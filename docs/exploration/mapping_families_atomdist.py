"""Exploration: hybrid per-atom features, atom-count distance minimised over graph automorphisms, and leader
clustering in rank order.

Features of heavy atom i in partition A, f_A(i), over every bead holding i:
  ring atom      -> ('role', bead size T/S/R, bead shares ring atoms)
  any atom       -> ('pair', j, w_i*w_j) for each partner j in the bead with i or j a non-ring atom
d(A, B) = #{i : f_A(i) != f_B(i)};  d_sym(A, B) = min over sigma in Aut(G) of d(A, sigma B).
Leader clustering: candidates in rank order; each joins the nearest leader within CUTOFF atoms (ties: the better
ranked leader), else leads a new family. The minimising sigma is kept to show a variant in its leader's numbering.

Exploration only, not used by the harness (docs/plan_mapping_families.md). Run it from the project root on a COPY
of a molecule folder: ranked_candidates writes its SASA cache into research/ of the folder it is given.

usage: python docs/exploration/mapping_families_atomdist.py MOLDIR_COPY CUTOFF [RANK_A RANK_B ...]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from martini_harness.core import cgbuild, design as D, partition as P  # noqa: E402
cgbuild.configure(str(ROOT / 'environment.json'))

md = Path(sys.argv[1]); CUT = int(sys.argv[2])
mol = D.target(md); hv = P.Heavy(mol)
_, cands = D.ranked_candidates(md, mol, 25)
cands = [c for c in cands if c['complete'] and not c['issues']]
autos = hv.mol.GetSubstructMatches(hv.mol, uniquify=False, maxMatches=5000)
ring = {hv.ids[i] for r in hv.mol.GetRingInfo().AtomRings() for i in r}
ids = hv.ids


def relabel(c, perm):
    """The candidate's beads with every atom id sent through the automorphism (weights carried along)."""
    return [{ids[perm[hv.pos[i]]]: w for i, w in b['members'].items()} for b in c['beads']], [b['size'] for b in c['beads']]


def features(beads, sizes):
    f = {i: set() for i in ids}
    for m, size in zip(beads, sizes):
        shared = any(w < 0.999 for i, w in m.items() if i in ring)
        for i, wi in m.items():
            if i in ring:
                f[i].add(('role', size, shared))
            for j, wj in m.items():
                if j != i and (i not in ring or j not in ring):
                    f[i].add(('pair', j, round(wi * wj, 3)))
    return tuple(frozenset(f[i]) for i in ids)


identity = tuple(range(len(ids)))
F = [features(*relabel(c, identity)) for c in cands]                          # as numbered
FS = [[(features(*relabel(c, p)), p) for p in autos] for c in cands]         # under every automorphism


def dsym(a, b):
    """(distance, differing atom ids in a's numbering, minimising automorphism) of candidate indices a, b."""
    best = None
    for fb, p in FS[b]:
        diff = [ids[k] for k in range(len(ids)) if F[a][k] != fb[k]]
        if best is None or len(diff) < len(best[1]):
            best = (len(diff), diff, p)
    return best


def spec(beads):
    return P.spec(beads)


def describe(lead, var, diff, p):
    """The variant's beads touching the differing atoms, in the leader's numbering (via the automorphism)."""
    vb, _ = relabel(cands[var], p)
    lb = [b['members'] for b in cands[lead]['beads']]
    touch = lambda bs: sorted({P._ids(b) for b in bs if set(b) & set(diff)})   # noqa: E731
    return f"{' | '.join(touch(lb))}  ->  {' | '.join(touch(vb))}"


print(f"{md.name}: {len(cands)} candidates, {len(autos)} automorphism(s), cutoff {CUT} atoms")
pairs = list(map(int, sys.argv[3:]))
for a, b in zip(pairs[::2], pairs[1::2]):
    d, diff, p = dsym(a - 1, b - 1)
    print(f"  rank {a} vs {b}: d_sym {d} (identity numbering: {len([k for k in range(len(ids)) if F[a-1][k] != F[b-1][k]])})"
          f"  atoms {diff}" + (f"\n      {describe(a - 1, b - 1, diff, p)}" if diff else ''))

fams = []
for k in range(len(cands)):
    near = [(dsym(f['lead'], k), n) for n, f in enumerate(fams)]
    near = [(x, n) for x, n in near if x[0] <= CUT]
    if near:
        (d, diff, p), n = min(near, key=lambda t: (t[0][0], t[1]))
        fams[n]['members'].append((k, d, diff, p))
    else:
        fams.append({'lead': k, 'members': []})
print(f"  -> {len(fams)} families")
for n, f in enumerate(fams[:5]):
    c = cands[f['lead']]
    print(f"  F{n + 1} lead rank {f['lead'] + 1}: {spec([b['members'] for b in c['beads']])}  "
          f"non-exact {sum(not b['same_fragment'] for b in c['beads'])}, {D.sasa_text(c)}")
    for k, d, diff, p in f['members'][:5]:
        print(f"      rank {k + 1} (d {d}): {describe(f['lead'], k, diff, p)}")
    if len(f['members']) > 5:
        print(f"      ... {len(f['members']) - 5} more")
