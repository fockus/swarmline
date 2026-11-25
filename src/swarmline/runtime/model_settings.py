# Attribution: adapted from aider (Apache-2.0)
# Upstream files: aider/models.py, aider/model_settings.yml
# Copyright: (c) Paul Gauthier and contributors
# Changes: reimplemented from scratch for swarmline as ModelSettings frozen
#          dataclass + ModelSettingsResolver; per-model edit_format + weak/editor
#          model tiering concept adapted; no verbatim copy of aider source.
"""Model settings — per-model edit format and weak/editor model tiering.

Design:
- ``ModelSettings`` is a frozen dataclass carrying optional per-model overrides.
- ``ModelSettingsResolver`` resolves a raw model name → ``ModelSettings`` by
  delegating name normalization (alias → exact → prefix) to ``ModelRegistry``
  and looking up per-model extras stored there.
- ``select_aux_model`` is a pure function implementing REQ-RCA-010: route
  auxiliary LLM tasks (summarization, commit messages) to the weak model when
  declared, else return the main model unchanged.
- ``build_aux_llm_call`` builds a concrete ``Callable[[str,str], Awaitable[str]]``
  adapter that routes a single-shot LLM request through the weak model by cloning
  the base ``RuntimeConfig`` with ``model=weak_model_name``.

Byte-identical invariant (REQ-RCA-070):
  Callers MUST gate ``select_aux_model`` / ``build_aux_llm_call`` behind
  ``CodingProfileConfig.enable_model_tiering``.  When the flag is False (the
  default), callers use the main model directly — this module's helpers are never
  invoked and no behaviour changes.

  Stage 6 (context-engineering-manus-parity) addendum, codex R1 [6 MAJOR]:
  ``ThinRuntime`` ALSO invokes ``build_aux_llm_call`` when
  ``native_config["compaction_llm_model"]`` is set, independent of
  ``enable_model_tiering`` — Stage 6's compaction cascade (Ступень B) must
  not require the coding-agent model-tiering feature just to get a working
  Tier 2. Still opt-in/absent-is-a-no-op; REQ-RCA-070's original
  coding_profile-gated call site is unchanged.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from swarmline.runtime.model_registry import ModelRegistry, get_registry


@dataclass(frozen=True)
class ModelSettings:
    """Per-model optional settings resolved from models.yaml.

    Attributes:
        name: Canonical (resolved) model identifier.
        edit_format: Preferred edit strategy for this model family (e.g.
                     ``"diff"``, ``"whole"``). ``None`` when not declared —
                     callers fall back to their own default.
        weak_model_name: Canonical name of a cheaper/faster model to use for
                         auxiliary tasks (REQ-RCA-010). ``None`` when not declared.
        editor_model_name: Canonical name of a model to use as the editor half
                           of an architect split (REQ-RCA-012). Exposed here for
                           Task 3 to consume; Task 2 does NOT activate architect mode.
                           ``None`` when not declared — caller uses main model only.
        use_repo_map: Whether to include a repo-map context block for this model.
                      Defaults to ``True`` (current behaviour preserved).
    """

    name: str
    edit_format: str | None = None
    weak_model_name: str | None = None
    editor_model_name: str | None = None
    use_repo_map: bool = True


@runtime_checkable
class ModelSettingsResolverProtocol(Protocol):
    """DIP boundary — any object with a compatible ``resolve`` method satisfies this.

    Decouples ``ArchitectCoordinator`` and ``wire_architect_coordinator`` from the
    concrete ``ModelSettingsResolver`` so test fakes pass without casting.
    """

    def resolve(self, raw: str | None) -> ModelSettings: ...


class ModelSettingsResolver:
    """Resolve a raw model name to its ``ModelSettings``.

    Reuses ``ModelRegistry`` for alias/prefix/exact normalisation so there is no
    duplicated resolution logic.  The per-model extras dict stored in the registry
    (populated from the optional YAML keys ``edit_format``, ``weak_model``,
    ``editor_model``, ``use_repo_map``) is read once and cached in the registry
    instance — no double YAML load.

    Resolution order:
    1. Delegate name resolution to ``ModelRegistry.resolve()``
       (alias → exact → prefix → default).
    2. Retrieve the extras dict for the resolved model.
    3. If the input was not a known model (``is_known`` is False), return a
       sane generic default ``ModelSettings`` with the raw name and None tiers.
    """

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self._registry = registry if registry is not None else get_registry()

    def resolve(self, raw: str | None) -> ModelSettings:
        """Resolve *raw* to a ``ModelSettings`` instance.

        Args:
            raw: Raw model name, alias, prefix, or ``None``.  Empty/whitespace
                 input is treated identically to ``None`` — the default model
                 settings are returned.

        Returns:
            A frozen ``ModelSettings`` instance.  Never raises.
        """
        normalized = (raw or "").strip()

        # Empty / None → return settings for the default model.
        if not normalized:
            return self._settings_for(self._registry.default_model)

        if self._registry.is_known(normalized):
            resolved = self._registry.resolve(normalized)
            return self._settings_for(resolved)

        # Unknown model: return sane generic default with the raw name preserved.
        return ModelSettings(name=normalized)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _settings_for(self, model_id: str) -> ModelSettings:
        """Build ``ModelSettings`` for an already-resolved canonical model_id."""
        extras = self._registry.get_model_extras(model_id)

        weak_raw: str | None = extras.get("weak_model")
        editor_raw: str | None = extras.get("editor_model")

        # Resolve weak/editor names through the registry so aliases work there too.
        weak_name = self._registry.resolve(weak_raw) if weak_raw else None
        editor_name = self._registry.resolve(editor_raw) if editor_raw else None

        return ModelSettings(
            name=model_id,
            edit_format=extras.get("edit_format"),
            weak_model_name=weak_name,
            editor_model_name=editor_name,
            use_repo_map=extras.get("use_repo_map", True),
        )


def select_aux_model(settings: ModelSettings, main_model: str) -> str:
    """Select the model to use for auxiliary LLM tasks (REQ-RCA-010).

    Auxiliary tasks include summarization, commit-message generation, and similar
    low-stakes calls where a cheaper/faster model is preferable.

    This is a pure function; it carries NO side effects.  Callers are responsible
    for gating it behind ``CodingProfileConfig.enable_model_tiering`` — when that
    flag is False the caller must use ``main_model`` directly (byte-identical path).

    Args:
        settings: Resolved ``ModelSettings`` for the active main model.
        main_model: The main model identifier used for primary reasoning tasks.

    Returns:
        ``settings.weak_model_name`` when declared, otherwise ``main_model``.
    """
    return (
        settings.weak_model_name if settings.weak_model_name is not None else main_model
    )


# codex R1 [3 MAJOR]: markers used to duck-type-detect an auth/network-class
# provider failure without importing anything thin/runtime-specific here
# (this module has no business knowing about ThinLlmError — it stays
# reusable). Matched against the exception's own class name, message, and
# (if present) a ThinLlmError-shaped `.error.details["exception_type"]`.
_ABORT_WORTHY_MARKERS = (
    "auth",
    "unauthorized",
    "forbidden",
    "permission",
    "connection",
    "timeout",
    "ratelimit",
    "rate limit",
    "network",
)


def _looks_like_abort_worthy_failure(exc: Exception) -> bool:
    """True when ``exc`` looks like an auth/network-class provider failure
    (Stage 6 compaction safe-fail: these must ABORT, not fall back)."""
    error = getattr(exc, "error", None)
    details = getattr(error, "details", None) if error is not None else None
    exception_type = (
        str(details.get("exception_type", "")) if isinstance(details, dict) else ""
    )
    haystack = f"{type(exc).__name__} {exception_type} {exc}".lower()
    return any(marker in haystack for marker in _ABORT_WORTHY_MARKERS)


def build_aux_llm_call(
    raw_llm_call: Callable[..., Awaitable[Any]],
    base_config: Any,
    weak_model_name: str,
) -> Callable[[str, str], Awaitable[str]]:
    """Build an async llm_call adapter that routes aux tasks to the weak model.

    The returned callable matches the ``ConversationCompactionFilter`` protocol:
    ``(prompt: str, dialog_text: str) -> str``.  Internally it clones
    ``base_config`` with ``model=weak_model_name`` (via ``dataclasses.replace``),
    calls ``raw_llm_call`` with that override config, then coerces the result to
    ``str`` (handles plain ``str``, objects with a ``.text`` attribute such as
    ``LlmCallResult``, and ``AsyncIterator[str]`` for streaming paths).

    An auth/network-class failure from ``raw_llm_call`` (duck-typed, e.g. a
    ``ThinLlmError``-shaped provider crash or a stdlib ``TimeoutError``/
    ``ConnectionError``/``OSError``) is re-raised as
    ``swarmline.compaction.SummarizerAbortError`` so
    ``ConversationCompactionFilter`` maps it to its safe-fail ABORT path
    (codex R1 [3 MAJOR]) instead of the local-fallback path meant for
    ordinary/recoverable summarizer failures.

    Args:
        raw_llm_call: The runtime's internal LLM callable with signature
                      ``(messages, system_prompt, *, config=None) -> str | ...``.
                      Typically ``ThinRuntime._llm_call``.
        base_config: The ``RuntimeConfig`` used as the base for cloning.  Must
                     be a dataclass so ``dataclasses.replace`` applies.
        weak_model_name: Canonical model name to use for the aux call.

    Returns:
        An async ``(prompt, dialog_text) -> str`` callable.
    """
    weak_config: Any = dataclasses.replace(base_config, model=weak_model_name)

    async def _aux_call(prompt: str, dialog_text: str) -> str:
        try:
            result: Any = await raw_llm_call(
                [{"role": "user", "content": dialog_text}],
                prompt,
                config=weak_config,
            )
        except Exception as exc:
            if isinstance(
                exc, (TimeoutError, ConnectionError, OSError)
            ) or _looks_like_abort_worthy_failure(exc):
                from swarmline.compaction import SummarizerAbortError

                raise SummarizerAbortError(str(exc)) from exc
            raise
        if isinstance(result, str):
            return result
        # LlmCallResult or any object with a .text str attribute
        text_attr = getattr(result, "text", None)
        if isinstance(text_attr, str):
            return text_attr
        # AsyncIterator[str] — consume and join
        chunks: list[str] = []
        async for chunk in result:  # type: ignore[union-attr]
            chunks.append(chunk)
        return "".join(chunks)

    return _aux_call
