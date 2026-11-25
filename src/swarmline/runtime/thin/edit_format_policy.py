"""EditFormatPolicy — per-model-family edit-format steering (REQ-SCA-010/011).

Different model families apply code edits most reliably in different formats:
GPT/Codex are tuned for unified-diff ``patch`` hunks, while Claude/Gemini/Qwen do
best with explicit ``search_replace`` blocks. This policy maps a model id to the
format its family handles best so the coding brief can steer the model when
``edit_strategy="auto"``.

Data-driven and overridable: ``family_to_format`` is a plain mapping of a
lowercase family marker (matched as a substring of the model id) to a format.
An UNKNOWN model resolves to ``neutral`` (no steering) so a new/unrecognized
model keeps working unchanged — steering is an optimization, never a gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

EditFormat = Literal["search_replace", "patch", "neutral"]

# Default family marker → format. Markers are matched case-insensitively as a
# substring of the model id; the first matching family wins (insertion order).
# Order matters: the search_replace families precede "gpt" so a Qwen "GPTQ"
# quantized variant (which contains the substring "gpt") still resolves to
# search_replace rather than being mis-steered to patch.
_DEFAULT_FAMILY_TO_FORMAT: dict[str, EditFormat] = {
    "claude": "search_replace",
    "gemini": "search_replace",
    "qwen": "search_replace",
    "codex": "patch",
    "gpt": "patch",
}

# One-line guidance per format, injected into the coding brief. ``neutral`` has
# no entry → no steering block is emitted.
_STEERING_BRIEF: dict[EditFormat, str] = {
    "patch": (
        "Edit-format steering: prefer the `patch` format — emit unified-diff-style "
        "hunks (V4A) for multi-file edits."
    ),
    "search_replace": (
        "Edit-format steering: prefer `search_replace` edits — emit exact "
        "SEARCH/REPLACE blocks where the SEARCH text matches the file verbatim."
    ),
}


@dataclass(frozen=True)
class EditFormatPolicy:
    """Resolve the best edit format for a model id (unknown → ``neutral``)."""

    family_to_format: Mapping[str, EditFormat]

    @classmethod
    def default(cls) -> EditFormatPolicy:
        """Policy with the built-in family table (a fresh, mutable-safe copy)."""
        return cls(family_to_format=dict(_DEFAULT_FAMILY_TO_FORMAT))

    def format_for(self, model_id: str) -> EditFormat:
        """Return the steered format for ``model_id`` — ``neutral`` if unknown."""
        mid = (model_id or "").lower()
        for family, fmt in self.family_to_format.items():
            if _family_matches(mid, family):
                return fmt
        return "neutral"


def _family_matches(model_id: str, family: str) -> bool:
    """True when ``family`` appears in ``model_id`` not immediately followed by a letter.

    A trailing letter means the marker is part of a LONGER token, e.g. the "gptq"
    quantization suffix on ``mistral-7b-gptq`` — that is NOT an OpenAI GPT model, so
    the "gpt" marker must not match it (keeps the unknown-family→neutral invariant).
    A digit or separator after the marker (``gpt-4o``, ``gpt4``, ``qwen2.5``) still
    matches. ponytail: a letter-boundary check is enough for real model-id suffixes;
    upgrade to full tokenization only if a marker ever needs mid-letter boundaries.
    """
    start = 0
    while True:
        idx = model_id.find(family, start)
        if idx == -1:
            return False
        after = idx + len(family)
        if after >= len(model_id) or not model_id[after].isalpha():
            return True
        start = idx + 1


def steering_brief(fmt: EditFormat) -> str:
    """One-line edit-format guidance for the coding brief, or ``""`` for neutral."""
    return _STEERING_BRIEF.get(fmt, "")
