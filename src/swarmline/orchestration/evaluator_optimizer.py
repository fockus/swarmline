"""JudgeAgentSignal — an agent-as-judge ``ExternalSignal`` implementation.

workflow-patterns spec, Task 2 (REQ-008, REQ-009, REQ-010, REQ-011).
Implements the EXISTING ``swarmline.protocols.external_signal.ExternalSignal``
port (ISP, 1 method) to drive the evaluator-optimizer pattern (a generator
produces a candidate, a SEPARATE evaluator judges it, feedback refines the
generator) through the ALREADY-existing ``ReflectionKernel`` loop
(``runtime.thin.kernels.reflection``). This module adds ZERO new
kernel/engine/port — the only new production code is one ``ExternalSignal``
implementation; ``ReflectionKernel`` itself is neither edited nor
reimplemented.

REQ-011 — self-judgement is unreliable (arxiv 2310.01798: a model critiquing
its own output is not a trustworthy stop condition — the same rationale
``ExternalSignal``'s own module docstring documents for ``ReflectionKernel``
in general). ``JudgeAgentSignal`` therefore takes its OWN evaluator callable
at construction, injected SEPARATELY from the generator's ``ctx.llm_call``:
``evaluate()`` accepts ``ctx`` only to satisfy the ``ExternalSignal``
signature and never reads ``ctx.llm_call`` to produce a verdict — only the
injected evaluator ever runs.

Verdict format + parser contract (REQ-008, kept intentionally simple):
the injected evaluator receives a judge prompt built from the candidate
``output`` (see ``_build_judge_prompt``) and returns free text. The parser
(``_parse_verdict``) reads the FIRST non-empty line's first word,
case-insensitively:

- first word == ``PASS`` -> ``SignalResult(passed=True, feedback="")``
  (``feedback`` is empty on pass — the ``SignalResult`` dataclass's own
  documented convention).
- first word == ``FAIL`` -> ``SignalResult(passed=False, feedback=<rest>)``,
  where ``<rest>`` is everything after the first line, or (if there is no
  second line) whatever follows "FAIL" on the same line, or — if neither is
  present — the raw verdict text, so ``feedback`` is never empty on a fail.
- anything else (missing/garbled token, empty text) -> FAIL-closed default:
  ``SignalResult(passed=False, feedback=<raw verdict text>)``.

Safe default (fail-closed): an ``ExternalSignal``-gated loop only stops on
``passed=True``. Treating an ambiguous or malformed verdict as PASS would
let a non-cooperating or malfunctioning judge silently rubber-stamp
arbitrary output — exactly the self-judgement failure mode REQ-011 exists to
avoid. Defaulting every unparseable verdict to FAIL (preserving the raw text
as feedback, so a human or the next refine step can see what confused the
parser) keeps an unreliable judge from ever silently approving a candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from swarmline.types import SignalResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from swarmline.types import KernelContext

_JUDGE_PROMPT_TEMPLATE = (
    "You are evaluating a candidate output for correctness and quality.\n\n"
    "Candidate output:\n{output}\n\n"
    "Respond with a verdict in this EXACT format:\n"
    "- First line: exactly the single word PASS or FAIL.\n"
    "- If FAIL, follow with one or more lines of actionable feedback "
    "explaining what is wrong and how to fix it.\n"
    "- If PASS, no further lines are needed."
)


def _build_judge_prompt(output: str) -> str:
    """Build the judge prompt from a candidate ``output`` (contract above)."""
    return _JUDGE_PROMPT_TEMPLATE.format(output=output)


def _parse_verdict(raw: str) -> SignalResult:
    """Parse the evaluator's free-text verdict into a ``SignalResult``.

    Fail-closed (module docstring, "Safe default"): any verdict whose first
    non-empty line's first word is not exactly PASS/FAIL (case-insensitive)
    is treated as FAIL, carrying the raw text as feedback, so an ambiguous
    or unreliable judge can never silently pass a candidate.
    """
    text = raw.strip()
    if not text:
        # Empty / whitespace-only verdict: fail-closed AND carry a non-empty
        # diagnostic feedback (REQ-008 — feedback is never empty on a fail, so
        # ReflectionKernel's refine/loop_limit path always has something to
        # surface instead of a blank last_feedback).
        return SignalResult(
            passed=False,
            feedback="Evaluator returned an empty verdict.",
        )

    lines = text.splitlines()
    first_line = lines[0].strip()
    first_word = first_line.split(maxsplit=1)[0].upper() if first_line else ""

    if first_word == "PASS":
        return SignalResult(passed=True, feedback="")

    if first_word == "FAIL":
        rest = "\n".join(lines[1:]).strip()
        if not rest:
            # No separate feedback lines -- fall back to whatever followed
            # "FAIL" on the same line, else the raw verdict itself, so
            # feedback is never empty on a fail.
            remainder = first_line[len("FAIL") :].strip()
            rest = remainder or text
        return SignalResult(passed=False, feedback=rest)

    # Ambiguous/unparseable -- fail-closed default (module docstring).
    return SignalResult(passed=False, feedback=text)


class JudgeAgentSignal:
    """Agent-as-judge ``ExternalSignal`` implementation (evaluator-optimizer).

    Implements ``swarmline.protocols.external_signal.ExternalSignal``
    structurally (via its ``runtime_checkable`` Protocol — no explicit
    inheritance needed: ``isinstance(JudgeAgentSignal(...), ExternalSignal)``
    holds). Drives the EXISTING ``ReflectionKernel`` loop as its
    ``ExternalSignal``; this class is the "evaluator" half of the
    generator/evaluator split, never a new loop or engine.

    ``evaluator`` is REQUIRED and is a plain async callable
    ``(prompt: str) -> str`` — deliberately the smallest possible judge
    abstraction (YAGNI: no dedicated judge-agent class is needed for this
    port). It MUST be distinct from the generator's ``ctx.llm_call``
    (REQ-011); ``evaluate()`` never touches ``ctx.llm_call``.
    """

    def __init__(self, evaluator: Callable[[str], Awaitable[str]]) -> None:
        if evaluator is None:
            raise ValueError("JudgeAgentSignal requires an evaluator (not None)")
        self._evaluator = evaluator

    async def evaluate(self, output: str, ctx: KernelContext) -> SignalResult:
        """Judge ``output`` via the INJECTED evaluator -- never ``ctx.llm_call``.

        ``ctx`` is accepted only to satisfy the ``ExternalSignal`` Protocol
        signature (REQ-011: the generator's ``ctx.llm_call`` is never read
        here).
        """
        prompt = _build_judge_prompt(output)
        raw_verdict = await self._evaluator(prompt)
        return _parse_verdict(raw_verdict)
