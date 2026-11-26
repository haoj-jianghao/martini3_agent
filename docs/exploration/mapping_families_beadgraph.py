"""Exploration: bead-graph distance between candidate partitions, with merge contraction, and leader clustering in
rank order.

Bead graph of a partition: one node per bead; two beads are joined when a covalent bond runs between them or they
share an atom. Each bead has
  type   the set of region instances it touches. Regions: each ring system (fused rings are one), and each acyclic chain
         with the indivisible groups of partition.INDIVISIBLE (carboxyl, amide, ...) carved out as regions of their own;
  label  (bead size T/S/R, shares atoms).

Correspondence A -> B: each A bead goes to one B bead or stays unmatched.
  1:1    the two beads have the same type;
  merge  several connected A beads go to one B bead, and their atoms (weights summed) are exactly the B bead's atoms.
d(A, B) = merges (k A beads into one B bead count k - 1) + unmatched beads of A and of B
          + bead edges in only one graph (A's edges taken through the correspondence) + 1:1 pairs whose labels differ,
minimised over correspondences, over the automorphisms sigma of the heavy-atom graph (B's atoms relabelled through
sigma), and over both directions (merge A -> B; a split is a merge B -> A). A pure merge costs 1.

Search: exact branch and bound per sigma; the best cost so far is shared across sigma, and sigma that give the same
problem (sigma'(B) = t(sigma(B)) for a t that leaves A unchanged) are run once. With `cap` (clustering), cap + 1 is the
starting bound, so only "is d <= cap" is decided exactly; larger distances are reported as cap + 1. Without it, a
quick matcher (identical beads and atom merges fixed, the rest searched) supplies the starting bound; it can
overestimate (naproxen 23 vs 25: 6 instead of 2), so it is never the answer by itself.

Leader clustering: candidates in rank order; each joins the nearest leader within the cutoff (ties: the better-ranked
leader), else leads a new family.

Exploration only, not used by the harness (docs/plan_mapping_families.md). Run it from the project root on a COPY of a
molecule folder: ranked_candidates writes its SASA cache into research/ of the folder it is given.

usage: python docs/exploration/mapping_families_beadgraph.py MOLDIR_COPY [RANK_A RANK_B ...] [--all OUT.json]
                                                             [--families CUT ...]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rdkit import Chem  # noqa: E402
from martini_harness.core import cgbuild, design as D, partition as P  # noqa: E402
cgbuild.configure(str(ROOT / 'environment.json'))

args = sys.argv[1:]; cuts = []; out_all = None
if '--families' in args:
    k = args.index('--families'); cuts = [float(x) for x in args[k + 1:]]; del args[k:]
if '--all' in args:
    k = args.index('--all'); out_all = args[k + 1]; del args[k:k + 2]
md = Path(args[0]); pairs = list(map(int, args[1:]))
mol = D.target(md); hv = P.Heavy(mol); g = hv.mol
_, cands = D.ranked_candidates(md, mol, 25)
cands = [c for c in cands if c['complete'] and not c['issues']]
aid = lambda k: hv.ids[k]                                                         # noqa: E731
akey = lambda m: frozenset((a, round(w, 3)) for a, w in m.items())               # noqa: E731  bead atoms with weights


def components(atoms):
    """Connected pieces of a set of heavy-atom indices."""
    out, left = [], set(atoms)
    while left:
        comp, stack = set(), [next(iter(left))]
        while stack:
            x = stack.pop()
            if x in comp: continue
            comp.add(x)
            stack += [n.GetIdx() for n in g.GetAtomWithIdx(x).GetNeighbors() if n.GetIdx() in left]
        out.append(comp); left -= comp
    return out


# ---- region instances: ring systems; chains with indivisible groups carved out ----
systems = []
for r in map(set, g.GetRingInfo().AtomRings()):
    for s in [s for s in systems if s & r]: systems.remove(s); r |= s
    systems.append(r)
ringatoms = set().union(*systems) if systems else set()
grp = [{hv.pos[i] for i in x} for _, x in P._matches(hv)]
grp = [x for x in grp if not x & ringatoms and not any(x < y for y in grp)]
chains = []
for c in components(set(range(g.GetNumAtoms())) - ringatoms):
    inside = [x for x in grp if x <= c]
    chains += inside + components(c - set().union(*inside) if inside else c)
regions = [('ring', s) for s in systems] + [('chain', c) for c in chains]
inst_of = {a: k for k, (_, s) in enumerate(regions) for a in s}
rank = list(Chem.CanonicalRankAtoms(g, breakTies=False))
cls, region_name = {}, []
for kind, s in regions:                         # display name: symmetry class + instance letter (ring1a, ring1b, ...)
    key = (kind, tuple(sorted(rank[a] for a in s)))
    cls.setdefault(key, [f"{kind}{sum(1 for k in cls if k[0] == kind) + 1}", 0])
    cls[key][1] += 1
    region_name.append(cls[key][0] + 'abcdefgh'[cls[key][1] - 1])
autos = g.GetSubstructMatches(g, uniquify=False, maxMatches=5000)


class BG:
    """Bead graph of one candidate: atom weights, edges, labels per bead; relabelled views cached per automorphism."""

    def __init__(self, c):
        self.W = [{hv.pos[i]: w for i, w in b['members'].items()} for b in c['beads']]
        self.n = len(self.W)
        self.T = [frozenset(inst_of[a] for a in m) for m in self.W]
        self.K = [akey(m) for m in self.W]
        self.lab = [(b['size'], any(w < 0.999 for w in b['members'].values())) for b in c['beads']]
        self.E = {(x, y) for x in range(self.n) for y in range(x + 1, self.n)
                  if set(self.W[x]) & set(self.W[y])
                  or any(g.GetBondBetweenAtoms(i, j) for i in self.W[x] for j in self.W[y])}
        self.adj = {k: set() for k in range(self.n)}
        for x, y in self.E: self.adj[x].add(y); self.adj[y].add(x)
        self._view = {}

    def view(self, s):
        """(weights, types, atom keys) of the beads with their atoms sent through automorphism s."""
        if s not in self._view:
            p = autos[s]
            W = [{p[a]: w for a, w in m.items()} for m in self.W]
            self._view[s] = (W, [frozenset(inst_of[a] for a in m) for m in W], [akey(m) for m in W])
        return self._view[s]


def preimages(phi):
    pre = {}
    for a, b in phi.items():
        if b is not None: pre.setdefault(b, []).append(a)
    return pre


def contracted(A, phi):
    """A's bead edges taken through the correspondence (edges inside a merge vanish); only fully assigned edges."""
    return {(min(phi[x], phi[y]), max(phi[x], phi[y])) for x, y in A.E
            if phi.get(x) is not None and phi.get(y) is not None and phi[x] != phi[y]}


def cost(A, B, phi):
    """(distance, breakdown) of a complete correspondence."""
    pre = preimages(phi); EAc = contracted(A, phi)
    br = dict(merges=sum(len(x) - 1 for x in pre.values()),
              unmatched_A=sum(1 for b in phi.values() if b is None), unmatched_B=B.n - len(pre),
              edges_only_A=len(EAc - B.E), edges_only_B=len(B.E - EAc),
              label=sum(1 for b, x in pre.items() if len(x) == 1 and A.lab[x[0]] != B.lab[b]))
    return sum(br.values()), br


def lower_bound(A, B, phi, unreachable=0):
    """Cost already certain for a partial correspondence. A 1:1 pair with different labels costs at least 1 whatever
    follows: the mismatch stays, or another bead joins and the merge costs 1 instead."""
    pre = preimages(phi)
    return (sum(len(x) - 1 for x in pre.values()) + sum(1 for b in phi.values() if b is None)
            + len(contracted(A, phi) - B.E)
            + sum(1 for b, x in pre.items() if len(x) == 1 and A.lab[x[0]] != B.lab[b]) + unreachable)


def overlap(A, WB, phi):
    return sum(len(set(A.W[a]) & set(WB[b])) for a, b in phi.items() if b is not None)


def quick_match(A, B, s):
    """Starting bound under automorphism s: identical beads paired, merges taken from atoms, the rest matched 1:1
    within the same type. Can overestimate; returns (cost, breakdown, phi)."""
    WB, TB, KB = B.view(s)
    phi, used = {}, set()
    byk = {k: b for b, k in enumerate(KB)}
    for a in range(A.n):
        b = byk.get(A.K[a])
        if b is not None and b not in used: phi[a] = b; used.add(b)
    for b in range(B.n):
        if b in used: continue
        inside = [a for a in range(A.n) if a not in phi and all(WB[b].get(at, 0) >= w - 1e-6 for at, w in A.W[a].items())]
        U = {}
        for a in inside:
            for at, w in A.W[a].items(): U[at] = U.get(at, 0) + w
        if len(inside) > 1 and akey(U) == KB[b]:
            for a in inside: phi[a] = b
            used.add(b)
    left = [a for a in range(A.n) if a not in phi]
    opts = {a: sorted([b for b in range(B.n) if b not in used and TB[b] == A.T[a]],
                      key=lambda b: -len(set(A.W[a]) & set(WB[b]))) + [None] for a in left}
    best = [float('inf'), None, None]

    def rec(n):
        if lower_bound(A, B, phi) >= best[0]: return
        if n == len(left):
            c, br = cost(A, B, phi)
            if c < best[0]: best[:] = [c, br, dict(phi)]
            return
        a = left[n]
        for b in opts[a]:
            if b is not None and b in phi.values(): continue
            phi[a] = b; rec(n + 1); del phi[a]
    rec(0)
    return best


def exact_match(A, B, s, best, tie):
    """Exact search under automorphism s, pruned by `best` = [cost, overlap, phi, breakdown], which is shared across
    automorphisms and updated in place. With `tie`, equal costs are also explored and the larger atom overlap wins
    (for reporting). Returns True when `best` improved."""
    WB, TB, KB = B.view(s)
    opts = {a: sorted([b for b in range(B.n) if TB[b] == A.T[a]
                       or all(WB[b].get(at, 0) >= w - 1e-6 for at, w in A.W[a].items())],
                      key=lambda b: -len(set(A.W[a]) & set(WB[b]))) + [None] for a in range(A.n)}
    order, seen = [], set()                     # breadth-first, so merge groups grow connected
    for st in sorted(range(A.n), key=lambda k: -len(A.adj[k])):
        if st in seen: continue
        q = [st]; seen.add(st)
        while q:
            x = q.pop(0); order.append(x)
            for y in sorted(A.adj[x]):
                if y not in seen: seen.add(y); q.append(y)
    reach = [set().union(*(set(opts[a]) for a in order[n:])) for n in range(A.n + 1)]
    phi, improved = {}, [False]

    def valid():
        for b, As in preimages(phi).items():
            if len(As) == 1:
                if TB[b] != A.T[As[0]]: return False
                continue
            U = {}
            for a in As:
                for at, w in A.W[a].items(): U[at] = U.get(at, 0) + w
            if akey(U) != KB[b]: return False
            sub, seen, st = set(As), {As[0]}, [As[0]]
            while st:
                x = st.pop()
                for y in A.adj[x] & sub:
                    if y not in seen: seen.add(y); st.append(y)
            if seen != sub: return False
        return True

    def rec(n):
        pre = preimages(phi)
        x = lower_bound(A, B, phi, sum(1 for b in range(B.n) if b not in pre and b not in reach[n]))
        if x > best[0] or (not tie and x >= best[0]): return
        if n == A.n:
            if not valid(): return
            c, br = cost(A, B, phi); ov = overlap(A, WB, phi)
            if (c, -ov) < (best[0], -best[1]):
                best[:] = [c, ov, dict(phi), br]; improved[0] = True
            return
        a = order[n]
        for b in opts[a]:
            phi[a] = b; rec(n + 1); del phi[a]
    rec(0)
    return improved[0]


def distinct_sigmas(X, Y):
    """One automorphism per class giving the same problem: sigma, sigma' are equivalent when sigma'(Y) = t(sigma(Y))
    for a t that leaves X unchanged (then d(X, sigma Y) = d(t X, t sigma Y) = d(X, sigma' Y))."""
    bead_set = lambda K, p=None: frozenset(k if p is None else frozenset((p[a], w) for a, w in k) for k in K)  # noqa: E731
    stab = [autos[t] for t in range(len(autos)) if bead_set(X.view(t)[2]) == bead_set(X.K)]
    seen, keep = set(), []
    for s in range(len(autos)):
        orbit = frozenset(bead_set(bead_set(Y.view(s)[2]), p) for p in stab)
        if orbit not in seen: seen.add(orbit); keep.append(s)
    return keep


def dist(i, j, tie=False, cap=None):
    """(distance, breakdown, phi, direction, sigma) between candidates i and j (indices). Exact; with `cap`, exact only
    up to cap, and cap + 1 means "more than cap" (breakdown, phi and sigma are then None)."""
    runs = [(X, Y, d, s) for X, Y, d in ((G[i], G[j], 'A->B'), (G[j], G[i], 'B->A')) for s in distinct_sigmas(X, Y)]
    where = (None, None)
    if cap is not None:
        best = [cap + 1, -1, None, None]
    else:
        best = [float('inf'), -1, None, None]
        for X, Y, d, s in runs:
            c, br, phi = quick_match(X, Y, s)
            if c < best[0]: best, where = [c, overlap(X, Y.view(s)[0], phi), phi, br], (d, s)
    for X, Y, d, s in runs:
        if exact_match(X, Y, s, best, tie): where = (d, s)
    return best[0], best[3], best[2], where[0], where[1]


G = [BG(c) for c in cands]
name = lambda m: ','.join(f"{aid(a)}" + (f":{w:g}" if w < 0.999 else '')        # noqa: E731
                          for a, w in sorted(m.items(), key=lambda t: aid(t[0])))
lab = lambda l: f"{l[0]}{'*' if l[1] else ''}"                                    # noqa: E731  * = shares atoms

print(f"{md.name}: {len(cands)} candidates, {len(autos)} automorphism(s); regions: "
      + '; '.join(f"{region_name[k]} {sorted(aid(a) for a in s)}" for k, (_, s) in enumerate(regions)))
for a, b in zip(pairs[::2], pairs[1::2]):
    a, b = a - 1, b - 1
    t = time.perf_counter(); d, br, phi, dirn, s = dist(a, b, tie=True)
    X, Y = (G[a], G[b]) if dirn == 'A->B' else (G[b], G[a])
    WB = Y.view(s)[0]
    print(f"  rank {a + 1} (A) vs {b + 1} (B): distance {d}  ({', '.join(f'{k} {v}' for k, v in br.items() if v)})"
          + ("" if dirn == 'A->B' else "  [split: B's beads mapped onto A]")
          + f"  [{(time.perf_counter() - t) * 1000:.0f} ms]")
    for k in range(X.n):
        m = phi[k]
        regs = '+'.join(sorted({region_name[inst_of[x]] for x in X.W[k]}))
        print(f"     {name(X.W[k]):<16} {regs:<16} {lab(X.lab[k]):<3} -> "
              + (f"{name(WB[m])} {lab(Y.lab[m])}" if m is not None else "unmatched"))
    for m in range(Y.n):
        if m not in phi.values(): print(f"     {'':<16} {'':<16} {'':<3}    unmatched {name(WB[m])}")

if out_all or cuts:
    t = time.perf_counter(); n = len(cands); Dm = {}

    def dd(i, j):
        if (i, j) not in Dm: Dm[(i, j)] = Dm[(j, i)] = dist(i, j, cap=None if out_all else max(cuts))[0]
        return Dm[(i, j)]
    if out_all:
        json.dump([[dd(i, j) if i != j else 0 for j in range(n)] for i in range(n)], open(out_all, 'w'))
        print(f"  all {n * (n - 1) // 2} pairs: {time.perf_counter() - t:.2f}s")
    for cut in cuts:
        fams = []
        for k in range(n):
            near = [(dd(f[0], k), i) for i, f in enumerate(fams)]
            near = [x for x in near if x[0] <= cut]
            if near: fams[min(near)[1]].append(k)
            else: fams.append([k])
        print(f"  families at distance <= {cut:g}: {len(fams)}  ("
              + '  '.join('F%d:%s' % (i + 1, ','.join(str(x + 1) for x in f[:8]) + ('...' if len(f) > 8 else ''))
                          for i, f in enumerate(fams[:5])) + ')')
    print(f"  ({time.perf_counter() - t:.2f}s total)")
