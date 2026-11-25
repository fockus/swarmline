"""Integration tests -- session lifecycle (code-agent-facade plan, Stage 5).

`CodeAgent` gets a `session_id`, auto-persists messages after each run, and
supports `resume(id)`/`reset()` -- reusing `CodeRuntimeSession` value objects
+ `FacadeSessionStore` (thin glue around the EXISTING `JsonlMessageStore`).
`SWARMLINE_SESSIONS_DIR` is forced to a per-test tmp dir by the root
`tests/conftest.py` autouse fixture; this file also sets it explicitly per
the plan's own instruction, which is redundant but harmless.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from swarmline.code_agent import CodeAgent
from swarmline.code_runtime_types import CodeRuntimeSession, CodeSessionStatus
from swarmline.domain_types import RuntimeEvent
from swarmline.runtime.types import Message

from .conftest import FakeRuntimeFactory

pytestmark = pytest.mark.asyncio


def _factory_with_reply(reply_text: str) -> FakeRuntimeFactory:
    """A `FakeRuntimeFactory` whose scripted `final` event carries a real
    assistant `new_messages` entry -- the default `fake_runtime_factory`
    fixture's `final` event has an EMPTY `new_messages` list, which would
    make every turn a no-op for history accumulation."""
    return FakeRuntimeFactory(
        events=[
            RuntimeEvent.final(
                reply_text,
                new_messages=[Message(role="assistant", content=reply_text)],
            )
        ]
    )


class TestSessionId:
    async def test_code_agent_has_auto_uuid_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path))
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        parsed = uuid.UUID(agent.session_id, version=4)

        assert str(parsed) == agent.session_id

    async def test_concurrent_agents_in_same_cwd_get_distinct_session_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path))
        first = CodeAgent(model="sonnet", cwd=str(tmp_path))
        second = CodeAgent(model="sonnet", cwd=str(tmp_path))

        assert first.session_id != second.session_id


class TestRunPersistsSession:
    async def test_run_persists_messages_and_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / "sessions"
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(sessions_dir))
        factory = _factory_with_reply("done")
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        async for _event in agent.run("hi"):
            pass

        session_dir = sessions_dir / agent.session_id
        assert (session_dir / "session.json").exists()
        assert any(session_dir.glob("*.jsonl"))
        assert agent.turn_count == 1


class TestResume:
    async def test_resume_restores_history_and_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        factory = _factory_with_reply("assistant reply")
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        async for _event in agent.run("hi"):
            pass
        session_id = agent.session_id

        resumed = await CodeAgent.resume(session_id, runtime_factory=factory)

        assert resumed.session_id == session_id
        assert resumed.cwd == str(tmp_path)
        assert resumed.model == "sonnet"
        assert len(resumed._messages) >= 2
        assert resumed._messages[0].role == "user"
        assert resumed._messages[0].content == "hi"
        assert any(m.role == "assistant" for m in resumed._messages)

    async def test_resume_unknown_session_raises_file_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))

        with pytest.raises(FileNotFoundError):
            await CodeAgent.resume("no-such-session-id")

    async def test_resume_corrupt_session_json_raises_value_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / "sessions"
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(sessions_dir))
        session_id = "corrupt-session"
        session_dir = sessions_dir / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session.json").write_text("{not valid json")

        with pytest.raises(ValueError, match="Corrupt session.json"):
            await CodeAgent.resume(session_id)

    async def test_kill_then_resume_continues_turn_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No `close()` call -- simulates the process dying after a
        completed turn; resuming picks up `turn_count` where it left off."""
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        factory = _factory_with_reply("first reply")
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)
        async for _event in agent.run("first"):
            pass
        session_id = agent.session_id
        assert agent.turn_count == 1
        del agent  # no close() -- simulated kill

        resumed = await CodeAgent.resume(session_id, runtime_factory=factory)
        assert resumed.turn_count == 1

        async for _event in resumed.run("second"):
            pass
        assert resumed.turn_count == 2


class TestReset:
    async def test_reset_clears_history_keeps_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        factory = _factory_with_reply("done")
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)
        async for _event in agent.run("hi"):
            pass
        session_id = agent.session_id
        cwd = agent.cwd

        await agent.reset()

        assert agent.session_id == session_id
        assert agent.cwd == cwd
        assert agent.turn_count == 0
        assert agent._messages == []

    async def test_reset_persists_cleared_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        factory = _factory_with_reply("done")
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)
        async for _event in agent.run("hi"):
            pass

        await agent.reset()
        resumed = await CodeAgent.resume(agent.session_id, runtime_factory=factory)

        assert resumed.turn_count == 0
        assert resumed._messages == []


class TestSessionSnapshot:
    async def test_session_returns_code_runtime_session_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path))
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        snapshot = agent.session()

        assert isinstance(snapshot, CodeRuntimeSession)
        assert snapshot.session_id == agent.session_id
        assert snapshot.status == CodeSessionStatus.CREATED


class TestFinalEventCommittedBeforeYield:
    async def test_turn_count_bumped_even_if_consumer_breaks_immediately_after_final(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A consumer that stops iterating as soon as it sees the `final`
        event (a very common pattern -- `final` IS the natural "done"
        signal) must still get the auto-save/turn_count bump. Committing
        only works if `run()` persists BEFORE yielding `final`, not after
        the generator is resumed past that yield (which never happens if
        the caller breaks right there)."""
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        factory = _factory_with_reply("done")
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        async for event in agent.run("hi"):
            if event.type == "final":
                break

        assert agent.turn_count == 1


class TestFailedTurnDoesNotPolluteHistory:
    async def test_error_only_turn_does_not_pollute_next_turn_history(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An error-only (no `final`) turn must not leave its user prompt
        sitting in `_messages` for the NEXT turn to inherit -- the design
        says an incomplete turn is "not completed"; that must hold for the
        in-memory history too, not just `turn_count`/persistence."""
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        from swarmline.domain_types import RuntimeErrorData

        failing_factory = FakeRuntimeFactory(
            events=[
                RuntimeEvent.error(
                    RuntimeErrorData(kind="provider_unavailable", message="boom")
                )
            ]
        )
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=failing_factory
        )
        async for _event in agent.run("first prompt (will fail)"):
            pass
        assert agent.turn_count == 0

        succeeding_factory = _factory_with_reply("ok")
        agent._factory = succeeding_factory
        async for _event in agent.run("second prompt"):
            pass

        run_kwargs = succeeding_factory.created[0].run_kwargs
        sent_contents = [m.content for m in run_kwargs["messages"]]
        assert "first prompt (will fail)" not in sent_contents
        assert sent_contents == ["second prompt"]
        assert agent.turn_count == 1


class TestEmptyNewMessagesFallback:
    async def test_final_with_empty_new_messages_falls_back_to_final_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`RuntimeEvent.final(text, new_messages=None)` is a LEGAL contract
        (e.g. the thin runtime's slash-command intercept path uses exactly
        this shape) -- history must not silently lose the reply just
        because `new_messages` came back empty."""
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
        factory = FakeRuntimeFactory(
            events=[RuntimeEvent.final("command output, no new_messages")]
        )
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        async for _event in agent.run("hi"):
            pass

        assert any(
            m.role == "assistant" and m.content == "command output, no new_messages"
            for m in agent._messages
        )


class TestSessionIdPathTraversalGuard:
    async def test_resume_rejects_path_traversal_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))

        with pytest.raises(ValueError, match="session_id"):
            await CodeAgent.resume("../../etc")

    async def test_reset_rejects_path_traversal_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / "sessions"
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(sessions_dir))
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), session_id="../../outside")

        with pytest.raises(ValueError, match="session_id"):
            await agent.reset()

        assert not (sessions_dir.parent / "outside").exists()
