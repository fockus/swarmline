"""``WorkingMemory`` — resource-scoped structured profile over a ``FactStore``
(Stage C2.1, Mastra parity).

A persistent, structured user profile (name, goals, preferences, ...) that
survives across threads/topics for one resource (``resource_id``, mirroring
the ``UserStore``'s ``user_id`` key), reserved under ``key_prefix`` (default
``"wm"``) in the existing ``FactStore`` -- it composes with whatever business
facts are already stored there without ever reading or writing them.

Thread-independence: ``FactStore.get_facts`` merges global + topic-scoped
facts, so this reads/writes with ``topic_id=None`` (global/resource scope
only) -- working memory is NOT thread-scoped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Deferred: `swarmline.protocols.memory` itself imports from
    # `swarmline.memory.types`, and this module is eagerly re-exported from
    # `swarmline.memory.__init__` -- a runtime import here would be a real
    # circular import (protocols.memory -> memory (__init__) -> working ->
    # protocols.memory). `FactStore` is only ever used as a type hint (this
    # file has `from __future__ import annotations`), so TYPE_CHECKING-only
    # is both correct and sufficient.
    from swarmline.protocols.memory import FactStore


class WorkingMemory:
    """Resource-scoped structured profile over a ``FactStore``.

    ISP: 4 methods (``aget``/``aset``/``aupdate``/``arender``).
    """

    def __init__(
        self,
        fact_store: FactStore,
        *,
        resource_id: str,
        template: Mapping[str, str] | None = None,
        key_prefix: str = "wm",
    ) -> None:
        self._fact_store = fact_store
        self._resource_id = resource_id
        self._template: dict[str, str] = dict(template) if template else {}
        self._prefix = f"{key_prefix}."

    def _field_key(self, field: str) -> str:
        """Reserved-prefix key for ``field``; rejects a delimiter-containing
        field name so prefix-stripping on read is always unambiguous."""
        if "." in field:
            raise ValueError(
                f"working memory field name {field!r} must not contain '.' "
                "(reserved as the key_prefix delimiter)"
            )
        return f"{self._prefix}{field}"

    async def aget(self) -> dict[str, Any]:
        """Return ``{field: value}`` for facts stored under ``key_prefix``
        -- never reads/returns non-prefixed (business) facts."""
        facts = await self._fact_store.get_facts(self._resource_id, topic_id=None)
        return {
            key[len(self._prefix) :]: value
            for key, value in facts.items()
            if key.startswith(self._prefix)
        }

    async def aset(self, field: str, value: Any) -> None:
        """Set one field under ``key_prefix`` (resource/global scope)."""
        key = self._field_key(field)
        await self._fact_store.upsert_fact(
            self._resource_id, key, value, topic_id=None, source="working_memory"
        )

    async def aupdate(self, values: Mapping[str, Any]) -> None:
        """Bulk ``aset`` -- set every field in ``values``.

        All-or-nothing VALIDATION: every field name is checked (rejects a
        '.'-containing name) BEFORE any write, so an invalid later field
        cannot leave an earlier field partially persisted. Persistence
        itself stays sequential/non-transactional (no store-level
        transaction spans multiple `upsert_fact` calls).
        """
        keys = {field: self._field_key(field) for field in values}
        for field, value in values.items():
            await self._fact_store.upsert_fact(
                self._resource_id,
                keys[field],
                value,
                topic_id=None,
                source="working_memory",
            )

    async def arender(self) -> str:
        """Render as a stable ``<working_memory>...</working_memory>`` block.

        Template fields render first, IN TEMPLATE ORDER (blank if unset, so
        the structure is always visible to the model); any additionally-set
        field not in the template renders after, SORTED BY NAME (a store's
        natural return order is not guaranteed stable across providers/DBs,
        so sorting keeps rendering deterministic) -- empty-safe, never
        raises.
        """
        current = await self.aget()
        lines = [f"{field}: {current.get(field, '')}" for field in self._template]
        lines.extend(
            f"{field}: {value}"
            for field, value in sorted(current.items())
            if field not in self._template
        )
        if not lines:
            return "<working_memory></working_memory>"
        body = "\n".join(lines)
        return f"<working_memory>\n{body}\n</working_memory>"
