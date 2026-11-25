"""Tests for SCA Task 3 — Ranked repo-map under token budget + opt-in wiring.

REQ-SCA-020, REQ-SCA-021.
TDD phase: tests written first, implementation follows.

Naming convention: test_<what>_<condition>_<result>.

Covers:
- RankedRepoMapper: graph-rank centrality + context_files personalization.
- RepoMapBudget: deterministic prefix truncation under a token budget.
- Backward-compat invariants (HARD): SymbolInfo unchanged, default tool output
  byte-identical, code_intel tools only wired when enable_repo_map_ranking.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from swarmline.code_intel.ranked_repo_mapper import (
    RankedRepoMapper,
    RankedSymbol,
    RepoMapBudget,
)
from swarmline.code_intel.repo_mapper import ASTRepoMapper
from swarmline.code_intel.types import (
    ImportEdge,
    RepoMap,
    SymbolInfo,
    SymbolKind,
)

# ---------------------------------------------------------------------------
# Test fixtures — small synthetic repos written to tmp_path
# ---------------------------------------------------------------------------


def _write_repo(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


# A repo where ``core`` is imported by everyone (high centrality), and a
# ``leaf`` module imported by no one (low centrality).
_HUB_AND_LEAF = {
    "core.py": "class Core:\n    def run(self):\n        return 1\n",
    "leaf.py": "def lonely():\n    return 0\n",
    "a.py": "from core import Core\n\ndef use_a():\n    return Core()\n",
    "b.py": "from core import Core\n\ndef use_b():\n    return Core()\n",
    "c.py": "from core import Core\n\ndef use_c():\n    return Core()\n",
}


# ---------------------------------------------------------------------------
# RankedRepoMapper — delegation contract (unchanged base output)
# ---------------------------------------------------------------------------


class TestRankedRepoMapperDelegation:
    """scan_repo/scan_file delegate to base and return UNRANKED base output."""

    def test_scan_repo_returns_same_repo_map_as_base(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, _HUB_AND_LEAF)
        base = ASTRepoMapper()
        ranked = RankedRepoMapper(base=base)

        base_map = base.scan_repo(str(tmp_path), {".py"})
        ranked_map = ranked.scan_repo(str(tmp_path), {".py"})

        assert isinstance(ranked_map, RepoMap)
        assert ranked_map == base_map

    def test_scan_file_returns_same_symbols_as_base(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, _HUB_AND_LEAF)
        base = ASTRepoMapper()
        ranked = RankedRepoMapper(base=base)

        target = str(tmp_path / "core.py")
        assert ranked.scan_file(target) == base.scan_file(target)


# ---------------------------------------------------------------------------
# RankedRepoMapper.rank — centrality ordering
# ---------------------------------------------------------------------------


class TestRankedRepoMapperCentrality:
    """Symbols in highly-referenced (central) files rank above leaf symbols."""

    def test_high_reference_symbol_ranks_first(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, _HUB_AND_LEAF)
        mapper = RankedRepoMapper(base=ASTRepoMapper())
        repo_map = mapper.scan_repo(str(tmp_path), {".py"})

        ranked = mapper.rank(repo_map)

        assert ranked, "expected at least one ranked symbol"
        # Result is sorted by rank descending.
        ranks = [r.rank for r in ranked]
        assert ranks == sorted(ranks, reverse=True)

        # The Core class (imported by a/b/c) must outrank the lonely leaf func.
        core_rank = max(
            r.rank for r in ranked if r.symbol.file_path.endswith("core.py")
        )
        leaf_rank = max(
            r.rank for r in ranked if r.symbol.file_path.endswith("leaf.py")
        )
        assert core_rank > leaf_rank

    def test_rank_wraps_symbolinfo_without_mutation(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, _HUB_AND_LEAF)
        mapper = RankedRepoMapper(base=ASTRepoMapper())
        repo_map = mapper.scan_repo(str(tmp_path), {".py"})

        ranked = mapper.rank(repo_map)

        for rs in ranked:
            assert isinstance(rs, RankedSymbol)
            assert isinstance(rs.symbol, SymbolInfo)
            assert isinstance(rs.rank, float)
        # Every base symbol is represented exactly once.
        assert {id(rs.symbol) for rs in ranked}  # distinct wrappers
        assert len(ranked) == len(repo_map.symbols)

    def test_rank_is_deterministic(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, _HUB_AND_LEAF)
        mapper = RankedRepoMapper(base=ASTRepoMapper())
        repo_map = mapper.scan_repo(str(tmp_path), {".py"})

        first = mapper.rank(repo_map)
        second = mapper.rank(repo_map)
        assert first == second


# ---------------------------------------------------------------------------
# RankedRepoMapper.rank — context_files personalization boost
# ---------------------------------------------------------------------------


class TestRankedRepoMapperContextBoost:
    """A symbol whose file is in context_files ranks above an equivalent one."""

    def test_context_file_symbol_outranks_equivalent_non_context(
        self, tmp_path: Path
    ) -> None:
        # Two structurally symmetric leaf files: neither is imported.
        files = {
            "ctx.py": "def thing():\n    return 1\n",
            "other.py": "def thing():\n    return 1\n",
        }
        _write_repo(tmp_path, files)
        ctx_path = str(tmp_path / "ctx.py")

        base = ASTRepoMapper()
        repo_map = base.scan_repo(str(tmp_path), {".py"})

        plain = RankedRepoMapper(base=base).rank(repo_map)
        boosted = RankedRepoMapper(base=base, context_files=(ctx_path,)).rank(repo_map)

        # Without personalization the two symmetric symbols tie.
        plain_ctx = next(r.rank for r in plain if r.symbol.file_path == ctx_path)
        plain_other = next(
            r.rank for r in plain if r.symbol.file_path.endswith("other.py")
        )
        assert plain_ctx == pytest.approx(plain_other)

        # With personalization the context file's symbol strictly outranks.
        boosted_ctx = next(r.rank for r in boosted if r.symbol.file_path == ctx_path)
        boosted_other = next(
            r.rank for r in boosted if r.symbol.file_path.endswith("other.py")
        )
        assert boosted_ctx > boosted_other
        # And it becomes the top-ranked symbol.
        assert boosted[0].symbol.file_path == ctx_path

    def test_context_boost_holds_when_context_is_large_majority(
        self, tmp_path: Path
    ) -> None:
        """F2: a context node strictly outranks an equivalent non-context node even
        when context covers the large majority of files (9 of 10) — and the teleport
        vector still sums to 1.0.
        """
        from swarmline.code_intel.ranked_repo_mapper import _personalization_vector

        # 10 symmetric, mutually-unconnected leaf files.
        files = {f"m{i}.py": "def thing():\n    return 1\n" for i in range(10)}
        _write_repo(tmp_path, files)
        nodes = [str(tmp_path / f"m{i}.py") for i in range(10)]
        # 9 of 10 files are context; m9 is the lone non-context file.
        context_paths = tuple(nodes[:9])
        the_other = nodes[9]

        # The personalization vector sums to 1.0 and every context node strictly
        # exceeds the single non-context node.
        vec = _personalization_vector(nodes, set(context_paths))
        assert sum(vec.values()) == pytest.approx(1.0)
        for ctx_node in context_paths:
            assert vec[ctx_node] > vec[the_other]

        base = ASTRepoMapper()
        repo_map = base.scan_repo(str(tmp_path), {".py"})
        boosted = RankedRepoMapper(base=base, context_files=context_paths).rank(
            repo_map
        )

        ranks = {r.symbol.file_path: r.rank for r in boosted}
        for ctx_path in context_paths:
            assert ranks[ctx_path] > ranks[the_other]

    def test_personalization_vector_sums_to_one_in_all_regimes(self) -> None:
        """F2: teleport vector sums to 1.0 with no/partial/full context coverage."""
        from swarmline.code_intel.ranked_repo_mapper import _personalization_vector

        nodes = [f"f{i}.py" for i in range(5)]
        # No context (uniform).
        assert sum(_personalization_vector(nodes, set()).values()) == pytest.approx(1.0)
        # Partial context.
        assert sum(
            _personalization_vector(nodes, {"f0.py", "f1.py"}).values()
        ) == pytest.approx(1.0)
        # Full context == all nodes -> falls back to uniform, still sums to 1.0.
        assert sum(
            _personalization_vector(nodes, set(nodes)).values()
        ) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# RankedRepoMapper.rank — order independence (determinism)
# ---------------------------------------------------------------------------


class TestRankedRepoMapperOrderIndependence:
    """Same logical graph in different input order -> identical ranked order (F1)."""

    def test_ranked_repo_map_order_independent(self) -> None:
        """Two RepoMaps with the SAME logical graph but files/imports/symbols in a
        different input order produce an IDENTICAL ranked sequence.
        """

        # Hub imported by a/b/c; leaf isolated. Two symbols per file to expose any
        # within-file tie instability.
        def _symbols(order: list[str]) -> tuple[SymbolInfo, ...]:
            out: list[SymbolInfo] = []
            for f in order:
                base = f.rsplit("/", 1)[-1][:-3]
                out.append(
                    SymbolInfo(base.title(), SymbolKind.CLASS, f, 1, f"class {base}")
                )
                out.append(
                    SymbolInfo(
                        f"{base}_fn", SymbolKind.FUNCTION, f, 5, f"def {base}_fn()"
                    )
                )
            return tuple(out)

        files_fwd = ["/r/hub.py", "/r/leaf.py", "/r/a.py", "/r/b.py", "/r/c.py"]
        files_rev = list(reversed(files_fwd))
        imports_fwd = (
            ImportEdge("/r/a.py", "hub", ("Hub",)),
            ImportEdge("/r/b.py", "hub", ("Hub",)),
            ImportEdge("/r/c.py", "hub", ("Hub",)),
        )
        imports_rev = tuple(reversed(imports_fwd))

        map_fwd = RepoMap(
            root_path="/r",
            files=tuple(files_fwd),
            symbols=_symbols(files_fwd),
            imports=imports_fwd,
        )
        map_rev = RepoMap(
            root_path="/r",
            files=tuple(files_rev),
            symbols=_symbols(files_rev),
            imports=imports_rev,
        )

        mapper = RankedRepoMapper(base=ASTRepoMapper())
        ranked_fwd = mapper.rank(map_fwd)
        ranked_rev = mapper.rank(map_rev)

        # Identical ranked ORDER: same (file_path, line, name) sequence.
        order_fwd = [
            (r.symbol.file_path, r.symbol.line, r.symbol.name) for r in ranked_fwd
        ]
        order_rev = [
            (r.symbol.file_path, r.symbol.line, r.symbol.name) for r in ranked_rev
        ]
        assert order_fwd == order_rev


# ---------------------------------------------------------------------------
# RepoMapBudget — deterministic prefix truncation
# ---------------------------------------------------------------------------


def _ranked_chain(n: int) -> tuple[RankedSymbol, ...]:
    """Build n RankedSymbols already sorted by rank descending."""
    out: list[RankedSymbol] = []
    for i in range(n):
        sym = SymbolInfo(
            name=f"sym_{i:03d}",
            kind=SymbolKind.FUNCTION,
            file_path=f"mod_{i:03d}.py",
            line=i + 1,
            signature=f"def sym_{i:03d}() -> None",
        )
        out.append(RankedSymbol(symbol=sym, rank=float(n - i)))
    return tuple(out)


class TestRepoMapBudget:
    """fit() keeps the largest rank-ordered prefix that fits the token budget."""

    def test_fit_returns_strict_prefix(self) -> None:
        ranked = _ranked_chain(40)
        budget = RepoMapBudget(max_tokens=120)

        kept = budget.fit(ranked)

        # Kept is a prefix of the input (order + identity preserved).
        assert kept == ranked[: len(kept)]
        assert 0 < len(kept) < len(ranked)

    def test_smaller_budget_keeps_fewer_symbols(self) -> None:
        ranked = _ranked_chain(60)
        big = RepoMapBudget(max_tokens=400).fit(ranked)
        small = RepoMapBudget(max_tokens=80).fit(ranked)

        assert len(small) <= len(big)
        assert len(small) < len(ranked)
        # Smaller budget's kept set is a prefix of the bigger one (monotone).
        assert small == big[: len(small)]

    def test_huge_budget_keeps_everything(self) -> None:
        ranked = _ranked_chain(10)
        kept = RepoMapBudget(max_tokens=1_000_000).fit(ranked)
        assert kept == ranked

    def test_zero_budget_keeps_nothing(self) -> None:
        ranked = _ranked_chain(10)
        kept = RepoMapBudget(max_tokens=0).fit(ranked)
        assert kept == ()

    def test_empty_input_returns_empty(self) -> None:
        kept = RepoMapBudget(max_tokens=4000).fit(())
        assert kept == ()

    def test_budget_is_frozen(self) -> None:
        budget = RepoMapBudget(max_tokens=4000)
        with pytest.raises(dataclasses.FrozenInstanceError):
            budget.max_tokens = 10  # type: ignore[misc]

    def test_fit_custom_measure_bounds_chosen_prefix(self) -> None:
        """fit honors a caller-supplied measure: budget bounds measure(prefix)."""
        ranked = _ranked_chain(50)
        # Each symbol "costs" exactly 10 tokens under this measure (overhead 0).
        kept = RepoMapBudget(max_tokens=35).fit(ranked, measure=lambda p: len(p) * 10)
        assert len(kept) == 3
        assert kept == ranked[:3]

    def test_fit_returns_empty_when_overhead_exceeds_budget(self) -> None:
        """If even the empty prefix (fixed overhead) exceeds the budget, fit -> ()."""
        ranked = _ranked_chain(20)
        # Fixed overhead of 1000 tokens regardless of prefix -> nothing fits.
        kept = RepoMapBudget(max_tokens=100).fit(
            ranked, measure=lambda p: 1000 + len(p) * 10
        )
        assert kept == ()

    def test_budget_bounds_full_output(self) -> None:
        """F3: the FULL emitted repo_map JSON (//4) is <= a small budget.

        With many symbols and a tight budget, the wired executor's full-output
        measure forces truncation so the *entire* serialized output — not just the
        symbols list — respects max_tokens, while keeping as many top symbols as fit
        alongside the fixed root_path/files/imports overhead.
        """
        from swarmline.code_intel.ranked_repo_mapper import RankedSymbol
        from swarmline.code_intel.tools import serialize_repo_map

        # Build a repo_map with fixed overhead (files/imports) + many symbols.
        files = tuple(f"/repo/mod_{i:03d}.py" for i in range(30))
        symbols = tuple(
            SymbolInfo(
                name=f"sym_{i:03d}",
                kind=SymbolKind.FUNCTION,
                file_path=f"/repo/mod_{i:03d}.py",
                line=1,
                signature=f"def sym_{i:03d}() -> None",
            )
            for i in range(30)
        )
        imports = tuple(
            ImportEdge(f"/repo/mod_{i:03d}.py", "mod_000", ("sym_000",))
            for i in range(1, 30)
        )
        repo_map = RepoMap(
            root_path="/repo", files=files, symbols=symbols, imports=imports
        )
        ranked = tuple(
            RankedSymbol(symbol=s, rank=float(len(symbols) - i))
            for i, s in enumerate(symbols)
        )

        def _measure_full(prefix: tuple[RankedSymbol, ...]) -> int:
            return len(serialize_repo_map(repo_map, ranking=prefix)) // 4

        # Overhead alone (root_path + files + imports, no symbols) is ~860 tokens;
        # the full output is ~1880. A 1200-token budget leaves room for SOME but not
        # all symbols, proving the full output (not just the symbols list) is bounded.
        overhead = _measure_full(())
        full = _measure_full(ranked)
        assert overhead < full  # symbols genuinely add weight
        max_tokens = 1200
        assert overhead < max_tokens < full

        fitted = RepoMapBudget(max_tokens=max_tokens).fit(ranked, measure=_measure_full)

        # Some symbols are dropped (tight budget) but at least some kept alongside overhead.
        assert 0 < len(fitted) < len(symbols)
        # The FULL emitted output respects the budget.
        out = serialize_repo_map(repo_map, ranking=fitted)
        assert len(out) // 4 <= max_tokens
        # Adding one more symbol would exceed the budget (it is the largest fitting prefix).
        over = serialize_repo_map(repo_map, ranking=ranked[: len(fitted) + 1])
        assert len(over) // 4 > max_tokens

        # Overhead-exceeds-budget regime: a budget below the fixed overhead yields ()
        # (no symbols) rather than crashing — the unavoidable structural minimum.
        starved = RepoMapBudget(max_tokens=overhead - 1).fit(
            ranked, measure=_measure_full
        )
        assert starved == ()


# ---------------------------------------------------------------------------
# Backward-compat invariant: SymbolInfo unchanged
# ---------------------------------------------------------------------------


def test_symbolinfo_unchanged() -> None:
    """SymbolInfo public repr / asdict output is byte-identical to its definition.

    Guards M1: RankedSymbol must NOT touch or shadow SymbolInfo's surface.
    """
    sym = SymbolInfo(
        name="Core",
        kind=SymbolKind.CLASS,
        file_path="core.py",
        line=1,
        signature="class Core",
    )

    # repr is stable and shows exactly the 5 declared fields, no rank.
    assert repr(sym) == (
        "SymbolInfo(name='Core', kind=<SymbolKind.CLASS: 'class'>, "
        "file_path='core.py', line=1, signature='class Core')"
    )

    # asdict carries exactly the 5 fields — no 'rank' leakage.
    assert dataclasses.asdict(sym) == {
        "name": "Core",
        "kind": SymbolKind.CLASS,
        "file_path": "core.py",
        "line": 1,
        "signature": "class Core",
    }

    # Field set is exactly the original five, in order.
    assert [f.name for f in dataclasses.fields(SymbolInfo)] == [
        "name",
        "kind",
        "file_path",
        "line",
        "signature",
    ]
    # Still frozen + slotted.
    assert SymbolInfo.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        sym.name = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Backward-compat invariant: default tool output byte-identical (flag off)
# ---------------------------------------------------------------------------


def _make_default_repo_map_tool() -> Any:
    """Build the default (unranked) repo_map executor via create_code_intel_tools."""
    from swarmline.code_intel.coverage_checker import ImportBasedCoverageAnalyzer
    from swarmline.code_intel.impact_analyzer import GraphImpactAnalyzer
    from swarmline.code_intel.language_parsers import (
        CompositeLanguageParser,
        PythonSeamParser,
    )
    from swarmline.code_intel.tools import create_code_intel_tools

    parser = CompositeLanguageParser()
    parser.register_parser(PythonSeamParser())
    _, executors = create_code_intel_tools(
        repo_mapper=ASTRepoMapper(),
        impact_analyzer=GraphImpactAnalyzer(),
        language_parser=parser,
        coverage_analyzer=ImportBasedCoverageAnalyzer(),
    )
    return executors["repo_map"]


class TestDefaultToolOutputByteIdentical:
    """With ranking off, repo_map tool JSON has no 'rank' key and is unchanged."""

    def test_default_repo_map_tool_has_no_rank_key(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, _HUB_AND_LEAF)
        repo_map_tool = _make_default_repo_map_tool()

        out = repo_map_tool({"root_path": str(tmp_path)})
        payload = json.loads(out)

        for sym in payload["symbols"]:
            assert "rank" not in sym
            assert set(sym.keys()) == {
                "name",
                "kind",
                "file_path",
                "line",
                "signature",
            }

    def test_ranked_serializer_default_path_byte_identical(
        self, tmp_path: Path
    ) -> None:
        """serialize_repo_map(..., ranking=None) byte-equals the legacy tool output."""
        from swarmline.code_intel.tools import serialize_repo_map

        _write_repo(tmp_path, _HUB_AND_LEAF)
        repo_map = ASTRepoMapper().scan_repo(str(tmp_path), {".py"})

        legacy = _make_default_repo_map_tool()({"root_path": str(tmp_path)})
        unranked = serialize_repo_map(repo_map, ranking=None)

        assert unranked == legacy


# ---------------------------------------------------------------------------
# Ranked serializer path (flag on): includes rank, sorted desc, budget-truncated
# ---------------------------------------------------------------------------


class TestRankedSerializer:
    """serialize_repo_map with a ranking emits rank, sorted desc, budget-fit."""

    def test_ranked_output_includes_rank_sorted_desc(self, tmp_path: Path) -> None:
        from swarmline.code_intel.tools import serialize_repo_map

        _write_repo(tmp_path, _HUB_AND_LEAF)
        mapper = RankedRepoMapper(base=ASTRepoMapper())
        repo_map = mapper.scan_repo(str(tmp_path), {".py"})
        ranked = mapper.rank(repo_map)

        out = serialize_repo_map(
            repo_map, ranking=RepoMapBudget(max_tokens=4000).fit(ranked)
        )
        payload = json.loads(out)

        ranks = [s["rank"] for s in payload["symbols"]]
        assert ranks == sorted(ranks, reverse=True)
        for sym in payload["symbols"]:
            assert "rank" in sym

    def test_ranked_output_truncated_by_budget(self, tmp_path: Path) -> None:
        from swarmline.code_intel.tools import serialize_repo_map

        _write_repo(tmp_path, _HUB_AND_LEAF)
        mapper = RankedRepoMapper(base=ASTRepoMapper())
        repo_map = mapper.scan_repo(str(tmp_path), {".py"})
        ranked = mapper.rank(repo_map)

        tight = serialize_repo_map(
            repo_map, ranking=RepoMapBudget(max_tokens=40).fit(ranked)
        )
        loose = serialize_repo_map(
            repo_map, ranking=RepoMapBudget(max_tokens=4000).fit(ranked)
        )

        tight_n = len(json.loads(tight)["symbols"])
        loose_n = len(json.loads(loose)["symbols"])
        assert tight_n <= loose_n
        assert tight_n < len(repo_map.symbols)


# ---------------------------------------------------------------------------
# Opt-in wiring (M5): code_intel tools only when enable_repo_map_ranking
# ---------------------------------------------------------------------------


class TestCodeIntelOptinWiring:
    """build_coding_toolpack includes the 5 code_intel tools ONLY when ranking on."""

    def test_toolpack_omits_code_intel_tools_when_flag_off(
        self, coding_sandbox: Any
    ) -> None:
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.runtime.thin.coding_toolpack import (
            CODING_CODE_INTEL_TOOL_NAMES,
            build_coding_toolpack,
        )

        pack = build_coding_toolpack(
            coding_sandbox, config=CodingProfileConfig(enable_repo_map_ranking=False)
        )
        assert CODING_CODE_INTEL_TOOL_NAMES.isdisjoint(pack.tool_names)

    def test_toolpack_omits_code_intel_tools_when_config_none(
        self, coding_sandbox: Any
    ) -> None:
        from swarmline.runtime.thin.coding_toolpack import (
            CODING_CODE_INTEL_TOOL_NAMES,
            build_coding_toolpack,
        )

        pack = build_coding_toolpack(coding_sandbox, config=None)
        assert CODING_CODE_INTEL_TOOL_NAMES.isdisjoint(pack.tool_names)

    def test_toolpack_includes_all_five_code_intel_tools_when_flag_on(
        self, coding_sandbox: Any
    ) -> None:
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.runtime.thin.coding_toolpack import (
            CODING_CODE_INTEL_TOOL_NAMES,
            build_coding_toolpack,
        )

        pack = build_coding_toolpack(
            coding_sandbox, config=CodingProfileConfig(enable_repo_map_ranking=True)
        )
        assert CODING_CODE_INTEL_TOOL_NAMES.issubset(pack.tool_names)
        # Name parity invariant preserved.
        assert set(pack.specs.keys()) == set(pack.executors.keys())

    def test_default_toolpack_byte_identical_when_flag_off(
        self, coding_sandbox: Any
    ) -> None:
        """flag-off pack has EXACTLY the same tool surface as no-config (sandbox+todo)."""
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        pack_no_config = build_coding_toolpack(coding_sandbox)
        pack_flag_off = build_coding_toolpack(
            coding_sandbox, config=CodingProfileConfig(enable_repo_map_ranking=False)
        )

        assert pack_no_config.tool_names == pack_flag_off.tool_names
        assert set(pack_no_config.executors.keys()) == set(
            pack_flag_off.executors.keys()
        )

    def test_ranked_repo_map_tool_emits_rank_when_wired(
        self, coding_sandbox: Any, tmp_path: Path
    ) -> None:
        """When wired on, the pack's repo_map tool produces ranked (rank-bearing) JSON."""
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        _write_repo(tmp_path, _HUB_AND_LEAF)
        pack = build_coding_toolpack(
            coding_sandbox, config=CodingProfileConfig(enable_repo_map_ranking=True)
        )
        out = pack.executors["repo_map"]({"root_path": str(tmp_path)})
        payload = json.loads(out)
        assert payload["symbols"], "expected ranked symbols"
        assert all("rank" in s for s in payload["symbols"])
        ranks = [s["rank"] for s in payload["symbols"]]
        assert ranks == sorted(ranks, reverse=True)


# ---------------------------------------------------------------------------
# RepoMapperPort structural conformance
# ---------------------------------------------------------------------------


def test_ranked_repo_mapper_satisfies_repo_mapper_port() -> None:
    """RankedRepoMapper is a structural RepoMapperPort (scan_repo/scan_file)."""
    from swarmline.code_intel.protocols import RepoMapperPort

    mapper = RankedRepoMapper(base=ASTRepoMapper())
    assert isinstance(mapper, RepoMapperPort)


def test_import_graph_centrality_with_synthetic_repo_map() -> None:
    """Direct rank() on a hand-built RepoMap: a referenced module beats an isolate."""
    root = "/repo"
    symbols = (
        SymbolInfo("Hub", SymbolKind.CLASS, "/repo/hub.py", 1, "class Hub"),
        SymbolInfo("Isolate", SymbolKind.CLASS, "/repo/isolate.py", 1, "class Isolate"),
    )
    imports = (
        ImportEdge("/repo/a.py", "hub", ("Hub",)),
        ImportEdge("/repo/b.py", "hub", ("Hub",)),
    )
    repo_map = RepoMap(
        root_path=root,
        files=("/repo/hub.py", "/repo/isolate.py", "/repo/a.py", "/repo/b.py"),
        symbols=symbols,
        imports=imports,
    )
    ranked = RankedRepoMapper(base=ASTRepoMapper()).rank(repo_map)
    by_file = {r.symbol.file_path: r.rank for r in ranked}
    assert by_file["/repo/hub.py"] > by_file["/repo/isolate.py"]
