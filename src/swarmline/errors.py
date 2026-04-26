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
