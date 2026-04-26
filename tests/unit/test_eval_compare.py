"""Unit: EvalComparator and EvalHistory."""

from __future__ import annotations

import json
from pathlib import Path

from swarmline.eval.compare import EvalComparator
from swarmline.eval.history import EvalHistory
from swarmline.eval.types import EvalCase, EvalReport, EvalResult, ScorerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(case_id: str, scores: dict[str, float], output: str = "out") -> EvalResult:
    case = EvalCase(id=case_id, input=f"input-{case_id}")
    return EvalResult(
        case=case,
        output=output,
        scores={name: ScorerResult(score=s, reason="") for name, s in scores.items()},
    )


def _report(*results: EvalResult) -> EvalReport:
    return EvalReport(results=tuple(results))


# ---------------------------------------------------------------------------
# EvalComparator
# ---------------------------------------------------------------------------


class TestEvalComparator:
    def test_compare_improved_case(self) -> None:
        base = _report(_result("c1", {"s": 0.3}))
        target = _report(_result("c1", {"s": 0.9}))
        diff = EvalComparator.compare(base, target)
        assert len(diff.cases) == 1
        assert diff.cases[0].status == "improved"

    def test_compare_regressed_case(self) -> None:
        base = _report(_result("c1", {"s": 0.9}))
        target = _report(_result("c1", {"s": 0.3}))
        diff = EvalComparator.compare(base, target)
        assert diff.cases[0].status == "regressed"

    def test_compare_unchanged_case(self) -> None:
        base = _report(_result("c1", {"s": 0.8}))
        target = _report(_result("c1", {"s": 0.8}))
        diff = EvalComparator.compare(base, target)
        assert diff.cases[0].status == "unchanged"

    def test_compare_new_case_in_target(self) -> None:
        base = _report(_result("c1", {"s": 0.5}))
        target = _report(_result("c1", {"s": 0.5}), _result("c2", {"s": 0.7}))
        diff = EvalComparator.compare(base, target)
        assert len(diff.cases) == 2
        new_cases = [c for c in diff.cases if c.status == "new"]
        assert len(new_cases) == 1
        assert new_cases[0].case_id == "c2"

    def test_compare_removed_case(self) -> None:
        base = _report(_result("c1", {"s": 0.5}), _result("c2", {"s": 0.7}))
        target = _report(_result("c1", {"s": 0.5}))
        diff = EvalComparator.compare(base, target)
        removed = [c for c in diff.cases if c.status == "removed"]
        assert len(removed) == 1
        assert removed[0].case_id == "c2"

    def test_aggregate_delta(self) -> None:
        base = _report(_result("c1", {"s": 0.4}), _result("c2", {"s": 0.6}))
        target = _report(_result("c1", {"s": 0.8}), _result("c2", {"s": 0.9}))
        diff = EvalComparator.compare(base, target)
        assert diff.mean_score_delta > 0
        assert diff.pass_rate_delta >= 0

    def test_compare_multiple_scorers(self) -> None:
        base = _report(_result("c1", {"exact": 0.0, "contains": 1.0}))
        target = _report(_result("c1", {"exact": 1.0, "contains": 1.0}))
        diff = EvalComparator.compare(base, target)
        assert diff.cases[0].status == "improved"
        assert "exact" in diff.cases[0].score_deltas

    def test_format_summary(self) -> None:
        base = _report(_result("c1", {"s": 0.3}))
        target = _report(_result("c1", {"s": 0.9}))
        diff = EvalComparator.compare(base, target)
        text = diff.format_summary()
        assert "improved" in text.lower() or "c1" in text

    def test_empty_reports(self) -> None:
        diff = EvalComparator.compare(_report(), _report())
        assert len(diff.cases) == 0
        assert diff.mean_score_delta == 0.0


# ---------------------------------------------------------------------------
# EvalHistory
# ---------------------------------------------------------------------------


class TestEvalHistory:
    def test_save_and_load(self, tmp_path: Path) -> None:
        report = _report(_result("c1", {"s": 0.8}))
        path = tmp_path / "eval_run.json"
        EvalHistory.save(report, path, run_id="run-1")
        loaded = EvalHistory.load(path)
        assert loaded.total == 1
        assert loaded.results[0].case.id == "c1"

    def test_save_creates_file(self, tmp_path: Path) -> None:
        report = _report(_result("c1", {"s": 0.5}))
        path = tmp_path / "results.json"
        EvalHistory.save(report, path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["total"] == 1

    def test_load_preserves_scores(self, tmp_path: Path) -> None:
        report = _report(_result("c1", {"exact": 0.9, "contains": 1.0}))
        path = tmp_path / "run.json"
        EvalHistory.save(report, path)
        loaded = EvalHistory.load(path)
        assert abs(loaded.results[0].scores["exact"].score - 0.9) < 0.001

    def test_roundtrip_multiple_cases(self, tmp_path: Path) -> None:
        report = _report(
            _result("c1", {"s": 0.8}),
            _result("c2", {"s": 0.5}),
            _result("c3", {"s": 1.0}),
        )
        path = tmp_path / "multi.json"
        EvalHistory.save(report, path, run_id="test-run")
        loaded = EvalHistory.load(path)
        assert loaded.total == 3
        ids = {r.case.id for r in loaded.results}
        assert ids == {"c1", "c2", "c3"}

    def test_load_with_metadata(self, tmp_path: Path) -> None:
        report = _report(_result("c1", {"s": 0.5}))
        path = tmp_path / "meta.json"
        EvalHistory.save(report, path, run_id="r1", metadata={"model": "gpt-4"})
        data = json.loads(path.read_text())
        assert data["run_id"] == "r1"
        assert data["metadata"]["model"] == "gpt-4"
