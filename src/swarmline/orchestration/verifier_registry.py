"""VerifierRegistry — criterion-key → zero-arg verifier closure (M4 fix).

Replaces the hardcoded ``method_map`` inside :class:`DoDStateMachine` with a
pluggable, frozen registry of closures. ``VerifierRegistry.default(verifier)``
reproduces the existing 5-criterion behaviour *byte-for-byte* (same keys, same
bound methods, same order of dispatch). ``with_check`` returns a new registry
with an extra criterion (used for ``lint_delta`` / ``lsp`` later) without a
6th ``CodeVerifier`` method.

Clean Architecture: depends only on the ``CodeVerifier`` protocol and
``VerificationResult`` value object — no infrastructure imports.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from swarmline.orchestration.code_verifier import CodeVerifier
from swarmline.orchestration.verification_types import VerificationResult

# A criterion verifier: a zero-arg coroutine bound to a verifier at build time.
VerifierFn = Callable[[], Awaitable[VerificationResult]]


@dataclass(frozen=True, slots=True)
class VerifierRegistry:
    """Immutable mapping of DoD criterion-key → zero-arg verifier closure.

    The keys are the canonical criterion names (``contracts``, ``tests``,
    ``tdd``, ``linters``, ``coverage``) — identical to the legacy ``method_map``
    keys — so a ``None`` registry path stays byte-identical.
    """

    fns: Mapping[str, VerifierFn]

    @staticmethod
    def default(verifier: CodeVerifier) -> VerifierRegistry:
        """Build the canonical registry: 5 closures bound to the verifier's
        5 ``verify_*`` methods, keyed by the SAME criterion keys the legacy
        ``method_map`` used. Preserves exact behaviour.
        """
        fns: dict[str, VerifierFn] = {
            "contracts": verifier.verify_contracts,
            "tests": verifier.verify_tests_substantive,
            "tdd": verifier.verify_tests_before_code,
            "linters": verifier.verify_linters,
            # verify_coverage has a defaulted min_pct; the legacy path called it
            # with no argument (default 85). Wrap so the closure stays zero-arg.
            "coverage": _coverage_closure(verifier),
        }
        return VerifierRegistry(fns=MappingProxyType(fns))

    def with_check(self, key: str, fn: VerifierFn) -> VerifierRegistry:
        """Return a NEW registry with an extra criterion added (immutable)."""
        merged: dict[str, VerifierFn] = dict(self.fns)
        merged[key] = fn
        return VerifierRegistry(fns=MappingProxyType(merged))


def _coverage_closure(verifier: CodeVerifier) -> VerifierFn:
    """Bind ``verify_coverage`` as a zero-arg closure (legacy default min_pct)."""

    async def _run() -> VerificationResult:
        return await verifier.verify_coverage()

    return _run
