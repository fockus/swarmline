"""Encoding for MODEL-CONTROLLED scratchpad keys.

Scratchpad keys are chosen by the model, and several backends compose them into
a hierarchical address — ``namespace + "/" + key`` for the namespaced decorator,
``namespace_uri + "/" + key`` for the OpenViking provider. Concatenating a raw
key into such an address is ambiguous and unsafe:

* ``namespace="a"`` + ``key="b/plan"`` and ``namespace="a/b"`` + ``key="plan"``
  produce the same address, so one namespace can address another's entries just
  by embedding a separator;
* ``..`` segments can be normalised by a path-aware backend and walk out of the
  namespace entirely;
* an empty key collapses to the namespace itself.

Encoding — rather than rejecting — keeps every key the model might reasonably
choose usable (``notes/2026-07``, ``plan.md``) while guaranteeing the encoded
form is a single opaque segment: no ``/``, no ``.``, so no traversal and no
boundary ambiguity. The transform is reversible, so entries round-trip back to
the caller under the key it originally used.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

__all__ = ["encode_key", "decode_key", "InvalidScratchpadKeyError"]


class InvalidScratchpadKeyError(ValueError):
    """The key cannot be represented as an address segment (empty/blank)."""


def encode_key(key: str) -> str:
    """Return ``key`` as a single opaque address segment.

    Raises:
        InvalidScratchpadKeyError: if the key is empty or only whitespace — such
            a key would collapse to the namespace itself, making the entry
            indistinguishable from the container that holds it.
    """
    if not key or not key.strip():
        raise InvalidScratchpadKeyError(
            "scratchpad key must be a non-empty, non-blank string"
        )
    # `safe=""` encodes the separator. `.` is unconditionally safe in `quote`
    # and cannot be excluded via `safe`, so it is escaped afterwards — otherwise
    # a key of `..` would survive as a traversal segment. Unambiguous because
    # `quote` already turned any literal `%` into `%25`.
    return quote(key, safe="").replace(".", "%2E")


def decode_key(encoded: str) -> str:
    """Inverse of :func:`encode_key`."""
    return unquote(encoded)
