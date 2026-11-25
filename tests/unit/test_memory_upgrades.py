"""TDD tests for OSS memory upgrades (T8):
- MemoryCommitPort + InMemoryCommitStore (versioning)
- MemorySharingPort + InMemorySharingStore (sharing)
- AgentSoulConfig.to_prompt_block()
- UserKnowledge + KnowledgeCategory
- ConversationDistiller (compression + recent-tail preservation)

All assertions target business facts. Arrange-Act-Assert. No mocks of internal code.
"""

from __future__ import annotations

import pytest

from swarmline.memory import (
    AgentSoulConfig,
    ConversationDistiller,
    DistillationResult,
    InMemoryCommitStore,
    InMemorySharingStore,
    KnowledgeCategory,
    MemoryCommitPort,
    MemoryMessage,
    MemorySharingPort,
    MemorySnapshot,
    ShareGrant,
    UserKnowledge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content: str) -> MemoryMessage:
    return MemoryMessage(role=role, content=content)


# ===========================================================================
# MemoryCommitPort + InMemoryCommitStore — versioning
# ===========================================================================


class TestMemoryCommitProtocolConformance:
    def test_inmemory_commit_store_implements_protocol(self) -> None:
        store = InMemoryCommitStore()
        assert isinstance(store, MemoryCommitPort)


class TestMemoryCommitRoundTrip:
    @pytest.mark.asyncio
    async def test_commit_creates_version_1_on_fresh_namespace(self) -> None:
        """First commit on a namespace returns version 1."""
        store = InMemoryCommitStore()
        snap = await store.commit("ns:agent1", ["fact-a", "fact-b"])
        assert snap.version == 1
        assert set(snap.entries) == {"fact-a", "fact-b"}
        assert snap.namespace == "ns:agent1"

    @pytest.mark.asyncio
    async def test_commit_increments_version(self) -> None:
        """Successive commits produce monotonically increasing versions."""
        store = InMemoryCommitStore()
        snap1 = await store.commit("ns:x", ["v1"])
        snap2 = await store.commit("ns:x", ["v2"])
        snap3 = await store.commit("ns:x", ["v3"])
        assert snap1.version == 1
        assert snap2.version == 2
        assert snap3.version == 3

    @pytest.mark.asyncio
    async def test_history_grows_with_each_commit(self) -> None:
        """history() returns newest-first and length equals number of commits."""
        store = InMemoryCommitStore()
        await store.commit("ns:x", ["a"])
        await store.commit("ns:x", ["b"])
        await store.commit("ns:x", ["c"])
        snaps = await store.history("ns:x")
        assert len(snaps) == 3
        # newest first
        assert snaps[0].version == 3
        assert snaps[1].version == 2
        assert snaps[2].version == 1

    @pytest.mark.asyncio
    async def test_history_limit_is_respected(self) -> None:
        """history(limit=2) returns only the 2 most recent snapshots."""
        store = InMemoryCommitStore()
        for i in range(5):
            await store.commit("ns:x", [f"entry-{i}"])
        snaps = await store.history("ns:x", limit=2)
        assert len(snaps) == 2
        assert snaps[0].version == 5
        assert snaps[1].version == 4

    @pytest.mark.asyncio
    async def test_diff_returns_entries_new_in_v2(self) -> None:
        """diff(v1, v2) returns entries present in v2 but not in v1."""
        store = InMemoryCommitStore()
        await store.commit("ns:x", ["common", "old-only"])
        await store.commit("ns:x", ["common", "new-entry"])
        added = await store.diff("ns:x", 1, 2)
        assert "new-entry" in added
        assert "common" not in added
        assert "old-only" not in added

    @pytest.mark.asyncio
    async def test_restore_reverts_namespace_state(self) -> None:
        """restore(version=1) creates a new snapshot whose entries match v1."""
        store = InMemoryCommitStore()
        snap1 = await store.commit("ns:x", ["original-entry"])
        await store.commit("ns:x", ["new-entry"])
        restored = await store.restore("ns:x", 1)
        assert set(restored.entries) == set(snap1.entries)

    @pytest.mark.asyncio
    async def test_restore_appends_new_snapshot(self) -> None:
        """restore() appends a new snapshot so history continues growing."""
        store = InMemoryCommitStore()
        await store.commit("ns:x", ["v1"])
        await store.commit("ns:x", ["v2"])
        await store.restore("ns:x", 1)
        snaps = await store.history("ns:x")
        # Two commits + one restore = three entries in history
        assert len(snaps) == 3

    @pytest.mark.asyncio
    async def test_restore_unknown_version_raises(self) -> None:
        """restore() raises ValueError for a non-existent version."""
        store = InMemoryCommitStore()
        with pytest.raises((ValueError, KeyError, LookupError)):
            await store.restore("ns:x", 99)

    @pytest.mark.asyncio
    async def test_namespaces_are_isolated(self) -> None:
        """Commits to different namespaces do not interfere."""
        store = InMemoryCommitStore()
        await store.commit("ns:a", ["entry-a"])
        await store.commit("ns:b", ["entry-b"])
        snaps_a = await store.history("ns:a")
        snaps_b = await store.history("ns:b")
        assert len(snaps_a) == 1
        assert len(snaps_b) == 1
        assert snaps_a[0].namespace == "ns:a"
        assert snaps_b[0].namespace == "ns:b"


class TestMemorySnapshotType:
    def test_snapshot_is_frozen(self) -> None:
        snap = MemorySnapshot(
            namespace="ns",
            version=1,
            entries=("e",),
        )
        with pytest.raises(AttributeError):
            snap.version = 2  # type: ignore[misc]


# ===========================================================================
# MemorySharingPort + InMemorySharingStore — access grants
# ===========================================================================


class TestMemorySharingProtocolConformance:
    def test_inmemory_sharing_store_implements_protocol(self) -> None:
        store = InMemorySharingStore()
        assert isinstance(store, MemorySharingPort)


class TestMemorySharingGrants:
    @pytest.mark.asyncio
    async def test_check_returns_false_before_any_share(self) -> None:
        """Unknown accessor has no access by default."""
        store = InMemorySharingStore()
        has_access = await store.check("owner-1", "ns:private", "stranger-agent")
        assert has_access is False

    @pytest.mark.asyncio
    async def test_share_grants_access_check_returns_true(self) -> None:
        """check() returns True after share()."""
        store = InMemorySharingStore()
        await store.share("owner-1", "ns:memory", "agent-b")
        has_access = await store.check("owner-1", "ns:memory", "agent-b")
        assert has_access is True

    @pytest.mark.asyncio
    async def test_unshare_revokes_access(self) -> None:
        """check() returns False after unshare()."""
        store = InMemorySharingStore()
        await store.share("owner-1", "ns:memory", "agent-b")
        await store.unshare("owner-1", "ns:memory", "agent-b")
        has_access = await store.check("owner-1", "ns:memory", "agent-b")
        assert has_access is False

    @pytest.mark.asyncio
    async def test_list_returns_active_grants(self) -> None:
        """list() returns all active ShareGrant objects for namespace."""
        store = InMemorySharingStore()
        await store.share("owner-1", "ns:memory", "agent-b")
        await store.share("owner-1", "ns:memory", "agent-c", "readwrite")
        grants = await store.list("owner-1", "ns:memory")
        target_ids = {g.target_id for g in grants}
        assert "agent-b" in target_ids
        assert "agent-c" in target_ids

    @pytest.mark.asyncio
    async def test_list_excludes_unshared_targets(self) -> None:
        """Unshared targets do not appear in list()."""
        store = InMemorySharingStore()
        await store.share("owner-1", "ns:memory", "agent-b")
        await store.share("owner-1", "ns:memory", "agent-c")
        await store.unshare("owner-1", "ns:memory", "agent-b")
        grants = await store.list("owner-1", "ns:memory")
        target_ids = {g.target_id for g in grants}
        assert "agent-b" not in target_ids
        assert "agent-c" in target_ids

    @pytest.mark.asyncio
    async def test_share_returns_grant_with_correct_permission(self) -> None:
        """share() returns a ShareGrant whose permission matches the argument."""
        store = InMemorySharingStore()
        grant = await store.share("owner-1", "ns:data", "reader-agent", "read")
        assert isinstance(grant, ShareGrant)
        assert grant.namespace == "ns:data"
        assert grant.target_id == "reader-agent"
        assert grant.permission == "read"

    @pytest.mark.asyncio
    async def test_sharing_namespaces_are_isolated(self) -> None:
        """Grants on different namespaces do not bleed across."""
        store = InMemorySharingStore()
        await store.share(owner_id="owner-1", namespace="ns:alpha", target_id="agent-x")
        has_access_alpha = await store.check(
            owner_id="owner-1", namespace="ns:alpha", accessor_id="agent-x"
        )
        has_access_beta = await store.check(
            owner_id="owner-1", namespace="ns:beta", accessor_id="agent-x"
        )
        assert has_access_alpha is True
        assert has_access_beta is False


# ===========================================================================
# Cross-owner isolation (OSS-T8 security fix)
# ===========================================================================


class TestMemorySharingOwnerIsolation:
    """Grants MUST be scoped to (owner_id, namespace) — not namespace alone.

    A grant from owner A must NOT be visible under owner C's same-named namespace.
    These tests are RED under the old ownerless keying (TypeError or wrong result)
    and GREEN only after owner_id is wired through the whole sharing surface.
    """

    @pytest.mark.asyncio
    async def test_sharing_isolated_across_owners(self) -> None:
        """Owner A grants bob access; owner C's same-named namespace is NOT granted.

        With the old namespace-only keying, check(C, "notes", "bob") returns True
        (the grant leaks). With owner-scoped keying it returns False.
        """
        store = InMemorySharingStore()
        await store.share(owner_id="owner-A", namespace="notes", target_id="bob")
        # Owner A's namespace: bob has access
        has_access_a = await store.check(
            owner_id="owner-A", namespace="notes", accessor_id="bob"
        )
        # Owner C's same-named namespace: bob must NOT have access
        has_access_c = await store.check(
            owner_id="owner-C", namespace="notes", accessor_id="bob"
        )
        assert has_access_a is True
        assert has_access_c is False  # ← this FAILS under old ownerless keying

    @pytest.mark.asyncio
    async def test_unshare_scoped_to_owner(self) -> None:
        """Owner A's unshare does NOT revoke owner C's grant for the same namespace+target."""
        store = InMemorySharingStore()
        await store.share(owner_id="owner-A", namespace="notes", target_id="bob")
        await store.share(owner_id="owner-C", namespace="notes", target_id="bob")
        # A revokes their own grant
        await store.unshare(owner_id="owner-A", namespace="notes", target_id="bob")
        # A's grant gone
        a_access = await store.check(
            owner_id="owner-A", namespace="notes", accessor_id="bob"
        )
        # C's grant untouched
        c_access = await store.check(
            owner_id="owner-C", namespace="notes", accessor_id="bob"
        )
        assert a_access is False
        assert c_access is True  # ← would be False under old unscoped unshare

    @pytest.mark.asyncio
    async def test_list_scoped_to_owner(self) -> None:
        """list(owner) returns only grants belonging to that owner."""
        store = InMemorySharingStore()
        await store.share(owner_id="owner-A", namespace="notes", target_id="bob")
        await store.share(owner_id="owner-B", namespace="notes", target_id="carol")
        grants_a = await store.list(owner_id="owner-A", namespace="notes")
        grants_b = await store.list(owner_id="owner-B", namespace="notes")
        target_ids_a = {g.target_id for g in grants_a}
        target_ids_b = {g.target_id for g in grants_b}
        # Each owner sees only their own grants
        assert target_ids_a == {"bob"}
        assert target_ids_b == {"carol"}

    @pytest.mark.asyncio
    async def test_share_records_owner_id_in_grant(self) -> None:
        """The returned ShareGrant carries the correct owner_id."""
        store = InMemorySharingStore()
        grant = await store.share(
            owner_id="owner-X", namespace="files", target_id="agent-Y"
        )
        assert grant.owner_id == "owner-X"
        assert grant.namespace == "files"
        assert grant.target_id == "agent-Y"


# ===========================================================================
# AgentSoulConfig — prompt block rendering
# ===========================================================================


class TestAgentSoulConfig:
    def test_soul_prompt_block_contains_personality(self) -> None:
        soul = AgentSoulConfig(personality="curious researcher")
        block = soul.to_prompt_block()
        assert "curious researcher" in block

    def test_soul_prompt_block_contains_tone(self) -> None:
        soul = AgentSoulConfig(personality="helper", tone="friendly")
        block = soul.to_prompt_block()
        assert "friendly" in block

    def test_soul_prompt_block_contains_behavior_rules(self) -> None:
        soul = AgentSoulConfig(
            personality="assistant",
            behavior_rules=("never lie", "be concise"),
        )
        block = soul.to_prompt_block()
        assert "never lie" in block
        assert "be concise" in block

    def test_soul_prompt_block_without_rules_omits_rules_section(self) -> None:
        soul = AgentSoulConfig(personality="plain", behavior_rules=())
        block = soul.to_prompt_block()
        # No rules heading clutter when empty
        assert "never" not in block.lower() or "rules" not in block.lower()

    def test_soul_prompt_block_contains_persona_description(self) -> None:
        soul = AgentSoulConfig(
            personality="guide", persona_description="A wise old teacher."
        )
        block = soul.to_prompt_block()
        assert "A wise old teacher." in block

    def test_soul_config_is_frozen(self) -> None:
        soul = AgentSoulConfig(personality="x")
        with pytest.raises(AttributeError):
            soul.personality = "y"  # type: ignore[misc]

    def test_soul_empty_personality_raises(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            AgentSoulConfig(personality="  ")


# ===========================================================================
# UserKnowledge — typed knowledge entries
# ===========================================================================


class TestUserKnowledge:
    def test_user_knowledge_basic_construction(self) -> None:
        uk = UserKnowledge(
            agent_id="agent-1",
            user_id="user-42",
            category=KnowledgeCategory.PREFERENCE,
            key="theme",
            value="dark",
        )
        assert uk.agent_id == "agent-1"
        assert uk.user_id == "user-42"
        assert uk.confidence == 1.0  # default

    def test_user_knowledge_confidence_stored(self) -> None:
        uk = UserKnowledge(
            agent_id="a",
            user_id="u",
            category=KnowledgeCategory.FACT,
            key="language",
            value="Python",
            confidence=0.85,
        )
        assert uk.confidence == 0.85

    def test_user_knowledge_invalid_confidence_raises(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            UserKnowledge(
                agent_id="a",
                user_id="u",
                category=KnowledgeCategory.FACT,
                key="k",
                value="v",
                confidence=1.5,
            )

    def test_user_knowledge_empty_key_raises(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            UserKnowledge(
                agent_id="a",
                user_id="u",
                category=KnowledgeCategory.FACT,
                key="  ",
                value="v",
            )

    def test_user_knowledge_is_frozen(self) -> None:
        uk = UserKnowledge(
            agent_id="a",
            user_id="u",
            category=KnowledgeCategory.CONTEXT,
            key="k",
            value="v",
        )
        with pytest.raises(AttributeError):
            uk.value = "changed"  # type: ignore[misc]

    def test_knowledge_categories_values(self) -> None:
        """All four canonical categories exist."""
        assert KnowledgeCategory.PREFERENCE
        assert KnowledgeCategory.PATTERN
        assert KnowledgeCategory.CONTEXT
        assert KnowledgeCategory.FACT


# ===========================================================================
# ConversationDistiller — compression + recent tail preservation
# ===========================================================================


class TestConversationDistillerShortConvo:
    def test_short_convo_below_min_returned_unchanged(self) -> None:
        """Conversations shorter than min_messages are returned verbatim."""
        distiller = ConversationDistiller(min_messages=10, keep_last=5)
        msgs = [_msg("user", f"msg-{i}") for i in range(5)]
        result = distiller.distill(msgs)
        assert isinstance(result, DistillationResult)
        assert list(result.recent_messages) == msgs
        assert result.summary == ""
        assert result.messages_summarized == 0

    def test_empty_convo_returned_unchanged(self) -> None:
        distiller = ConversationDistiller(min_messages=5)
        result = distiller.distill([])
        assert list(result.recent_messages) == []
        assert result.summary == ""
        assert result.messages_summarized == 0


class TestConversationDistillerCompression:
    def test_long_convo_recent_tail_preserved_verbatim(self) -> None:
        """The last keep_last messages are returned unchanged."""
        keep = 3
        distiller = ConversationDistiller(min_messages=5, keep_last=keep)
        msgs = [_msg("user", f"msg-{i}") for i in range(10)]
        result = distiller.distill(msgs)
        assert list(result.recent_messages) == msgs[-keep:]

    def test_long_convo_all_recent_kept(self) -> None:
        """recent_messages count equals keep_last when total >= min_messages."""
        keep = 4
        distiller = ConversationDistiller(min_messages=6, keep_last=keep)
        msgs = [_msg("user", f"m{i}") for i in range(10)]
        result = distiller.distill(msgs)
        assert len(result.recent_messages) == keep

    def test_long_convo_summary_non_empty(self) -> None:
        """Summary is non-empty when older messages are compressed."""
        distiller = ConversationDistiller(min_messages=4, keep_last=2)
        msgs = [_msg("user", f"message {i}") for i in range(8)]
        result = distiller.distill(msgs)
        assert result.summary != ""

    def test_long_convo_messages_summarized_count(self) -> None:
        """messages_summarized = total - keep_last."""
        total = 10
        keep = 3
        distiller = ConversationDistiller(min_messages=5, keep_last=keep)
        msgs = [_msg("user", f"m{i}") for i in range(total)]
        result = distiller.distill(msgs)
        assert result.messages_summarized == total - keep
        assert result.total_input == total

    def test_custom_summarizer_is_called_with_older_messages(self) -> None:
        """Custom summarizer callable receives the messages to compress."""
        captured: list[list[MemoryMessage]] = []

        def custom_summarizer(messages: list[MemoryMessage]) -> str:
            captured.append(list(messages))
            return "CUSTOM SUMMARY"

        distiller = ConversationDistiller(
            min_messages=4, keep_last=2, summarizer=custom_summarizer
        )
        msgs = [_msg("user", f"m{i}") for i in range(6)]
        result = distiller.distill(msgs)
        assert result.summary == "CUSTOM SUMMARY"
        assert len(captured) == 1
        # Summarizer received all except the last 2
        assert captured[0] == msgs[:-2]

    def test_distillation_result_is_frozen(self) -> None:
        """DistillationResult is immutable."""
        distiller = ConversationDistiller(min_messages=4, keep_last=2)
        msgs = [_msg("user", f"m{i}") for i in range(6)]
        result = distiller.distill(msgs)
        with pytest.raises(AttributeError):
            result.summary = "mutated"  # type: ignore[misc]

    def test_recent_messages_oldest_first_in_result(self) -> None:
        """recent_messages preserves original chronological order."""
        distiller = ConversationDistiller(min_messages=4, keep_last=3)
        msgs = [_msg("user", f"m{i}") for i in range(7)]
        result = distiller.distill(msgs)
        # Messages are oldest-first inside the tail
        assert list(result.recent_messages) == msgs[-3:]
        assert result.recent_messages[0].content == "m4"
        assert result.recent_messages[-1].content == "m6"
