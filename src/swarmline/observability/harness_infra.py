"""Registers the observability-events infra blocks into the harness seam.

``swarmline.harness.registries`` (harness-composition spec, Task 2) defines a
generic, process-wide "name -> zero-arg resolver" seam for composition/infra
blocks, and its own module docstring explicitly sanctions wiring a block in
from OUTSIDE by calling ``get_infra_registry().register(name, resolver)`` --
"without touching this module". This module is exactly that outside caller
for the observability-events journal/replay blocks (REQ-012).

Registration is an EXPLICIT function, never an import side-effect: importing
this module does nothing observable (no import-time dependency on
``swarmline.harness`` at all -- see ``register_observability_infra`` below).
A bootstrap layer calls ``register_observability_infra()`` once, early, to
make ``event_record``/``replay`` resolvable through the harness composition
seam. Side-effect-on-import registration would make availability depend on
unpredictable import order across the codebase, which is exactly the
non-determinism this module avoids by requiring an explicit call.
"""

from __future__ import annotations

from swarmline.observability.journal import InMemoryEventJournal


def register_observability_infra() -> None:
    """Register the ``event_record`` and ``replay`` infra-block resolvers.

    REQ-012. Truly idempotent: if BOTH blocks are already registered, this is
    a no-op that preserves the existing journal (and any events already
    recorded through it) -- it does NOT replace it with a fresh, empty one.
    Presence is checked via the registry's own public ``names()`` (no private
    attribute access; mirrors ``KernelRegistry``'s ``register``/``get``/
    ``names`` shape per the registries module docstring).

    Both resolvers close over the SAME ``InMemoryEventJournal`` instance
    created at (first) registration time, so a consumer resolving
    ``event_record`` to append events and ``replay`` to read them back gets
    one coherent journal, not two independent, disconnected stores.

    # ponytail: harness-composition Task 5 (a parallel, in-flight effort) owns
    # the concrete contract for HOW ``HarnessBuilder.build()`` consumes a
    # resolved infra block. This function deliberately keeps the resolved
    # shape minimal -- "a zero-arg callable returning an object satisfying
    # ``EventJournal``/``ReplayReader``" -- and does not attempt to fully wire
    # consumption; Task 5 may refine or replace this default once its
    # consumption contract lands.
    """
    from swarmline.harness.registries import get_infra_registry

    registry = get_infra_registry()
    if {"event_record", "replay"} <= registry.names():
        return

    journal = InMemoryEventJournal()
    registry.register("event_record", lambda: journal)
    registry.register("replay", lambda: journal)
