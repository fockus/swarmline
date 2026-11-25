"""Model profiles: context window, output limit and prompt-cache mode per model.

Profiles live in the ``profiles:`` section of ``models.yaml``, keyed by the model id
WITHOUT a routing prefix (``moonshotai/kimi-k2.5``, not ``openrouter:moonshotai/...``).
They are deliberately separate from ``providers:``: adding an OpenRouter-style id to
``providers`` would change how ``get_provider``/``resolve_provider`` route that string.

``resolve_model_profile`` never falls back to the default model: an unknown model gets
``None`` so the caller can apply an explicit conservative default
(``UNKNOWN_MODEL_PROFILE``) and say so, instead of silently sizing a 32k model's context
as if it were Sonnet's 200k.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, get_args

if TYPE_CHECKING:
    from swarmline.runtime.model_registry import ModelRegistry

PromptCacheMode = Literal["explicit", "automatic", "none"]
PROMPT_CACHE_MODES: frozenset[str] = frozenset(get_args(PromptCacheMode))


def _is_int(value: Any) -> bool:
    # bool is an int subclass; `context_window: true` in YAML is a typo, not a window.
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Physical limits of one model.

    Attributes:
        context_window: Total tokens the model accepts (prompt + output).
        max_output_tokens: Largest completion the model can produce in one call.
        prompt_cache: ``explicit`` (cache breakpoints must be sent, Anthropic),
            ``automatic`` (provider caches prefixes by itself) or ``none``.
        vision: The model accepts image parts in a user message. Defaults to
            ``False``: an image sent to a text-only model is an API error, so a
            model is "seeing" only when its profile says so.
    """

    context_window: int
    max_output_tokens: int
    prompt_cache: PromptCacheMode
    vision: bool = False

    def __post_init__(self) -> None:
        if not _is_int(self.context_window) or self.context_window <= 0:
            raise ValueError(
                f"context_window must be a positive int, got {self.context_window!r}"
            )
        if (
            not _is_int(self.max_output_tokens)
            or not 0 < self.max_output_tokens < self.context_window
        ):
            raise ValueError(
                f"max_output_tokens must be an int in (0, context_window={self.context_window}), got {self.max_output_tokens!r}"
            )
        if self.prompt_cache not in PROMPT_CACHE_MODES:
            raise ValueError(
                f"prompt_cache must be one of {sorted(PROMPT_CACHE_MODES)}, got {self.prompt_cache!r}"
            )
        if not isinstance(self.vision, bool):
            raise ValueError(f"vision must be a bool, got {self.vision!r}")


# Conservative profile for a model the registry does not know (AGR-069): small enough
# that compaction starts early rather than letting a small-window model overflow.
UNKNOWN_MODEL_PROFILE = ModelProfile(
    context_window=32_000, max_output_tokens=4_096, prompt_cache="none"
)


def normalize_model_id(raw: str) -> str:
    """Canonical lookup key: the same strip+lower normalization ``resolve`` applies."""
    return raw.strip().lower()


# OpenRouter routing variants (``vendor/model:free``): same model, same limits.
OPENROUTER_VARIANT_SUFFIXES: frozenset[str] = frozenset(
    {"free", "batch", "nitro", "floor", "online", "thinking"}
)


def strip_variant_suffix(model_id: str) -> str:
    """Drop a known OpenRouter variant suffix; an unknown suffix is kept as is."""
    base, sep, suffix = model_id.rpartition(":")
    return base if sep and base and suffix in OPENROUTER_VARIANT_SUFFIXES else model_id


def parse_model_profile(model_id: str, raw: Any) -> ModelProfile:
    """Build a profile from one YAML entry, naming the model in any validation error."""
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"profile for model {model_id!r} must be a mapping, got {type(raw).__name__}"
        )
    try:
        return ModelProfile(
            context_window=raw.get("context_window"),
            max_output_tokens=raw.get("max_output_tokens"),
            prompt_cache=raw.get("prompt_cache"),
            vision=raw.get("vision", False),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid profile for model {model_id!r}: {exc}") from exc


def resolve_model_profile(
    raw: str | None, registry: ModelRegistry | None = None
) -> ModelProfile | None:
    """Return the profile of ``raw`` or ``None`` when the model is not recognized.

    Lookup order: strip a known provider prefix (``openrouter:``, ``anthropic:``, ...)
    and a known OpenRouter variant suffix (``:free``, ``:nitro``, ...), then the exact
    profile id, then an explicitly declared registry alias. Deliberately NOT the
    registry's greedy ``startswith`` matching (``gpt-4`` must not become ``gpt-4o``)
    and NO fallback to ``default_model``: a wrong window is worse than "unknown".
    """
    # Local imports: model_registry imports this module at load time, and
    # provider_resolver imports model_registry -- a top-level import would cycle.
    from swarmline.runtime.model_registry import get_registry
    from swarmline.runtime.provider_resolver import parse_provider_prefix

    if raw is None or not raw.strip():
        return None
    reg = registry if registry is not None else get_registry()
    _, model_part = parse_provider_prefix(raw.strip())
    name = strip_variant_suffix(normalize_model_id(model_part))
    exact = reg.get_profile(name)
    if exact is not None:
        return exact
    alias_target = reg.list_aliases().get(name)
    return reg.get_profile(alias_target) if alias_target is not None else None
