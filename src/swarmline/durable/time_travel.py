"""Time-travel — history + fork over a B1 ``Checkpointer`` (Stage C1.3).

Pure wrappers: ``get_state_history`` resolves the full ``Checkpoint`` for
every entry in the thread's ``list()`` history (oldest-first, per the B1
``Checkpointer.list`` guarantee); ``fork`` branches a new checkpoint off an
existing one via ``get`` + ``put(parent_id=...)``. No new state, no new
storage -- these compose entirely on top of the existing B1 contract.

I-095 caveat (known C1.1 backlog, NOT fixed here): in ``async`` durability
mode, a background progress-checkpoint write can fail after its
``parent_id`` was already handed to a sibling/child checkpoint, leaving a
dangling reference in that thread's chain. History is returned exactly as
stored -- ``get_state_history`` does not repair or hide such gaps.
"""

from __future__ import annotations

import copy
from collections import Counter

from swarmline.protocols.checkpoint import Checkpoint, Checkpointer


async def get_state_history(
    checkpointer: Checkpointer, thread_id: str
) -> list[Checkpoint]:
    """Return the thread's full checkpoint history, oldest-first.

    Fails loud on a duplicated ``checkpoint_id``: B1 explicitly allows an
    explicit duplicate id to append a NEW row rather than replace one, but
    ``Checkpointer.get(checkpoint_id=...)`` only ever returns the LATEST
    matching row -- there is no row-stable lookup in the protocol, so a
    duplicated id makes "full history" ambiguous. Rather than silently
    returning the same (latest) row twice and losing the earlier one, this
    raises so the caller knows the thread's history cannot be resolved
    honestly.
    """
    metas = await checkpointer.list(thread_id)
    duplicates = [cid for cid, n in Counter(m.id for m in metas).items() if n > 1]
    if duplicates:
        raise ValueError(
            f"thread {thread_id!r} has duplicated checkpoint id(s) {duplicates!r} "
            "-- get(checkpoint_id=...) cannot resolve a stable row per id, so "
            "the full history is ambiguous"
        )
    history: list[Checkpoint] = []
    for meta in metas:
        checkpoint = await checkpointer.get(thread_id, checkpoint_id=meta.id)
        if checkpoint is not None:
            history.append(checkpoint)
    return history


async def fork(checkpointer: Checkpointer, thread_id: str, checkpoint_id: str) -> str:
    """Branch a new checkpoint off ``checkpoint_id``; return the new id.

    The new checkpoint is a branch ROOT: a DEEP copy of the source's
    ``state`` (both ``get`` and ``put`` only shallow-copy, so nested
    containers would otherwise alias the source), same ``resource_id``,
    ``parent_id`` pointing at ``checkpoint_id`` -- an independent timeline
    the caller can now write onto without touching the source's own
    lineage.
    """
    cp = await checkpointer.get(thread_id, checkpoint_id=checkpoint_id)
    if cp is None:
        raise LookupError(
            f"checkpoint {checkpoint_id!r} not found on thread {thread_id!r}"
        )
    return await checkpointer.put(
        thread_id,
        copy.deepcopy(dict(cp.state)),
        resource_id=cp.resource_id,
        parent_id=checkpoint_id,
    )
