"""Base exception class for all swarmline-raised errors.

Every exception that swarmline raises is a subclass of :class:`SwarmlineError`,
so user code can catch any swarmline failure with a single ``except`` clause::

    from swarmline.errors import SwarmlineError

    try:
        result = await agent.query(prompt)
    except SwarmlineError as exc:
        log.warning("swarmline failure: %s", exc)
"""

from __future__ import annotations


class SwarmlineError(Exception):
    """Base class for all exceptions raised by swarmline.

    All concrete swarmline exception classes (``ThinLlmError``,
    ``StructuredOutputError``, ``A2AClientError``, ``ApprovalDeniedError``, ...)
    subclass this base, so a single ``except SwarmlineError:`` catches any
    swarmline-originated failure.

    Subclasses that previously inherited from :class:`RuntimeError` keep that
    parent via multiple inheritance, so historical ``except RuntimeError:``
    handlers continue to work unchanged.
    """


class UnknownModelError(SwarmlineError, ValueError):
    """Raised when a model slug cannot be resolved to a known provider.

    A slug given WITHOUT a ``provider:`` prefix that matches no registry model/alias —
    and with no explicit ``base_url`` to fall back to an OpenAI-compatible endpoint — is a
    misconfiguration. Previously such a slug silently resolved to the registry default
    (``claude-sonnet-4`` / anthropic), routing to a different model+provider than intended
    (wrong billing / confusing auth error). It now fails loud.

    Also subclasses :class:`ValueError`, so existing ``except ValueError:`` handlers for bad
    arguments keep working alongside ``except SwarmlineError:``.
    """

    def __init__(self, slug: str | None) -> None:
        self.slug = slug
        super().__init__(
            f"Unknown model slug {slug!r}: no matching model in the registry. Use an explicit "
            f"'provider:model' prefix (e.g. 'openrouter:google/gemini-3.5-flash' or "
            f"'anthropic:claude-sonnet-4-20250514'), or pass an explicit base_url for an "
            f"OpenAI-compatible endpoint."
        )
