# Attribution: adapted from aider (Apache-2.0)
# Upstream file: aider/repomap.py
# Copyright: (c) Paul Gauthier and contributors
# Changes: replaced the networkx multi-digraph + pagerank dependency with a
#          pure-stdlib power-iteration PageRank over a file→file reference graph;
#          kept aider's "personalization boosts chat/context files" idea but wired
#          it through a frozen RankedSymbol wrapper instead of mutating SymbolInfo;
#          rank flows from each file's centrality down to its symbols. No third-
#          party deps (no networkx, no grep-ast).
"""RankedRepoMapper — graph-ranked repo map under a token budget (Task 3).

Clean Architecture: depends only on ``code_intel`` domain types/ports plus
stdlib. ``RankedRepoMapper`` *wraps* a base :class:`RepoMapperPort`:

- ``scan_repo`` / ``scan_file`` DELEGATE to the base and return the UNRANKED
  ``RepoMap`` / ``list[SymbolInfo]`` in the same order and type (the base type is
  never modified — M1 invariant: ``SymbolInfo`` is byte-identical).
- ``rank`` is a SEPARATE method that computes per-symbol centrality via a simple
  pure-Python PageRank power-iteration over the reference/import graph, with an
  optional personalization vector that boosts symbols whose file is in
  ``context_files``. Higher rank == more central / more context-relevant.

``RepoMapBudget`` truncates an already rank-sorted tuple to the largest prefix
whose serialized token estimate fits ``max_tokens`` (binary search).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from swarmline.code_intel.protocols import RepoMapperPort
from swarmline.code_intel.types import RepoMap, SymbolInfo, file_to_module

# PageRank power-iteration constants. ``_DAMPING`` is aider's/Google's classic
# 0.85; iterations + tolerance are tuned so a few-hundred-file graph converges in
# well under a millisecond (deterministic, order-independent).
_DAMPING: float = 0.85
_MAX_ITERATIONS: int = 100
_TOLERANCE: float = 1.0e-8


@dataclass(frozen=True, slots=True)
class RankedSymbol:
    """A :class:`SymbolInfo` paired with its graph-rank score.

    ``symbol`` is the *unchanged* base ``SymbolInfo`` (never mutated or shadowed);
    ``rank`` is the centrality/context score (higher == more central).
    """

    symbol: SymbolInfo
    rank: float


@dataclass(frozen=True, slots=True)
class RepoMapBudget:
    """Token budget that truncates a rank-sorted symbol tuple to fit ``max_tokens``."""

    max_tokens: int

    def fit(
        self,
        ranked: tuple[RankedSymbol, ...],
        measure: Callable[[tuple[RankedSymbol, ...]], int] | None = None,
    ) -> tuple[RankedSymbol, ...]:
        """Return the largest rank-ordered prefix whose token estimate fits the budget.

        ``ranked`` MUST already be sorted by rank descending; the token estimate is
        monotonically non-decreasing in the prefix length, so we binary-search the
        largest ``k`` with ``measure(ranked[:k]) <= max_tokens``.

        F3 (budget bounds the FULL output): ``measure`` lets the caller estimate the
        ENTIRE serialized repo-map (root_path + files + imports + symbols), not just
        the symbols list. When omitted it defaults to the symbols-only estimator
        (used by the pure unit tests). The full-output measure is supplied by the
        wired executor so the emitted JSON actually respects ``repo_map_max_tokens``.

        ponytail / ceiling: when ``measure`` is the full-output one, the fixed
        overhead (root_path + files + imports) is NOT droppable, so an empty prefix
        ``()`` may still exceed ``max_tokens``. In that unavoidable case ``fit``
        returns ``()`` (zero symbols) rather than crashing — the structural minimum
        is the smallest output we can produce.
        """
        if not ranked or self.max_tokens <= 0:
            return ()

        estimate = measure if measure is not None else _estimate_tokens

        # If even the empty prefix (fixed overhead alone) blows the budget, there is
        # nothing to truncate toward — return zero symbols (structural minimum).
        if estimate(()) > self.max_tokens:
            return ()

        lo, hi = 0, len(ranked)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if estimate(ranked[:mid]) <= self.max_tokens:
                lo = mid
            else:
                hi = mid - 1
        return ranked[:lo]


def _estimate_tokens(ranked: tuple[RankedSymbol, ...]) -> int:
    """Cheap deterministic token estimator for a ranked-symbol prefix.

    ponytail: the laziest correct estimator is "serialized bytes // 4" — the
    well-known ~4-chars-per-token rule of thumb. It needs no tokenizer model and
    no third-party dep, and it only has to be *monotone* in prefix length for
    ``RepoMapBudget.fit``'s binary search to be correct. Ceiling: it is an
    approximation, so the real token count of the emitted JSON may differ from the
    budget by the usual tokenizer slack; that is acceptable for a soft repo-map cap.
    """
    serialized = _serialize_ranked_symbols(ranked)
    return len(serialized) // 4


def _serialize_ranked_symbols(ranked: tuple[RankedSymbol, ...]) -> str:
    """Serialize ranked symbols to the canonical JSON used by the repo_map tool."""
    return json.dumps(
        [
            {
                "name": rs.symbol.name,
                "kind": rs.symbol.kind.value,
                "file_path": rs.symbol.file_path,
                "line": rs.symbol.line,
                "signature": rs.symbol.signature,
                "rank": rs.rank,
            }
            for rs in ranked
        ]
    )


class RankedRepoMapper:
    """RepoMapperPort wrapper that adds graph-rank + context personalization.

    ``scan_repo`` / ``scan_file`` delegate to ``base`` and return its UNRANKED
    output unchanged. Ranking is exposed via the separate ``rank`` method.
    """

    def __init__(
        self,
        base: RepoMapperPort,
        *,
        context_files: tuple[str, ...] = (),
    ) -> None:
        self._base = base
        self._context_files = tuple(context_files)

    def scan_repo(self, root: str, extensions: set[str]) -> RepoMap:
        """Delegate to base — returns the UNRANKED RepoMap unchanged."""
        return self._base.scan_repo(root, extensions)

    def scan_file(self, path: str) -> list[SymbolInfo]:
        """Delegate to base — returns the UNRANKED symbols unchanged."""
        return self._base.scan_file(path)

    def rank(self, repo_map: RepoMap) -> tuple[RankedSymbol, ...]:
        """Rank every symbol by its file's graph centrality (+ context boost).

        Builds a file→file reference graph from ``repo_map.imports`` (an edge points
        from the importing file to the imported file, so importance flows toward the
        depended-upon / central modules), runs personalized PageRank, then assigns
        each symbol the rank of its file. Result is sorted by rank descending, with a
        stable (file_path, line, name) tiebreaker for determinism.
        """
        file_rank = self._page_rank(repo_map)
        ranked = [
            RankedSymbol(symbol=sym, rank=file_rank.get(sym.file_path, 0.0))
            for sym in repo_map.symbols
        ]
        # F1 (determinism): quantize ONLY the sort key — float non-associativity in
        # the power-iteration accumulators can drift logically-tied ranks by ~1e-16,
        # which would otherwise flip tied symbols BEFORE the structural tiebreaker.
        # Rounding to 12 places (well below _TOLERANCE) collapses sub-tolerance noise
        # so ties fall through to (file_path, line, name). RankedSymbol.rank stays exact.
        ranked.sort(
            key=lambda rs: (
                -round(rs.rank, 12),
                rs.symbol.file_path,
                rs.symbol.line,
                rs.symbol.name,
            )
        )
        return tuple(ranked)

    def _page_rank(self, repo_map: RepoMap) -> dict[str, float]:
        """Personalized PageRank power-iteration over the file reference graph.

        Pure stdlib, ~15 lines of iteration. Nodes are file paths; each import edge
        contributes a directed edge importer→imported (importance flows to central
        modules). ``context_files`` form the personalization (teleport) vector, so a
        symbol in a context file is boosted above an otherwise-equivalent one.
        """
        # F1 (determinism): canonicalize node order defensively — do NOT assume the
        # caller pre-sorted repo_map.files. A fixed iteration order makes the float
        # accumulations (dangling_sum, delta) reproducible regardless of input order.
        nodes = sorted(repo_map.files)
        if not nodes:
            return {}

        # Resolve import edges to file→file links via module name.
        module_to_file = {file_to_module(f, repo_map.root_path): f for f in nodes}
        out_edges: dict[str, list[str]] = {f: [] for f in nodes}
        for edge in repo_map.imports:
            target = module_to_file.get(edge.target_module)
            if target is not None and target != edge.source_file:
                if edge.source_file in out_edges:
                    out_edges[edge.source_file].append(target)
        # Sort each adjacency list so per-node share accumulation is order-independent.
        for src in out_edges:
            out_edges[src].sort()

        # Personalization vector: uniform, boosted toward context files.
        context = {f for f in self._context_files if f in out_edges} or set()
        personalization = _personalization_vector(nodes, context)

        n = len(nodes)
        rank = {node: 1.0 / n for node in nodes}
        for _ in range(_MAX_ITERATIONS):
            nxt = {node: (1.0 - _DAMPING) * personalization[node] for node in nodes}
            dangling_sum = 0.0
            for node in nodes:
                targets = out_edges[node]
                if targets:
                    share = _DAMPING * rank[node] / len(targets)
                    for tgt in targets:
                        nxt[tgt] += share
                else:
                    dangling_sum += _DAMPING * rank[node]
            # Dangling mass redistributes along the personalization vector.
            for node in nodes:
                nxt[node] += dangling_sum * personalization[node]
            delta = sum(abs(nxt[node] - rank[node]) for node in nodes)
            rank = nxt
            if delta < _TOLERANCE:
                break
        return rank


_CONTEXT_BOOST: float = 2.0
"""Raw teleport weight assigned to a context node vs 1.0 for a non-context node.

F2: any value > 1.0 guarantees a STRICT per-node boost after normalization. The
exact value is a free monotone parameter (ponytail: 2.0 = "twice as likely to
teleport into a context file"); only its being >1.0 matters for the invariant.
"""


def _personalization_vector(nodes: list[str], context: set[str]) -> dict[str, float]:
    """Build the PageRank teleport distribution (boosted toward context files).

    F2 (personalization correctness): use NORMALIZED relative weights, never a fixed
    mass split. Each context node gets raw weight ``_CONTEXT_BOOST`` (>1.0), each
    non-context node gets 1.0, then every weight is divided by the total so the
    vector ALWAYS sums to 1.0 and every context node is STRICTLY greater than every
    non-context node — for ANY context size (even 9-of-10 files). When ``context``
    is empty OR covers every node, the boost is vacuous, so we fall back to the
    uniform 1/n distribution (still normalized, sums to 1.0).
    """
    n = len(nodes)
    if not context or len(context) >= n:
        return {node: 1.0 / n for node in nodes}

    raw = {node: (_CONTEXT_BOOST if node in context else 1.0) for node in nodes}
    total = sum(raw.values())
    return {node: w / total for node, w in raw.items()}
