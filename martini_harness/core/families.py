"""Families of candidate partitions: a bead-graph distance and leader clustering in rank order
(docs/plan_mapping_families.md, section "Bead-graph distance"; exploration script
docs/exploration/mapping_families_beadgraph.py).

- `supply(mol, cands, n, cutoff)`: the `n` partitions the research step supplies. Candidates are taken in rank order;
  one that is within `cutoff` of an earlier leader joins that family, otherwise it leads a new one. So the first leader
  is the best-ranked candidate, and every later leader differs from every earlier one by more than `cutoff` bead
  edits. The leaders of the first `n` families are supplied; with fewer families, the best-ranked other candidates
  fill the remaining slots.
- `distance(fam, i, j, cap)`: the bead-graph distance between candidates i and j, exact up to `cap`; cap + 1 means
  "more than cap".

Bead graph: one node per bead; two beads are joined when a covalent bond runs between them or they share an atom.
Regions: each ring system (fused rings are one) and each acyclic chain, with the groups of `partition.INDIVISIBLE`
carved out of chains as regions of their own. A bead's type is the set of region instances it touches; its label is
(size T/S/R, shares atoms). A correspondence sends each bead of A to one bead of B or leaves it unmatched: 1:1 when the
types are equal, or as a merge, when several connected A beads together hold exactly the B bead's atoms (weights
summed). Distance = merges (k beads into one count k - 1) + unmatched beads of A and of B + bead edges in only one
graph + 1:1 pairs whose labels differ, minimised over correspondences, over the automorphisms of the heavy-atom graph
(B's atoms relabelled) and over both directions (a split is a merge from B to A). A pure merge costs 1; naproxen's
ring re-pairing (ranks 2 and 4) costs 2; a different ring style on both phenyls of diphenhydramine costs 8.
"""
from rdkit import Chem

from . import partition as P

CUTOFF = 2   # bead edits: within it, two partitions are one family (docs/plan_mapping_families.md, window 2-3)


class Family:
    """Per-molecule data for the distance: regions, automorphisms, and the bead graphs of the ranked candidates."""

    def __init__(self, mol, cands):
        self.hv = hv = P.Heavy(mol)
        g = self.g = hv.mol
        systems = []
        for r in map(set, g.GetRingInfo().AtomRings()):
            for s in [s for s in systems if s & r]:
                systems.remove(s)
                r |= s
            systems.append(r)
        ring = set().union(*systems) if systems else set()
        groups = [{hv.pos[i] for i in x} for _, x in P._matches(hv)]
        groups = [x for x in groups if not x & ring and not any(x < y for y in groups)]
        chains = []
        for c in self._components(set(range(g.GetNumAtoms())) - ring):
            inside = [x for x in groups if x <= c]
            chains += inside + self._components(c - set().union(*inside) if inside else c)
        self.inst = {a: k for k, s in enumerate(systems + chains) for a in s}
        self.autos = g.GetSubstructMatches(g, uniquify=False, maxMatches=5000)
        self.graphs = [_Graph(self, c) for c in cands]
        self._d = {}

    def _components(self, atoms):
        out, left = [], set(atoms)
        while left:
            comp, stack = set(), [next(iter(left))]
            while stack:
                x = stack.pop()
                if x not in comp:
                    comp.add(x)
                    stack += [n.GetIdx() for n in self.g.GetAtomWithIdx(x).GetNeighbors() if n.GetIdx() in left]
            out.append(comp)
            left -= comp
        return out


def _key(m):
    """A bead's atoms with their weights, comparable across beads."""
    return frozenset((a, round(w, 3)) for a, w in m.items())


class _Graph:
    """Bead graph of one candidate; its beads' atoms relabelled through each automorphism are cached."""

    def __init__(self, fam, c):
        self.fam = fam
        self.W = [{fam.hv.pos[i]: w for i, w in b['members'].items()} for b in c['beads']]
        self.n = len(self.W)
        self.T = [frozenset(fam.inst[a] for a in m) for m in self.W]
        self.K = [_key(m) for m in self.W]
        self.lab = [(b.get('size') or P.size_of(sum(b['members'].values())),
                     any(w < 0.999 for w in b['members'].values())) for b in c['beads']]
        g = fam.g
        self.E = {(x, y) for x in range(self.n) for y in range(x + 1, self.n)
                  if set(self.W[x]) & set(self.W[y])
                  or any(g.GetBondBetweenAtoms(i, j) for i in self.W[x] for j in self.W[y])}
        self.adj = {k: set() for k in range(self.n)}
        for x, y in self.E:
            self.adj[x].add(y)
            self.adj[y].add(x)
        self._view = {}

    def view(self, s):
        """(weights, types, atom keys) of the beads with their atoms sent through automorphism s."""
        if s not in self._view:
            p = self.fam.autos[s]
            W = [{p[a]: w for a, w in m.items()} for m in self.W]
            self._view[s] = (W, [frozenset(self.fam.inst[a] for a in m) for m in W], [_key(m) for m in W])
        return self._view[s]


def _preimages(phi):
    pre = {}
    for a, b in phi.items():
        if b is not None:
            pre.setdefault(b, []).append(a)
    return pre


def _contracted(A, phi):
    """A's bead edges taken through the correspondence; edges inside a merge vanish, unassigned ends are skipped."""
    return {(min(phi[x], phi[y]), max(phi[x], phi[y])) for x, y in A.E
            if phi.get(x) is not None and phi.get(y) is not None and phi[x] != phi[y]}


def _cost(A, B, phi):
    pre, EAc = _preimages(phi), _contracted(A, phi)
    return (sum(len(x) - 1 for x in pre.values()) + sum(1 for b in phi.values() if b is None) + B.n - len(pre)
            + len(EAc - B.E) + len(B.E - EAc)
            + sum(1 for b, x in pre.items() if len(x) == 1 and A.lab[x[0]] != B.lab[b]))


def _lower_bound(A, B, phi, unreachable):
    """Cost already certain for a partial correspondence. A 1:1 pair with different labels costs at least 1 whatever
    follows: the mismatch stays, or another bead joins it and the merge costs 1 instead."""
    pre = _preimages(phi)
    return (sum(len(x) - 1 for x in pre.values()) + sum(1 for b in phi.values() if b is None)
            + len(_contracted(A, phi) - B.E)
            + sum(1 for b, x in pre.items() if len(x) == 1 and A.lab[x[0]] != B.lab[b]) + unreachable)


def _search(A, B, s, best):
    """Branch and bound for correspondences A -> B under automorphism s; lowers best[0] in place."""
    WB, TB, KB = B.view(s)
    opts = {a: sorted([b for b in range(B.n) if TB[b] == A.T[a]
                       or all(WB[b].get(at, 0) >= w - 1e-6 for at, w in A.W[a].items())],
                      key=lambda b: -len(set(A.W[a]) & set(WB[b]))) + [None] for a in range(A.n)}
    order, seen = [], set()                      # breadth-first, so merge groups grow connected
    for st in sorted(range(A.n), key=lambda k: -len(A.adj[k])):
        if st in seen:
            continue
        q = [st]
        seen.add(st)
        while q:
            x = q.pop(0)
            order.append(x)
            for y in sorted(A.adj[x]):
                if y not in seen:
                    seen.add(y)
                    q.append(y)
    reach = [set().union(*(set(opts[a]) for a in order[n:])) for n in range(A.n + 1)]
    phi = {}

    def valid():
        for b, As in _preimages(phi).items():
            if len(As) == 1:
                if TB[b] != A.T[As[0]]:
                    return False
                continue
            U = {}
            for a in As:
                for at, w in A.W[a].items():
                    U[at] = U.get(at, 0) + w
            if _key(U) != KB[b]:
                return False
            sub, seen, st = set(As), {As[0]}, [As[0]]
            while st:
                for y in A.adj[st.pop()] & sub:
                    if y not in seen:
                        seen.add(y)
                        st.append(y)
            if seen != sub:
                return False
        return True

    def rec(n):
        pre = _preimages(phi)
        if _lower_bound(A, B, phi, sum(1 for b in range(B.n) if b not in pre and b not in reach[n])) >= best[0]:
            return
        if n == A.n:
            if valid():
                best[0] = min(best[0], _cost(A, B, phi))
            return
        a = order[n]
        for b in opts[a]:
            phi[a] = b
            rec(n + 1)
            del phi[a]
    rec(0)


def _distinct_sigmas(fam, X, Y):
    """One automorphism per class giving the same problem: s and s' are equivalent when s'(Y) = t(s(Y)) for a t that
    leaves X unchanged, since then d(X, s Y) = d(t X, t s Y) = d(X, s' Y)."""
    def beads(K, p=None):
        return frozenset(k if p is None else frozenset((p[a], w) for a, w in k) for k in K)
    stab = [fam.autos[t] for t in range(len(fam.autos)) if beads(X.view(t)[2]) == beads(X.K)]
    seen, keep = set(), []
    for s in range(len(fam.autos)):
        orbit = frozenset(beads(beads(Y.view(s)[2]), p) for p in stab)
        if orbit not in seen:
            seen.add(orbit)
            keep.append(s)
    return keep


def distance(fam, i, j, cap=CUTOFF):
    """Bead-graph distance between candidates i and j, exact up to `cap`; cap + 1 means "more than cap"."""
    if (i, j, cap) not in fam._d:
        best = [cap + 1]
        for X, Y in ((fam.graphs[i], fam.graphs[j]), (fam.graphs[j], fam.graphs[i])):
            for s in _distinct_sigmas(fam, X, Y):
                _search(X, Y, s, best)
        fam._d[(i, j, cap)] = fam._d[(j, i, cap)] = best[0]
    return fam._d[(i, j, cap)]


def supply(mol, cands, n=3, cutoff=CUTOFF):
    """The `n` partitions to supply from `cands` (ranked, complete partitions): [(index, family, leader)], family
    numbered from 0. Leader clustering in rank order: a candidate within `cutoff` of a leader joins the nearest one
    (ties: the better-ranked leader), otherwise it leads a new family; the walk stops at the n-th leader. The leaders
    come first, in rank order. When there are fewer than `n` families (every candidate walked), the remaining slots
    go to the best-ranked other candidates, whatever their family, each marked with the family it belongs to (user
    decisions 2026-11-26: fill the slots; by rank, not family 1's variants first)."""
    fam = Family(mol, cands)
    lead, member = [], {}
    for k in range(len(cands)):
        near = [(d, f) for f, l in enumerate(lead) if (d := distance(fam, l, k, cutoff)) <= cutoff]
        if near:
            member[k] = min(near)[1]
            continue
        lead.append(k)
        if len(lead) == n:
            break
    out = [(k, f, True) for f, k in enumerate(lead)]
    return out + [(k, member[k], False) for k in sorted(member)][:n - len(out)]
