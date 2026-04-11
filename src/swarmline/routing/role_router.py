"""RoleRouter - route the user to the right role (architecture section 7).

MVP strategy:
1. Explicit command (/role credit) - always takes priority
2. Keyword/regex heuristic over the user text
3. Fallback to default_role
"""

from __future__ import annotations


class KeywordRoleRouter:
    """Keyword-based role router.

    Accepts a mapping role_id -> list of keywords.
    Checks the user text for keyword matches (case-insensitive).
    """

    def __init__(
        self,
        default_role: str = "default",
        keyword_map: dict[str, list[str]] | None = None,
    ) -> None:
        self._default = default_role
        # Normalize: convert all keywords to lowercase
        self._map: list[tuple[str, list[str]]] = []
        if keyword_map:
            for role_id, keywords in keyword_map.items():
                self._map.append((role_id, [kw.lower() for kw in keywords]))

    def resolve(
        self,
        user_text: str,
        explicit_role: str | None = None,
    ) -> str:
        """Resolve a role from the user text.

        Args:
            user_text: user message text
            explicit_role: explicitly specified role (from the /role command) - priority

        Returns:
            role_id to use for the current turn
        """
        # Step 1: explicit command wins over everything
        if explicit_role:
            return explicit_role

        # Step 2: keyword match
        text_lower = user_text.lower()
        if not text_lower.strip():
            return self._default

        for role_id, keywords in self._map:
            for kw in keywords:
                if kw in text_lower:
                    return role_id

        # Step 3: fallback
        return self._default
