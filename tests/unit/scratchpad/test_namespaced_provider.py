"""Contract tests for NamespacedScratchpadProvider — namespace boundary integrity.

Entry keys are MODEL-CONTROLLED. Naive `namespace + "/" + key` concatenation is
therefore ambiguous: `ns="a"` with `key="b/plan"` and `ns="a/b"` with
`key="plan"` both produce `a/b/plan`, so a caller in one namespace can address
another's entry just by embedding a separator in the key. `..` segments make it
worse on a path-aware backend, which may normalise them and walk out of the
namespace entirely.

The namespace boundary must therefore not depend on what the model types.
"""

from __future__ import annotations

import pytest

from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider
from swarmline.scratchpad.namespaced_provider import NamespacedScratchpadProvider
from swarmline.scratchpad.protocols import ScratchpadProvider


@pytest.fixture
def shared_backend() -> InMemoryScratchpadProvider:
    return InMemoryScratchpadProvider()


class TestStructuralCompliance:
    def test_decorator_satisfies_the_provider_protocol(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        assert isinstance(
            NamespacedScratchpadProvider(shared_backend, "ns"), ScratchpadProvider
        )

    @pytest.mark.parametrize("bad_namespace", ["", "   ", "/", "///"])
    def test_empty_namespace_is_rejected(
        self, shared_backend: InMemoryScratchpadProvider, bad_namespace: str
    ) -> None:
        with pytest.raises(ValueError):
            NamespacedScratchpadProvider(shared_backend, bad_namespace)


class TestNestedNamespacesCannotCollide:
    """The headline ambiguity: a separator inside a key must not cross a boundary."""

    async def test_key_with_separator_is_not_visible_to_the_nested_namespace(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        outer = NamespacedScratchpadProvider(shared_backend, "a")
        nested = NamespacedScratchpadProvider(shared_backend, "a/b")

        await outer.write("b/plan", "outer secret")

        assert await nested.read("plan") is None, (
            "key separator let a nested namespace read the outer one's entry"
        )
        assert await nested.read(None) == []

    async def test_nested_namespace_entry_is_not_visible_to_the_outer_key(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        outer = NamespacedScratchpadProvider(shared_backend, "a")
        nested = NamespacedScratchpadProvider(shared_backend, "a/b")

        await nested.write("plan", "nested secret")

        assert await outer.read("b/plan") is None
        assert [entry.key for entry in await outer.read(None)] == []

    async def test_sibling_namespaces_with_a_shared_prefix_do_not_collide(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        short = NamespacedScratchpadProvider(shared_backend, "tenant-a")
        longer = NamespacedScratchpadProvider(shared_backend, "tenant-abc")

        await short.write("plan", "short tenant note")

        assert await longer.read("plan") is None
        assert await longer.read(None) == []

    async def test_delete_cannot_reach_across_a_namespace(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        outer = NamespacedScratchpadProvider(shared_backend, "a")
        nested = NamespacedScratchpadProvider(shared_backend, "a/b")
        await nested.write("plan", "nested secret")

        await outer.delete("b/plan")

        survivor = await nested.read("plan")
        assert survivor is not None and not isinstance(survivor, list)
        assert survivor.content == "nested secret"

    async def test_search_cannot_reach_across_a_namespace(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        outer = NamespacedScratchpadProvider(shared_backend, "a")
        nested = NamespacedScratchpadProvider(shared_backend, "a/b")
        await nested.write("plan", "nested confidential body")

        assert await outer.search("confidential") == []


class TestTraversalAndDegenerateKeys:
    @pytest.mark.parametrize(
        "hostile_key",
        ["..", "../plan", "a/../../plan", "./plan", "", "   ", "/", "plan/.."],
    )
    async def test_hostile_keys_never_escape_the_namespace(
        self, shared_backend: InMemoryScratchpadProvider, hostile_key: str
    ) -> None:
        """Either rejected outright, or encoded so the stored key stays inside.

        Both outcomes are acceptable; escaping the namespace is not.
        """
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a")

        try:
            await scoped.write(hostile_key, "payload")
        except ValueError:
            return  # rejected outright — fine

        stored_keys = [entry.key for entry in await shared_backend.read(None)]
        assert stored_keys, "write reported success but stored nothing"
        assert all(key.startswith("tenant-a/") for key in stored_keys), (
            f"key escaped the namespace: {stored_keys}"
        )
        assert all(".." not in key.split("/") for key in stored_keys), (
            f"traversal segment survived: {stored_keys}"
        )

    async def test_hostile_key_roundtrips_for_its_own_namespace(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        """If a key is accepted, the caller must be able to read it back by the same key."""
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a")

        try:
            await scoped.write("a/b", "payload")
        except ValueError:
            pytest.skip("separator keys are rejected outright by this implementation")

        entry = await scoped.read("a/b")
        assert entry is not None and not isinstance(entry, list)
        assert entry.content == "payload"


class TestNormalKeysStillWork:
    async def test_model_keys_are_preserved_end_to_end(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a/ws-1")

        written = await scoped.write("plan", "body", tags=("t",))
        read_back = await scoped.read("plan")
        listed = await scoped.read(None)
        found = await scoped.search("body")

        assert written.key == "plan"
        assert read_back is not None and not isinstance(read_back, list)
        assert read_back.key == "plan"
        assert [entry.key for entry in listed] == ["plan"]
        assert [entry.key for entry in found] == ["plan"]
        assert await scoped.delete("plan") is True


class TestPrefixItselfIsNotAnEntry:
    """A key equal to the namespace prefix is the CONTAINER, not an entry in it.

    `_owns` checked only that the remainder held no separator — and the empty
    remainder trivially satisfies that, so the prefix claimed itself. The
    decorator would then surface a phantom entry whose key decodes to `""`.

    TaskLoom's own wiring cannot produce this today (`encode_key` rejects blank
    keys, and the prefix always carries a trailing separator), but the backend is
    SHARED: anything else writing to it — another decorator, a migration, a
    direct caller — can leave such a key behind. For a public 2.0.0 library the
    boundary must hold regardless of who else writes to the store.
    """

    def test_the_prefix_itself_is_not_owned(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a")

        assert scoped._owns(scoped.namespace) is False

    async def test_a_bare_prefix_key_is_not_listed_as_an_entry(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a")
        await shared_backend.write(
            "tenant-a/", "written straight to the shared backend"
        )

        listed = await scoped.read(None)

        assert listed == [], (
            f"the namespace container surfaced as an entry: {[e.key for e in listed]}"
        )

    async def test_a_bare_prefix_key_is_not_searchable(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a")
        await shared_backend.write("tenant-a/", "container body")

        assert await scoped.search("container") == []

    async def test_no_entry_is_ever_surfaced_with_an_empty_key(
        self, shared_backend: InMemoryScratchpadProvider
    ) -> None:
        """The user-visible symptom of the bug: a keyless entry in the listing."""
        scoped = NamespacedScratchpadProvider(shared_backend, "tenant-a")
        await shared_backend.write("tenant-a/", "phantom")
        await scoped.write("real", "genuine note")

        listed = await scoped.read(None)

        assert [entry.key for entry in listed] == ["real"]
        assert all(entry.key for entry in listed), "an entry surfaced with an empty key"
