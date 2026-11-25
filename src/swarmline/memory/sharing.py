"""Memory sharing — owner-scoped access grants between generic str ids.

MemorySharingPort: ISP-compliant protocol (4 methods).
InMemorySharingStore: reference implementation, zero external dependencies.

Security invariant: grants are keyed by (owner_id, namespace) so two owners
who happen to use the same namespace string cannot observe or revoke each
other's grants.  ``owner_id`` is a required first parameter on every method
and a required field on ``ShareGrant``.

All ids are plain ``str``. No product (tenant/workspace/FastAPI/SQLAlchemy) coupling.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# `list` is used as a method name in MemorySharingPort (per spec).
# Use _list alias so the return-type annotations resolve to the builtin,
# not to the method, which confuses strict type checkers like ty.
_list = builtins.list


@dataclass(frozen=True)
class ShareGrant:
    """Immutable record of a single memory-sharing grant.

    Args:
        owner_id:   Required str identifying who owns the namespace.
                    Together with ``namespace`` this forms the isolation key.
        namespace:  The memory namespace being shared (generic string key).
        target_id:  The agent/user/entity id being granted access.
        permission: Access level — ``"read"`` (default) or ``"readwrite"``.
    """

    owner_id: str
    namespace: str
    target_id: str
    permission: str = "read"


@runtime_checkable
class MemorySharingPort(Protocol):
    """Port for owner-scoped memory-access grants (ISP — 4 methods).

    Every method takes ``owner_id`` as its FIRST parameter so grants are
    scoped to ``(owner_id, namespace)`` and cannot leak across owners who
    share the same namespace string.

    All ids are plain ``str``.  Method ``list`` is intentionally named to
    follow the task specification.
    """

    async def share(
        self,
        owner_id: str,
        namespace: str,
        target_id: str,
        permission: str = "read",
    ) -> ShareGrant:
        """Grant *target_id* access to *owner_id*'s *namespace*.

        Returns the created/updated :class:`ShareGrant`.
        """
        ...

    async def unshare(self, owner_id: str, namespace: str, target_id: str) -> None:
        """Revoke *target_id*'s access to *owner_id*'s *namespace*.

        No-op if the grant does not exist.  Does NOT affect grants belonging
        to other owners even if they use the same namespace string.
        """
        ...

    async def list(  # noqa: A003
        self,
        owner_id: str,
        namespace: str,
    ) -> _list[ShareGrant]:
        """Return all active :class:`ShareGrant` objects for *owner_id*'s *namespace*."""
        ...

    async def check(self, owner_id: str, namespace: str, accessor_id: str) -> bool:
        """Return ``True`` if *accessor_id* has an active grant on *owner_id*'s *namespace*."""
        ...


class InMemorySharingStore:
    """Reference in-process implementation of :class:`MemorySharingPort`.

    Grants are keyed by ``(owner_id, namespace)`` so distinct owners who use
    the same namespace string are completely isolated from each other.

    Thread-safety and persistence are out of scope — use a database-backed
    implementation in production.
    """

    def __init__(self) -> None:
        # (owner_id, namespace) -> {target_id: ShareGrant}
        self._grants: dict[tuple[str, str], dict[str, ShareGrant]] = {}

    def _key(self, owner_id: str, namespace: str) -> tuple[str, str]:
        return (owner_id, namespace)

    async def share(
        self,
        owner_id: str,
        namespace: str,
        target_id: str,
        permission: str = "read",
    ) -> ShareGrant:
        """Grant *target_id* access to *owner_id*'s *namespace*."""
        grant = ShareGrant(
            owner_id=owner_id,
            namespace=namespace,
            target_id=target_id,
            permission=permission,
        )
        self._grants.setdefault(self._key(owner_id, namespace), {})[target_id] = grant
        return grant

    async def unshare(self, owner_id: str, namespace: str, target_id: str) -> None:
        """Revoke *target_id*'s grant on *owner_id*'s *namespace* (no-op if absent)."""
        bucket = self._grants.get(self._key(owner_id, namespace))
        if bucket is not None:
            bucket.pop(target_id, None)

    async def list(  # noqa: A003
        self,
        owner_id: str,
        namespace: str,
    ) -> _list[ShareGrant]:
        """Return all active grants for *owner_id*'s *namespace*."""
        bucket = self._grants.get(self._key(owner_id, namespace), {})
        return list(bucket.values())

    async def check(self, owner_id: str, namespace: str, accessor_id: str) -> bool:
        """Return ``True`` if *accessor_id* holds a grant on *owner_id*'s *namespace*."""
        bucket = self._grants.get(self._key(owner_id, namespace), {})
        return accessor_id in bucket
