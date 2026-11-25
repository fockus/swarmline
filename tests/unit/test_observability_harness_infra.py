"""Unit: register_observability_infra() -- wires event_record/replay resolvers
into the harness infra registry seam from OUTSIDE swarmline.harness (REQ-012).

observability-events spec, Task 4. This module only CALLS the public
``swarmline.harness.registries`` API (``get_infra_registry().register(...)`` /
``.get()`` / ``.names()``) -- it never imports or edits any other harness
module (see the module's own docstring backlog note, which explicitly
sanctions exactly this kind of outside-caller registration).
"""

from __future__ import annotations

import inspect

import pytest

from swarmline.harness.registries import InfraBlockNotFound, get_infra_registry
from swarmline.observability import harness_infra
from swarmline.observability.harness_infra import register_observability_infra
from swarmline.observability.journal import EventJournal, ReplayReader


@pytest.fixture
def clean_infra_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide infra registry's resolver
    dict for the duration of the test.

    The infra registry (``get_infra_registry()``) is a process-wide singleton
    shared with ``test_harness_builder.py`` (which fails if it finds ANY
    leaked registration). ``monkeypatch.setattr`` records the ORIGINAL dict
    object and restores it verbatim on teardown, so registrations made here
    can never leak into other test modules regardless of run order.
    """
    registry = get_infra_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


class TestRegisterObservabilityInfra:
    """REQ-012: explicit (non-import-side-effect) registration of the
    observability-events infra blocks into the harness registry seam.
    """

    def test_event_record_not_found_before_registration(
        self, clean_infra_registry
    ) -> None:
        """Before calling register_observability_infra(), the block is unknown."""
        with pytest.raises(InfraBlockNotFound) as exc_info:
            clean_infra_registry.get("event_record")

        assert "event_record" in str(exc_info.value)

    def test_infra_registry_resolves_event_record_and_replay_after_register(
        self, clean_infra_registry
    ) -> None:
        """After registration, both 'event_record' and 'replay' resolve."""
        register_observability_infra()

        event_record = clean_infra_registry.get("event_record")
        replay = clean_infra_registry.get("replay")

        assert isinstance(event_record, EventJournal)
        assert isinstance(replay, ReplayReader)

    def test_register_observability_infra_is_idempotent(
        self, clean_infra_registry
    ) -> None:
        """Calling register_observability_infra() twice still resolves cleanly:
        a single resolver per name (register() overwrites by name -- no
        duplicate/leaked registrations accumulate).
        """
        register_observability_infra()
        register_observability_infra()

        assert {"event_record", "replay"} <= clean_infra_registry.names()
        assert clean_infra_registry.get("event_record") is not None
        assert clean_infra_registry.get("replay") is not None

    async def test_register_observability_infra_reregister_preserves_recorded_events(
        self, clean_infra_registry
    ) -> None:
        """True idempotency: re-registering must NOT orphan already-recorded
        events behind a fresh, empty journal.

        Record an event through the FIRST registration's ``event_record``
        resolver, call ``register_observability_infra()`` AGAIN, then resolve
        ``replay`` -- it must still see the event appended before the second
        call, proving the second registration preserved the existing
        coherent journal instead of replacing it with a new one.
        """
        register_observability_infra()
        event_journal = clean_infra_registry.get("event_record")
        await event_journal.append("agent.started", {"agent": "demo"})

        register_observability_infra()

        replay = clean_infra_registry.get("replay")
        entries = [entry async for entry in replay.read()]

        assert [entry.event_type for entry in entries] == ["agent.started"]

    def test_registration_uses_only_public_registry_api(self) -> None:
        """Guard: the module source never reaches into ``_BlockRegistry``
        internals (``_resolvers``/``_lock``) -- only the public
        ``register``/``get``/``names`` surface of
        ``swarmline.harness.registries`` is used.
        """
        source = inspect.getsource(harness_infra)

        assert "_resolvers" not in source
        assert "_lock" not in source

    def test_module_does_not_import_harness_at_module_level(self) -> None:
        """The lazy-import discipline (REQ-012): the ``from swarmline.harness``
        import must live INSIDE ``register_observability_infra()``'s body, not
        at module scope -- so merely importing
        ``swarmline.observability.harness_infra`` never touches the harness
        package; only actually CALLING the function does.
        """
        module_source = inspect.getsource(harness_infra)
        function_source = inspect.getsource(register_observability_infra)
        module_scope_source = module_source.split("def register_observability_infra")[0]

        assert "from swarmline.harness" in function_source
        assert "from swarmline.harness" not in module_scope_source
