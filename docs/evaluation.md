# Agent Evaluation

Cognitia includes a built-in evaluation framework for measuring agent quality across multiple dimensions.

## Quick Start

```python
from cognitia.eval.runner import EvalRunner
from cognitia.eval.scorers import ContainsScorer, ExactMatchScorer
from cognitia.eval.reporters import ConsoleReporter
from cognitia.eval.types import EvalCase

suite = [
    EvalCase(id="geo-1", input="Capital of France?", expected="Paris"),
    EvalCase(id="math-1", input="2+2?", expected="4"),
]

runner = EvalRunner()
report = await runner.run(agent=my_agent, suite=suite, scorers=[
    ExactMatchScorer(),
    ContainsScorer(),
])

print(ConsoleReporter().format(report))
```

## Concepts

### EvalCase

A single test case with input, expected output, and optional context:

```python
EvalCase(
    id="unique-id",
    input="user prompt",
    expected="expected answer or substring",
    context={"latency_ms": 200, "cost_usd": 0.003},  # metadata for scorers
    tags=("category", "difficulty"),
)
```

### Scorers

Scorers evaluate agent output and return a `ScorerResult` (score 0.0-1.0 + reason).

| Scorer | What it checks |
|--------|---------------|
| `ExactMatchScorer` | `output == expected` (optional case-insensitive) |
| `ContainsScorer` | `expected in output` |
| `RegexScorer` | Regex pattern match on output |
| `LatencyScorer` | Response time under threshold |
| `CostScorer` | Token cost under budget |

### EvalReport

Aggregated results with statistics:

```python
report.total      # number of cases
report.passed     # cases where all scores >= 0.5
report.failed     # total - passed
report.pass_rate  # passed / total
report.mean_score # average across all cases

# Per-scorer stats
report.scorer_stats("contains")  # {"mean": 0.85, "min": 0.0, "max": 1.0, "p50": 1.0, "p95": 1.0}
```

## Reporters

### Console

```python
from cognitia.eval.reporters import ConsoleReporter
print(ConsoleReporter().format(report))
```

### JSON (for CI/CD)

```python
from cognitia.eval.reporters import JsonReporter
json_str = JsonReporter(indent=2).format(report)
```

## Custom Scorers

Implement the `Scorer` protocol:

```python
from cognitia.eval.types import EvalCase, Scorer, ScorerResult

class MyCustomScorer:
    @property
    def name(self) -> str:
        return "custom"

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        # Your scoring logic
        is_good = "thank you" in output.lower()
        return ScorerResult(
            score=1.0 if is_good else 0.0,
            reason="polite" if is_good else "impolite",
        )
```

## Compare

Compare two eval runs to track regressions and improvements:

```python
from cognitia.eval.compare import EvalComparator

comparison = EvalComparator.compare(baseline_report, new_report, threshold=0.05)

print(comparison.format_summary())
# Comparison: 3 improved, 1 regressed, 6 unchanged
# Mean score: 0.82 -> 0.87 (+0.05)
# Pass rate:  80% -> 90% (+10%)
# --------------------------------------------------
#   [+] geo-1: 0.75 -> 1.00
#   [-] math-3: 1.00 -> 0.50
#   [=] code-1: 0.90 -> 0.90
```

### ComparisonReport

| Property | Type | Description |
|----------|------|-------------|
| `cases` | `tuple[CaseComparison, ...]` | Per-case comparison results |
| `mean_score_delta` | `float` | Change in mean score |
| `pass_rate_delta` | `float` | Change in pass rate |
| `improved` | `int` | Cases that improved |
| `regressed` | `int` | Cases that regressed |
| `unchanged` | `int` | Cases within threshold |

### CaseComparison

| Field | Description |
|-------|-------------|
| `status` | `"improved"`, `"regressed"`, `"unchanged"`, `"new"`, `"removed"` |
| `delta` | Score difference (target - base) |
| `score_deltas` | Per-scorer delta dict |

## History

Persist eval reports to JSON for tracking over time:

```python
from cognitia.eval.history import EvalHistory

# Save
EvalHistory.save(
    report,
    "evals/run-2026-03-30.json",
    run_id="v1.2.0-baseline",
    metadata={"model": "sonnet", "runtime": "thin"},
)

# Load
loaded = EvalHistory.load("evals/run-2026-03-30.json")
print(loaded.pass_rate)
```

Use `EvalHistory` with `EvalComparator` for CI/CD regression testing:

```python
baseline = EvalHistory.load("evals/baseline.json")
current = await runner.run(agent=agent, suite=suite, scorers=scorers)

comparison = EvalComparator.compare(baseline, current)
if comparison.regressed > 0:
    print(f"REGRESSION: {comparison.regressed} cases regressed")
    print(comparison.format_summary())
```

## Example

See [`examples/32_agent_evaluation.py`](https://github.com/fockus/cognitia/blob/main/examples/32_agent_evaluation.py) for a complete runnable example.
