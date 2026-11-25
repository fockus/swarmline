"""Contract tests for swarmline.graph.channels (Epic D, Stage D1.1).

Covers the LangGraph-style reducer/channel primitives: `replace`, `add`,
`add_messages`, the frozen `Channel` dataclass, and the `init_state` /
`apply_update` state-folding helpers.
"""

from __future__ import annotations

import dataclasses

from swarmline.graph.channels import (
    Channel,
    add,
    add_messages,
    apply_update,
    init_state,
    replace,
)


class TestReplaceReducer:
    def test_replace_reducer_returns_update_overwriting_current(self) -> None:
        current = {"a": 1}
        update = {"b": 2}

        result = replace(current, update)

        assert result == {"b": 2}
        assert result is update


class TestAddReducer:
    def test_add_reducer_concatenates_lists(self) -> None:
        current = [1, 2]
        update = [3, 4]

        result = add(current, update)

        assert result == [1, 2, 3, 4]

    def test_add_reducer_sums_numbers(self) -> None:
        assert add(2, 3) == 5
        assert add(2.5, 1.5) == 4.0

    def test_add_reducer_concatenates_strings(self) -> None:
        assert add("foo", "bar") == "foobar"

    def test_add_reducer_uses_default_factory_when_current_is_none(self) -> None:
        result = add(None, [1, 2])

        assert result == [1, 2]

    def test_add_reducer_raises_type_error_on_incompatible_scalars(self) -> None:
        try:
            add(1, "x")
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError for incompatible add() operands")


class TestAddMessagesReducer:
    def test_add_messages_appends_new_messages(self) -> None:
        current = [{"id": "1", "text": "hi"}]
        update = [{"id": "2", "text": "there"}]

        result = add_messages(current, update)

        assert result == [
            {"id": "1", "text": "hi"},
            {"id": "2", "text": "there"},
        ]

    def test_add_messages_replaces_message_with_matching_id(self) -> None:
        current = [{"id": "1", "text": "hi"}, {"id": "2", "text": "there"}]
        update = [{"id": "2", "text": "edited"}]

        result = add_messages(current, update)

        assert len(result) == 2
        assert result[1] == {"id": "2", "text": "edited"}

    def test_add_messages_accepts_a_single_non_list_message(self) -> None:
        current = [{"id": "1", "text": "hi"}]
        update = {"id": "2", "text": "single"}

        result = add_messages(current, update)

        assert result == [
            {"id": "1", "text": "hi"},
            {"id": "2", "text": "single"},
        ]


class TestChannelAndStateSchema:
    def test_apply_update_uses_declared_reducer_per_channel(self) -> None:
        schema = {"acc": Channel(reducer=add, default_factory=list)}
        state = init_state(schema)

        new_state = apply_update(state, {"acc": [1, 2]}, schema)
        new_state = apply_update(new_state, {"acc": [3]}, schema)

        assert new_state["acc"] == [1, 2, 3]

    def test_apply_update_defaults_to_replace_for_undeclared_channel(self) -> None:
        schema: dict[str, Channel] = {}
        state = {"foo": "old"}

        new_state = apply_update(state, {"foo": "new"}, schema)

        assert new_state["foo"] == "new"

    def test_apply_update_returns_new_dict_without_mutating_input(self) -> None:
        schema = {"acc": Channel(reducer=add, default_factory=list)}
        state = init_state(schema)
        state["acc"].append("preexisting")
        original_id = id(state)

        new_state = apply_update(state, {"acc": ["x"]}, schema)

        assert new_state is not state
        assert id(state) == original_id
        assert state["acc"] == ["preexisting"]
        assert new_state["acc"] == ["preexisting", "x"]

    def test_apply_update_with_empty_update_returns_equal_but_new_dict(self) -> None:
        schema = {"acc": Channel(reducer=add, default_factory=list)}
        state = init_state(schema)

        new_state = apply_update(state, {}, schema)

        assert new_state == state
        assert new_state is not state

    def test_init_state_seeds_declared_default_factories(self) -> None:
        schema = {
            "acc": Channel(reducer=add, default_factory=list),
            "counter": Channel(reducer=add, default_factory=int),
            "flag": Channel(reducer=replace),
        }

        state = init_state(schema)

        assert state["acc"] == []
        assert state["counter"] == 0
        assert "flag" not in state

    def test_channel_is_frozen(self) -> None:
        channel = Channel(reducer=add, default_factory=list)

        try:
            channel.reducer = replace  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:
            raise AssertionError("expected Channel to be frozen (immutable)")
