# Design Patterns

This guide shows how to combine swarmline features for real-world use cases. Each pattern includes a complete, runnable code example with the exact imports from the codebase.

---

## 1. Production-Ready Agent

**Combines:** Agent + CostBudget + Guardrails + RetryPolicy + InputFilter

### When to Use

You are deploying an agent that handles real user traffic. You need:

- Input validation (length limits, forbidden patterns)
- Cost budget enforcement so a single query cannot drain your account
- Retry with exponential backoff for transient API failures
- Model fallback chain for rate limit resilience
- Security middleware to block dangerous tool inputs

### Architecture

```
User Prompt
    |
    v
+-------------------+      +--------------------+
| ContentLength     |----->| RegexGuardrail     |
| Guardrail (input) |      | (forbidden words)  |
+-------------------+      +--------------------+
                                   |
                                   v
                          +------------------+
                          | MaxTokensFilter  |
                          | (truncate old    |
                          |  messages)       |
                          +------------------+
                                   |
                                   v
                 +-------------------------------+
                 |          Agent                 |
                 |  middleware:                   |
                 |    SecurityGuard               |
                 |    ToolOutputCompressor        |
                 |    CostTracker                 |
                 |  retry: ExponentialBackoff     |
                 |  fallback: ModelFallbackChain  |
                 +-------------------------------+
                                   |
                                   v
                          +------------------+
                          | ContentLength    |
                          | Guardrail        |
                          | (output check)   |
                          +------------------+
                                   |
                                   v
                              Result
```

### Code

```python
"""Production-ready agent with all safety layers composed together."""

import asyncio

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import (
    BudgetExceededError,
    CostTracker,
    Middleware,
    SecurityGuard,
    ToolOutputCompressor,
    build_middleware_stack,
)
from swarmline.agent.result import Result
from swarmline.guardrails import (
    ContentLengthGuardrail,
    GuardrailContext,
    GuardrailResult,
    RegexGuardrail,
)
from swarmline.input_filters import MaxTokensFilter, SystemPromptInjector
from swarmline.retry import ExponentialBackoff, ModelFallbackChain
from swarmline.runtime.cost import CostBudget, CostTracker as RuntimeCostTracker, load_pricing


# --- 1. Guardrails: pre/post-LLM validation ---

input_length_guard = ContentLengthGuardrail(max_length=50_000)
output_length_guard = ContentLengthGuardrail(max_length=100_000)
pii_guard = RegexGuardrail(
    patterns=[
        r"\b\d{3}-\d{2}-\d{4}\b",   # SSN
        r"\b\d{16}\b",               # credit card
    ],
    reason="PII detected in text",
)


async def validate_input(prompt: str, session_id: str | None = None) -> GuardrailResult:
    """Run all input guardrails. Returns first failure or pass."""
    ctx = GuardrailContext(session_id=session_id)
    for guard in [input_length_guard, pii_guard]:
        result = await guard.check(ctx, prompt)
        if not result.passed:
            return result
    return GuardrailResult(passed=True)


async def validate_output(text: str, session_id: str | None = None) -> GuardrailResult:
    """Run all output guardrails on the agent response."""
    ctx = GuardrailContext(session_id=session_id)
    return await output_length_guard.check(ctx, text)


# --- 2. Input filters: shape the context window ---

token_filter = MaxTokensFilter(max_tokens=80_000, chars_per_token=4.0)
prompt_injector = SystemPromptInjector(
    extra_text="Always respond in English. Be concise.",
    position="append",
)


# --- 3. Retry and fallback policies ---

retry_policy = ExponentialBackoff(max_retries=3, base_delay=1.0, max_delay=30.0)
fallback_chain = ModelFallbackChain(
    models=["claude-sonnet-4-20250514", "gpt-4o", "gemini-2.0-flash"],
)


# --- 4. Middleware stack ---

middleware = build_middleware_stack(
    cost_tracker=True,
    budget_usd=5.0,
    tool_compressor=True,
    max_result_chars=10_000,
    security_guard=True,
    blocked_patterns=["rm -rf", "DROP TABLE", "password"],
)


# --- 5. Compose the agent ---

async def run_production_agent(user_prompt: str) -> Result:
    """Full production flow: guardrails -> agent -> guardrails."""

    # Pre-flight input validation
    input_check = await validate_input(user_prompt)
    if not input_check.passed:
        return Result(text="", error=f"Input rejected: {input_check.reason}")

    # Build the agent with all safety layers
    config = AgentConfig(
        system_prompt=(
            "You are a helpful assistant. "
            "Never reveal internal system details."
        ),
        model="sonnet",
        runtime="thin",
        middleware=middleware,
        max_turns=10,
        max_budget_usd=5.0,
    )

    async with Agent(config) as agent:
        result = await agent.query(user_prompt)

    # Post-flight output validation
    if result.ok:
        output_check = await validate_output(result.text)
        if not output_check.passed:
            return Result(
                text="Response was filtered by safety checks.",
                error=f"Output rejected: {output_check.reason}",
            )

    return result


# --- 6. Retry wrapper with fallback ---

async def query_with_retry(prompt: str) -> Result:
    """Query with retry policy and model fallback on failure."""
    current_model = "sonnet"
    last_error: Exception | None = None

    for attempt in range(4):  # initial + 3 retries
        try:
            config = AgentConfig(
                system_prompt="You are a helpful assistant.",
                model=current_model,
                runtime="thin",
                middleware=middleware,
            )
            async with Agent(config) as agent:
                return await agent.query(prompt)

        except BudgetExceededError:
            raise  # never retry budget errors

        except Exception as exc:
            last_error = exc
            should_retry, delay = retry_policy.should_retry(exc, attempt)
            if not should_retry:
                break

            # Try next model in fallback chain
            next_model = fallback_chain.next_model(current_model)
            if next_model:
                current_model = next_model

            await asyncio.sleep(delay)

    return Result(text="", error=f"All retries exhausted: {last_error}")
```

### Key Configuration Points

- **`ContentLengthGuardrail(max_length=50_000)`** -- reject oversized inputs before they hit the LLM
- **`build_middleware_stack()`** -- one-call factory for the standard SecurityGuard + ToolOutputCompressor + CostTracker combo
- **`ExponentialBackoff(max_retries=3)`** -- retry transient errors with jitter to avoid thundering herd
- **`ModelFallbackChain(models=[...])`** -- degrade to cheaper/available models when primary is rate-limited
- **`max_budget_usd=5.0`** -- hard budget cap at both Agent config level and CostTracker middleware level

---

## 2. Research Agent with RAG

**Combines:** Agent + Retriever + Memory + Sessions

### When to Use

You are building a research assistant that:

- Searches a local knowledge base before answering (RAG)
- Remembers user preferences and past findings across sessions
- Persists conversation history with summaries

### Architecture

```
User Query
    |
    v
+--------------------+
| SimpleRetriever    |   documents[]
| (word overlap or   |<----- loaded from files/DB
|  custom embedding) |
+--------------------+
    |
    v  retrieved docs
+--------------------+
| RagInputFilter     |   injects <context>...</context>
|                    |   into system_prompt
+--------------------+
    |
    v
+--------------------+
| Agent              |
| runtime: "thin"    |
+--------------------+
    |
    v  result
+------------------------------------+
| InMemoryMemoryProvider             |
|   save_message(user_id, topic_id)  |
|   upsert_fact(user_id, key, val)   |
|   save_summary(user_id, topic_id)  |
+------------------------------------+
    |
    v
+------------------------------------+
| SqliteSessionBackend               |
|   save(key, state)                 |
|   load(key) -> state               |
+------------------------------------+
```

### Code

```python
"""Research agent with RAG, persistent memory, and session management."""

import asyncio

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.memory.inmemory import InMemoryMemoryProvider
from swarmline.rag import Document, RagInputFilter, SimpleRetriever
from swarmline.session.backends import (
    InMemorySessionBackend,
    MemoryScope,
    SqliteSessionBackend,
    scoped_key,
)


# --- 1. Build a knowledge base ---

knowledge_base = [
    Document(
        content="Python asyncio provides an event loop for concurrent I/O operations.",
        metadata={"source": "python-docs", "topic": "asyncio"},
    ),
    Document(
        content="FastAPI uses Starlette for ASGI and Pydantic for data validation.",
        metadata={"source": "fastapi-docs", "topic": "web"},
    ),
    Document(
        content="SQLAlchemy 2.0 supports both sync and async database sessions.",
        metadata={"source": "sqlalchemy-docs", "topic": "database"},
    ),
    Document(
        content="Swarmline agents support thin, claude_sdk, and deepagents runtimes.",
        metadata={"source": "swarmline-docs", "topic": "agents"},
    ),
]

retriever = SimpleRetriever(documents=knowledge_base)
rag_filter = RagInputFilter(retriever=retriever, top_k=3)


# --- 2. Memory provider for facts and history ---

memory = InMemoryMemoryProvider()


# --- 3. Session backend for persistence ---

# Use SqliteSessionBackend for persistence across restarts:
#   session_backend = SqliteSessionBackend(db_path="research_sessions.db")
session_backend = InMemorySessionBackend()

USER_ID = "researcher-1"
TOPIC_ID = "python-async"


async def research_query(query: str) -> str:
    """Execute a research query with RAG context injection."""

    # Retrieve relevant documents
    from swarmline.runtime.types import Message

    messages = [Message(role="user", content=query)]
    filtered_messages, enriched_prompt = await rag_filter.filter(
        messages,
        "You are a research assistant. Use the provided context to answer "
        "accurately. Cite sources when possible.",
    )

    # Build agent with enriched system prompt
    config = AgentConfig(
        system_prompt=enriched_prompt,
        model="sonnet",
        runtime="thin",
    )

    async with Agent(config) as agent:
        result = await agent.query(query)

    if result.ok:
        # Persist conversation to memory
        await memory.save_message(USER_ID, TOPIC_ID, "user", query)
        await memory.save_message(USER_ID, TOPIC_ID, "assistant", result.text)

        # Extract and store facts (in production, use LLM extraction)
        await memory.upsert_fact(
            USER_ID, f"last_query_{TOPIC_ID}", query, source="system"
        )

        # Persist session state
        session_key = scoped_key(MemoryScope.AGENT, f"{USER_ID}:{TOPIC_ID}")
        msg_count = await memory.count_messages(USER_ID, TOPIC_ID)
        await session_backend.save(session_key, {
            "user_id": USER_ID,
            "topic_id": TOPIC_ID,
            "message_count": msg_count,
            "model": "sonnet",
        })

    return result.text if result.ok else f"Error: {result.error}"


async def get_session_context() -> dict | None:
    """Load previous session context for continuity."""
    session_key = scoped_key(MemoryScope.AGENT, f"{USER_ID}:{TOPIC_ID}")
    state = await session_backend.load(session_key)
    if state:
        # Load conversation history
        messages = await memory.get_messages(USER_ID, TOPIC_ID, limit=20)
        facts = await memory.get_facts(USER_ID, topic_id=TOPIC_ID)
        summary = await memory.get_summary(USER_ID, TOPIC_ID)
        return {
            "session": state,
            "history_length": len(messages),
            "facts": facts,
            "summary": summary,
        }
    return None


async def summarize_session() -> None:
    """Create a summary of the current research session."""
    messages = await memory.get_messages(USER_ID, TOPIC_ID, limit=50)
    if len(messages) >= 5:
        # In production, use LLM to generate summary
        topics = set()
        for msg in messages:
            if msg.role == "user":
                topics.add(msg.content[:50])
        summary_text = f"Research session covering: {'; '.join(topics)}"
        await memory.save_summary(
            USER_ID, TOPIC_ID, summary_text, messages_covered=len(messages)
        )


async def main() -> None:
    # Check for existing session
    ctx = await get_session_context()
    if ctx:
        print(f"Resuming session: {ctx['history_length']} messages, facts={ctx['facts']}")

    # Run research queries
    answer = await research_query("How does asyncio work with FastAPI?")
    print(f"Answer: {answer[:200]}...")

    # Summarize after multiple queries
    await summarize_session()


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Configuration Points

- **`SimpleRetriever`** -- swap with a custom `Retriever` implementation backed by a vector database (Chroma, Pinecone, pgvector) for production embeddings
- **`RagInputFilter`** -- automatically injects `<context>...</context>` blocks into the system prompt; works with any runtime
- **`InMemoryMemoryProvider`** -- swap with `SqliteMemoryProvider` or `PostgresMemoryProvider` for persistence; same API
- **`scoped_key(MemoryScope.AGENT, ...)`** -- namespace isolation prevents session data leakage between agents

---

## 3. Multi-Agent Team

**Combines:** AgentTool + TaskQueue + AgentRegistry

### When to Use

You are building a system where:

- An orchestrator agent delegates subtasks to specialist agents
- Tasks are queued by priority and claimed by available workers
- Agent lifecycle is tracked in a central registry

### Architecture

```
                    +---------------------+
                    |   Orchestrator      |
                    |   Agent             |
                    +----------+----------+
                               |
              +----------------+----------------+
              |                |                |
              v                v                v
    +---------+------+ +------+--------+ +-----+---------+
    | math_expert    | | code_reviewer | | data_analyst  |
    | (agent-as-tool)| | (agent-as-tool)| | (agent-as-tool)|
    +---------+------+ +------+--------+ +-----+---------+
              |                |                |
              v                v                v
    +---------+------+ +------+--------+ +-----+---------+
    | AgentRecord    | | AgentRecord   | | AgentRecord   |
    | in Registry    | | in Registry   | | in Registry   |
    +----------------+ +---------------+ +---------------+
              |                |                |
              +----------------+----------------+
                               |
                               v
                      +--------+--------+
                      | InMemoryTask   |
                      | Queue          |
                      | (priority-     |
                      |  based)        |
                      +-----------------+
```

### Code

```python
"""Multi-agent team: orchestrator delegates to specialists via task queue."""

import asyncio
import time
from collections.abc import AsyncIterator

from swarmline.multi_agent.agent_registry import InMemoryAgentRegistry
from swarmline.multi_agent.agent_tool import create_agent_tool_spec, execute_agent_tool
from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus
from swarmline.multi_agent.task_queue import InMemoryTaskQueue
from swarmline.multi_agent.task_types import TaskFilter, TaskItem, TaskPriority, TaskStatus
from swarmline.runtime.types import Message, RuntimeEvent, ToolSpec


# --- 1. Agent Registry: track all agents ---

registry = InMemoryAgentRegistry()
task_queue = InMemoryTaskQueue()


async def setup_team() -> None:
    """Register the orchestrator and specialist agents."""
    agents = [
        AgentRecord(
            id="orchestrator",
            name="Team Lead",
            role="lead",
            runtime_name="thin",
            budget_limit_usd=10.0,
        ),
        AgentRecord(
            id="math-expert",
            name="Math Expert",
            role="specialist",
            parent_id="orchestrator",
            runtime_name="thin",
            metadata={"specialty": "mathematics"},
        ),
        AgentRecord(
            id="code-reviewer",
            name="Code Reviewer",
            role="specialist",
            parent_id="orchestrator",
            runtime_name="thin",
            metadata={"specialty": "code-review"},
        ),
        AgentRecord(
            id="data-analyst",
            name="Data Analyst",
            role="specialist",
            parent_id="orchestrator",
            runtime_name="thin",
            metadata={"specialty": "data-analysis"},
        ),
    ]
    for agent in agents:
        await registry.register(agent)


# --- 2. Mock specialist runtimes ---

async def math_expert_run(
    *, messages: list[Message], system_prompt: str, active_tools: list[ToolSpec], **kw
) -> AsyncIterator[RuntimeEvent]:
    """Simulated math expert agent."""
    query = messages[-1].content if messages else ""
    response = f"[Math Expert] Analysis of '{query}': The derivative is 2x + 3."
    yield RuntimeEvent.assistant_delta(text=response)
    yield RuntimeEvent.final(text=response, new_messages=[])


async def code_reviewer_run(
    *, messages: list[Message], system_prompt: str, active_tools: list[ToolSpec], **kw
) -> AsyncIterator[RuntimeEvent]:
    """Simulated code reviewer agent."""
    query = messages[-1].content if messages else ""
    response = f"[Code Reviewer] Review of '{query}': Code looks clean. Consider adding type hints."
    yield RuntimeEvent.assistant_delta(text=response)
    yield RuntimeEvent.final(text=response, new_messages=[])


# Map agent IDs to their runtime functions
AGENT_RUNTIMES = {
    "math-expert": math_expert_run,
    "code-reviewer": code_reviewer_run,
}


# --- 3. Create tool specs for agent-as-tool ---

agent_tool_specs = {
    "math-expert": create_agent_tool_spec(
        name="math_expert",
        description="Delegate a math problem to the Math Expert agent.",
    ),
    "code-reviewer": create_agent_tool_spec(
        name="code_reviewer",
        description="Request a code review from the Code Reviewer agent.",
    ),
}


# --- 4. Orchestrator workflow ---

async def orchestrate(task_description: str) -> dict[str, str]:
    """Orchestrator: create tasks, dispatch to specialists, collect results."""
    results: dict[str, str] = {}

    # Create tasks in the queue
    tasks = [
        TaskItem(
            id="task-math-1",
            title="Solve the math component",
            description=task_description,
            priority=TaskPriority.HIGH,
            assignee_agent_id="math-expert",
            created_at=time.time(),
        ),
        TaskItem(
            id="task-review-1",
            title="Review the solution code",
            description=task_description,
            priority=TaskPriority.MEDIUM,
            assignee_agent_id="code-reviewer",
            created_at=time.time(),
        ),
    ]
    for task in tasks:
        await task_queue.put(task)

    # Process tasks by dispatching to specialist agents
    for task in tasks:
        agent_id = task.assignee_agent_id
        if agent_id is None or agent_id not in AGENT_RUNTIMES:
            continue

        # Update agent status in registry
        await registry.update_status(agent_id, AgentStatus.RUNNING)

        # Execute the specialist agent as a tool
        run_fn = AGENT_RUNTIMES[agent_id]
        agent_result = await execute_agent_tool(
            run_fn=run_fn,
            query=task.description,
            system_prompt=f"You are a specialist agent. Task: {task.title}",
            timeout_seconds=30.0,
        )

        # Record result and update task status
        if agent_result.success:
            results[agent_id] = agent_result.output
            await task_queue.complete(task.id)
        else:
            results[agent_id] = f"ERROR: {agent_result.error}"
            await task_queue.cancel(task.id)

        await registry.update_status(agent_id, AgentStatus.IDLE)

    return results


async def main() -> None:
    await setup_team()

    # Show registered team
    team = await registry.list_agents(AgentFilter(parent_id="orchestrator"))
    print("Team members:")
    for agent in team:
        print(f"  {agent.name} (role={agent.role}, specialty={agent.metadata.get('specialty')})")

    # Run orchestration
    results = await orchestrate("Analyze the function f(x) = x^2 + 3x and review the implementation")
    print("\nResults:")
    for agent_id, output in results.items():
        print(f"  {agent_id}: {output}")

    # Show final task states
    all_tasks = await task_queue.list_tasks()
    print("\nTask states:")
    for task in all_tasks:
        print(f"  [{task.status.value}] {task.title}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Configuration Points

- **`create_agent_tool_spec(name, description)`** -- generates a `ToolSpec` with a single `query` parameter so the orchestrator LLM can call specialist agents like regular tools
- **`execute_agent_tool(run_fn, query, timeout_seconds=30)`** -- runs any async runtime generator and collects the final result with a timeout
- **`InMemoryTaskQueue`** -- swap with `SqliteTaskQueue(db_path="tasks.db")` for persistence across restarts; same API
- **`AgentRecord(parent_id="orchestrator")`** -- establishes hierarchy; query with `AgentFilter(parent_id=...)` to find a leader's team

---

## 4. Conversational Agent with Memory

**Combines:** Conversation + SessionBackend + MemoryProvider

### When to Use

You are building a chatbot or assistant that:

- Maintains multi-turn conversation context within a session
- Persists sessions to disk (survives restarts)
- Remembers user facts and preferences across sessions
- Summarizes old conversations to manage context window size

### Architecture

```
User
  |
  |  say("Hello")
  v
+---------------------+
| Conversation        |
|  session_id: "abc"  |
|  history: Message[] |
+----------+----------+
           |
           | executes via Agent
           v
+---------------------+
| Agent               |
| runtime: "thin"     |
| middleware: [...]    |
+----------+----------+
           |
           v  Result
+---------------------+     +-------------------------+
| Conversation        |     | SqliteSessionBackend    |
|  appends to history |---->| save(key, state)        |
+---------------------+     | load(key) -> state      |
                             +-------------------------+
                                       |
                                       v
                             +-------------------------+
                             | InMemoryMemoryProvider  |
                             | save_message()          |
                             | upsert_fact()           |
                             | save_summary()          |
                             +-------------------------+
```

### Code

```python
"""Conversational agent with session persistence and long-term memory."""

import asyncio

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.conversation import Conversation
from swarmline.agent.middleware import CostTracker, ToolOutputCompressor
from swarmline.memory.inmemory import InMemoryMemoryProvider
from swarmline.session.backends import (
    InMemorySessionBackend,
    MemoryScope,
    SqliteSessionBackend,
    scoped_key,
)


# --- 1. Long-term memory ---

memory = InMemoryMemoryProvider()

# For production persistence:
#   from swarmline.memory.sqlite import SqliteMemoryProvider
#   memory = SqliteMemoryProvider(db_path="memory.db")


# --- 2. Session persistence ---

# InMemorySessionBackend for dev, SqliteSessionBackend for production
session_backend = InMemorySessionBackend()
# session_backend = SqliteSessionBackend(db_path="chat_sessions.db")


# --- 3. Build the conversational agent ---

USER_ID = "user-42"
TOPIC_ID = "general-chat"


async def build_system_prompt() -> str:
    """Build a system prompt enriched with remembered facts."""
    base_prompt = "You are a friendly assistant. Remember details the user shares."

    # Load known facts about this user
    facts = await memory.get_facts(USER_ID, topic_id=TOPIC_ID)
    if facts:
        facts_text = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        base_prompt += f"\n\nKnown facts about this user:\n{facts_text}"

    # Load previous summary if available
    summary = await memory.get_summary(USER_ID, TOPIC_ID)
    if summary:
        base_prompt += f"\n\nPrevious conversation summary:\n{summary}"

    return base_prompt


async def chat_session(user_messages: list[str]) -> None:
    """Run a multi-turn chat session with persistence."""

    system_prompt = await build_system_prompt()

    cost_tracker = CostTracker(budget_usd=2.0)
    config = AgentConfig(
        system_prompt=system_prompt,
        model="sonnet",
        runtime="thin",
        middleware=(
            ToolOutputCompressor(max_result_chars=5000),
            cost_tracker,
        ),
    )

    agent = Agent(config)
    session_key = scoped_key(MemoryScope.AGENT, f"{USER_ID}:{TOPIC_ID}")

    # Load previous session state
    prev_state = await session_backend.load(session_key)
    turn_offset = prev_state.get("turn_count", 0) if prev_state else 0

    async with agent.conversation(session_id=f"{USER_ID}:{TOPIC_ID}") as conv:
        for i, user_msg in enumerate(user_messages):
            turn_num = turn_offset + i + 1

            # Send message and get response
            result = await conv.say(user_msg)

            if result.ok:
                print(f"[Turn {turn_num}] User: {user_msg}")
                print(f"[Turn {turn_num}] Assistant: {result.text[:200]}")

                # Persist to long-term memory
                await memory.save_message(USER_ID, TOPIC_ID, "user", user_msg)
                await memory.save_message(USER_ID, TOPIC_ID, "assistant", result.text)
            else:
                print(f"[Turn {turn_num}] Error: {result.error}")

        # Save session state for next time
        await session_backend.save(session_key, {
            "user_id": USER_ID,
            "topic_id": TOPIC_ID,
            "turn_count": turn_offset + len(user_messages),
            "cost_usd": cost_tracker.total_cost_usd,
        })

    # Summarize if conversation is getting long
    msg_count = await memory.count_messages(USER_ID, TOPIC_ID)
    if msg_count > 20:
        await memory.save_summary(
            USER_ID, TOPIC_ID,
            summary=f"Extended conversation with {msg_count} messages.",
            messages_covered=msg_count,
        )
        # Trim old messages, keep last 10
        await memory.delete_messages_before(USER_ID, TOPIC_ID, keep_last=10)


async def remember_fact(key: str, value: str) -> None:
    """Store a user fact for future sessions."""
    await memory.upsert_fact(USER_ID, key, value, topic_id=TOPIC_ID, source="user")


async def main() -> None:
    # Session 1: introduce yourself
    await remember_fact("name", "Alice")
    await remember_fact("language", "Python")

    await chat_session([
        "Hi, my name is Alice. I write Python.",
        "What async frameworks do you recommend?",
        "Tell me more about FastAPI.",
    ])

    # Session 2: agent remembers Alice
    print("\n--- New session (facts persisted) ---")
    await chat_session([
        "What was my name again?",
        "What language do I use?",
    ])


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Configuration Points

- **`agent.conversation(session_id=...)`** -- creates a `Conversation` that maintains message history across turns within the same session
- **`SqliteSessionBackend`** -- drop-in replacement for `InMemorySessionBackend`; persists across process restarts with zero config
- **`memory.save_summary()` + `memory.delete_messages_before(keep_last=10)`** -- sliding window pattern to keep context manageable
- **`build_system_prompt()`** -- inject remembered facts and summaries into each new session's system prompt

---

## 5. Cost-Controlled Pipeline

**Combines:** CostBudget + ModelFallbackChain + CancellationToken

### When to Use

You are running a multi-step LLM pipeline (e.g., research, summarize, format) and need:

- A total cost budget across all steps
- Graceful degradation to cheaper models when budget runs low
- Cooperative cancellation if budget is exceeded mid-pipeline

### Architecture

```
Pipeline Start
    |
    v
+------------------+
| CostBudget       |  max_cost_usd=2.0
| CostTracker      |  tracks cumulative spend
+--------+---------+
         |
         v
+--------+---------+   budget OK?
| Step 1: Research |-----------> continue
| model: sonnet    |   exceeded?
+--------+---------+-----------> fallback to cheaper model
         |                       or cancel pipeline
         v
+--------+---------+
| Step 2: Analyze  |
| model: (current) |
+--------+---------+
         |
         v
+--------+---------+
| Step 3: Format   |
| model: (current) |
+--------+---------+
         |
         v
+------------------+
| CancellationToken|  checked between steps
| .is_cancelled    |  callbacks fire on cancel
+------------------+
         |
         v
    Pipeline Result
```

### Code

```python
"""Cost-controlled pipeline with model fallback and cooperative cancellation."""

import asyncio

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import BudgetExceededError, CostTracker
from swarmline.agent.result import Result
from swarmline.retry import ModelFallbackChain
from swarmline.runtime.cancellation import CancellationToken
from swarmline.runtime.cost import CostBudget, CostTracker as RuntimeCostTracker, load_pricing


# --- 1. Budget and pricing setup ---

pricing = load_pricing()
budget = CostBudget(max_cost_usd=2.0, action_on_exceed="error")
cost_tracker = RuntimeCostTracker(budget=budget, pricing=pricing)


# --- 2. Model fallback chain: expensive -> cheap ---

fallback = ModelFallbackChain(
    models=[
        "claude-sonnet-4-20250514",  # best quality
        "gpt-4o-mini",               # cheaper alternative
        "gemini-2.0-flash",          # cheapest fallback
    ],
)


# --- 3. Pipeline steps ---

async def run_step(
    step_name: str,
    prompt: str,
    model: str,
    cancel_token: CancellationToken,
    middleware_tracker: CostTracker,
) -> tuple[str, str]:
    """Execute a single pipeline step. Returns (output_text, model_used).

    Tries the given model first. If budget exceeded, falls back to cheaper model.
    Checks cancellation token before executing.
    """
    if cancel_token.is_cancelled:
        return f"[{step_name}] CANCELLED", model

    current_model = model

    for _attempt in range(3):  # up to 3 fallback attempts
        try:
            config = AgentConfig(
                system_prompt=f"You are executing step: {step_name}. Be concise.",
                model=current_model,
                runtime="thin",
                middleware=(middleware_tracker,),
            )

            async with Agent(config) as agent:
                result = await agent.query(prompt)

            if result.ok:
                return result.text, current_model
            return f"[{step_name}] Error: {result.error}", current_model

        except BudgetExceededError:
            # Try a cheaper model
            next_model = fallback.next_model(current_model)
            if next_model is None:
                # No more fallbacks -- cancel the entire pipeline
                cancel_token.cancel()
                return f"[{step_name}] Budget exceeded, no cheaper model available", current_model
            print(f"  [{step_name}] Budget pressure, falling back: {current_model} -> {next_model}")
            current_model = next_model

    return f"[{step_name}] All fallbacks exhausted", current_model


async def run_pipeline(topic: str) -> dict[str, str]:
    """Execute a 3-step research pipeline with budget control."""

    cancel_token = CancellationToken()
    middleware_tracker = CostTracker(budget_usd=2.0)

    # Register cleanup callback
    cleanup_done = False

    def on_pipeline_cancel() -> None:
        nonlocal cleanup_done
        cleanup_done = True
        print("  [Pipeline] Cancellation triggered -- cleaning up resources")

    cancel_token.on_cancel(on_pipeline_cancel)

    results: dict[str, str] = {}
    current_model = "claude-sonnet-4-20250514"

    # Step 1: Research
    print("Step 1: Research")
    output, current_model = await run_step(
        "research",
        f"Research the topic: {topic}. List 3 key findings.",
        current_model,
        cancel_token,
        middleware_tracker,
    )
    results["research"] = output

    # Step 2: Analyze (uses model from step 1 -- may have degraded)
    print("Step 2: Analyze")
    output, current_model = await run_step(
        "analyze",
        f"Based on this research, provide analysis:\n{results['research'][:500]}",
        current_model,
        cancel_token,
        middleware_tracker,
    )
    results["analyze"] = output

    # Step 3: Format
    print("Step 3: Format")
    output, current_model = await run_step(
        "format",
        f"Format this analysis as a brief executive summary:\n{results['analyze'][:500]}",
        current_model,
        cancel_token,
        middleware_tracker,
    )
    results["format"] = output

    # Summary
    results["_metadata"] = (
        f"model_used={current_model}, "
        f"total_cost=${middleware_tracker.total_cost_usd:.4f}, "
        f"cancelled={cancel_token.is_cancelled}, "
        f"cleanup_ran={cleanup_done}"
    )

    return results


# --- 4. Budget monitoring (standalone) ---

def check_budget_health() -> str:
    """Check budget status using the runtime-level cost tracker."""
    status = cost_tracker.check_budget()
    remaining = (budget.max_cost_usd or 0) - cost_tracker.total_cost_usd
    return f"Status: {status}, spent: ${cost_tracker.total_cost_usd:.4f}, remaining: ${remaining:.4f}"


async def main() -> None:
    results = await run_pipeline("The impact of LLMs on software development")

    print("\n=== Pipeline Results ===")
    for step, output in results.items():
        if step.startswith("_"):
            print(f"\nMetadata: {output}")
        else:
            print(f"\n[{step}]\n{output[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Configuration Points

- **`CostBudget(max_cost_usd=2.0, action_on_exceed="error")`** -- hard budget cap; `"warn"` mode logs but continues
- **`ModelFallbackChain(models=[...])`** -- ordered from most expensive to cheapest; `next_model()` returns `None` when chain is exhausted
- **`CancellationToken`** -- cooperative: each step checks `is_cancelled` before running; `on_cancel()` callbacks handle cleanup
- **`CostTracker` (middleware)** -- accumulates cost across all Agent calls in the pipeline; raises `BudgetExceededError` when limit is hit
- **`RuntimeCostTracker`** -- lower-level tracker that works with `load_pricing()` for per-model token cost accounting

---

## Combining Patterns

These patterns compose naturally. A production system might combine all five:

```
                     +------------------+
                     | Cost Budget      |  (Pattern 5)
                     | CancellationToken|
                     +--------+---------+
                              |
                              v
                     +--------+---------+
                     | Orchestrator     |  (Pattern 3)
                     | AgentRegistry    |
                     | TaskQueue        |
                     +--------+---------+
                              |
              +---------------+---------------+
              |                               |
              v                               v
    +---------+----------+          +---------+----------+
    | Research Agent     |          | Review Agent       |
    | RAG + Memory       |          | Guardrails         |
    | (Pattern 2)        |          | (Pattern 1)        |
    +--------------------+          +--------------------+
              |                               |
              v                               v
    +---------+----------+          +---------+----------+
    | Conversation       |          | Conversation       |
    | SessionBackend     |          | SessionBackend     |
    | (Pattern 4)        |          | (Pattern 4)        |
    +--------------------+          +--------------------+
```

Each layer is independent and swappable. Start with the pattern that matches your immediate need, then add layers as requirements grow.
