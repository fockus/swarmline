"""Workflow graph: declarative execution with conditions, loops, and HITL.

Demonstrates: WorkflowGraph, add_node, add_edge, add_conditional_edge,
add_parallel, set_max_loops, add_interrupt, InMemoryCheckpoint, to_mermaid.
No API keys required.
"""

import asyncio

from swarmline.orchestration.workflow_graph import (
    END_NODE,
    InMemoryCheckpoint,
    WorkflowGraph,
    WorkflowInterrupt,
)


# --- Node functions (State -> State) ---

async def research(state: dict) -> dict:
    """Gather information."""
    state["research"] = f"Found 3 sources about '{state['topic']}'"
    print(f"  [research] {state['research']}")
    return state


async def analyze(state: dict) -> dict:
    """Analyze findings."""
    state["analysis"] = "Key insight: topic is trending"
    print(f"  [analyze] {state['analysis']}")
    return state


async def draft(state: dict) -> dict:
    """Write a draft."""
    state["draft"] = f"Draft about {state['topic']}: {state.get('analysis', '')}"
    state.setdefault("revision", 0)
    state["revision"] += 1
    print(f"  [draft] Revision {state['revision']}")
    return state


async def review(state: dict) -> dict:
    """Review the draft. Approve after 2 revisions."""
    if state.get("revision", 0) >= 2:
        state["review_status"] = "approved"
    else:
        state["review_status"] = "needs_revision"
    print(f"  [review] Status: {state['review_status']}")
    return state


def review_decision(state: dict) -> str:
    """Route based on review outcome."""
    if state.get("review_status") == "approved":
        return "publish"
    return "draft"  # loop back


async def publish(state: dict) -> dict:
    """Publish the final content."""
    state["published"] = True
    print("  [publish] Content published!")
    return state


# --- Parallel tasks ---

async def check_plagiarism(state: dict) -> dict:
    state["plagiarism_check"] = "clear"
    print("  [plagiarism] Clear")
    return state


async def check_grammar(state: dict) -> dict:
    state["grammar_check"] = "passed"
    print("  [grammar] Passed")
    return state


async def main() -> None:
    # === 1. Linear graph ===
    print("=== Linear Graph ===")
    linear = WorkflowGraph("linear-pipeline")
    linear.add_node("research", research)
    linear.add_node("analyze", analyze)
    linear.add_node("draft", draft)
    linear.add_edge("research", "analyze")
    linear.add_edge("analyze", "draft")
    linear.add_edge("draft", END_NODE)
    linear.set_entry("research")

    result = await linear.execute({"topic": "AI agents"})
    print(f"Result keys: {list(result.keys())}\n")

    # === 2. Conditional branching with loop ===
    print("=== Conditional Loop Graph ===")
    loop_graph = WorkflowGraph("review-loop")
    loop_graph.add_node("draft", draft)
    loop_graph.add_node("review", review)
    loop_graph.add_node("publish", publish)
    loop_graph.add_edge("draft", "review")
    loop_graph.add_conditional_edge("review", review_decision)
    loop_graph.add_edge("publish", END_NODE)
    loop_graph.set_entry("draft")
    loop_graph.set_max_loops("draft", max_loops=5)

    result = await loop_graph.execute({"topic": "Swarmline framework"})
    print(f"Final revision: {result.get('revision')}, published: {result.get('published')}\n")

    # === 3. Parallel execution ===
    print("=== Parallel Execution ===")
    parallel_graph = WorkflowGraph("quality-checks")
    parallel_graph.add_node("draft", draft)
    parallel_graph.add_node("check_plagiarism", check_plagiarism)
    parallel_graph.add_node("check_grammar", check_grammar)
    parallel_graph.add_node("publish", publish)
    parallel_graph.set_entry("draft")
    # add_parallel creates internal entry node "__parallel_check_plagiarism_check_grammar"
    parallel_graph.add_parallel(["check_plagiarism", "check_grammar"], then="publish")
    # Connect draft to the parallel entry node (internal ID from add_parallel)
    parallel_graph.add_edge("draft", "__parallel_check_plagiarism_check_grammar")
    parallel_graph.add_edge("publish", END_NODE)

    result = await parallel_graph.execute({"topic": "Parallel workflows"})
    print(f"Plagiarism: {result.get('plagiarism_check')}, Grammar: {result.get('grammar_check')}\n")

    # === 4. Checkpoint (crash recovery) ===
    print("=== Checkpoint ===")
    checkpoint = InMemoryCheckpoint()
    checkpoint.save("run-1", "analyze", {"topic": "AI", "research": "done"})
    saved = checkpoint.load("run-1")
    print(f"Saved checkpoint: node={saved[0] if saved else 'none'}")
    checkpoint.clear("run-1")

    # === 5. Mermaid visualization ===
    print("\n=== Mermaid Diagram ===")
    print(loop_graph.to_mermaid())

    # === 6. HITL interrupt (human-in-the-loop) ===
    # Note: add_interrupt() fires BEFORE the node executes.
    # resume() skips the interrupted node and continues to the next one.
    # Strategy: draft runs first, then a "human_review" gate node is the
    # interrupt point. Since resume() skips human_review, execution continues
    # directly to publish — the gate node exists only to pause the workflow.
    print("=== HITL Interrupt ===")

    async def human_review(state: dict) -> dict:
        """Gate node for human review — only runs if not interrupted."""
        print("  [human_review] Reviewing...")
        return state

    hitl_graph = WorkflowGraph("hitl-demo")
    hitl_graph.add_node("draft", draft)
    hitl_graph.add_node("human_review", human_review)
    hitl_graph.add_node("publish", publish)
    hitl_graph.set_entry("draft")
    hitl_graph.add_edge("draft", "human_review")
    hitl_graph.add_interrupt("human_review")  # pause BEFORE human_review for human input
    hitl_graph.add_edge("human_review", "publish")
    hitl_graph.add_edge("publish", END_NODE)

    try:
        await hitl_graph.execute({"topic": "HITL demo"})
    except WorkflowInterrupt as interrupt:
        print(f"  Interrupted at node: {interrupt.node_id}")
        print(f"  State so far: draft revision={interrupt.state.get('revision')}")
        # Resume with human input — skips human_review, goes to publish
        final = await hitl_graph.resume(interrupt, human_input={"human_feedback": "Looks good!"})
        print(f"  Resumed, published: {final.get('published')}")


if __name__ == "__main__":
    asyncio.run(main())
