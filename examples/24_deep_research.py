"""Deep Research agent: multi-step research with source aggregation.

Demonstrates: WorkflowGraph, @tool, structured output, RAG pipeline.
Runs a mock pipeline by default and supports ``--live`` with
``ANTHROPIC_API_KEY`` or ``OPENROUTER_API_KEY``.

Pipeline:
  decompose → search → aggregate → synthesize → report
                 ↑____________|
         (loop back if findings are thin, max 2 passes)

Architecture notes:
- WorkflowGraph drives the multi-step execution declaratively
- @tool decorators define mock search backends with auto-inferred JSON Schema
- Pydantic models enforce structured output at every stage boundary
- SimpleRetriever + RagInputFilter aggregate cross-source evidence via RAG
- The synthesis node consumes RAG-enriched context to produce a typed report
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from typing import Any

from pydantic import BaseModel, Field

from swarmline.agent.tool import tool
from swarmline.orchestration.workflow_graph import END_NODE, WorkflowGraph
from swarmline.rag import Document, RagInputFilter, SimpleRetriever
from swarmline.runtime.structured_output import (
    extract_pydantic_schema,
    validate_structured_output,
)
from swarmline.runtime.types import Message

# ---------------------------------------------------------------------------
# Domain models — structured output contracts
# ---------------------------------------------------------------------------


class SubQueries(BaseModel):
    """Decomposition of the main research question into focused sub-queries."""

    question: str = Field(description="Original research question")
    sub_queries: list[str] = Field(
        description="3-5 focused sub-queries to investigate",
        min_length=2,
        max_length=5,
    )
    rationale: str = Field(description="Why these sub-queries cover the topic well")


class SearchResult(BaseModel):
    """A single search result from any source."""

    query: str
    source: str
    title: str
    snippet: str
    relevance: float = Field(ge=0.0, le=1.0)


class ResearchReport(BaseModel):
    """Final structured research report."""

    question: str
    executive_summary: str
    key_findings: list[str] = Field(min_length=1)
    sources_consulted: list[str]
    confidence: str = Field(description="low | medium | high")
    limitations: str


# ---------------------------------------------------------------------------
# Mock search tools  (@tool decorator — auto-infers JSON Schema)
# ---------------------------------------------------------------------------


@tool("web_search", description="Search the web for current information on a topic.")
async def web_search(query: str, max_results: int = 3) -> str:
    """Search the web for current information on a topic.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.
    """
    # Mock data keyed loosely to common research domains
    mock_db: dict[str, list[dict[str, str]]] = {
        "climate": [
            {"title": "Global Temperature Records 2024", "snippet": "2024 was the hottest year on record, with global average temperatures 1.5°C above pre-industrial levels.", "url": "climate-institute.org/records-2024"},
            {"title": "Arctic Ice Loss Acceleration", "snippet": "Arctic sea ice extent hit a new summer minimum in 2024, declining 13% per decade since 1979.", "url": "nsidc.org/arctic-2024"},
            {"title": "Carbon Capture Breakthroughs", "snippet": "Direct air capture costs fell 40% in 2024 as new electrochemical methods proved scalable.", "url": "carbonbrief.org/dac-2024"},
        ],
        "ai": [
            {"title": "LLM Scaling Laws Revisited", "snippet": "Recent research shows diminishing returns on pure parameter scaling; data quality and architecture matter more at frontier scale.", "url": "arxiv.org/scaling-2024"},
            {"title": "Agent Frameworks Adoption Survey", "snippet": "Enterprise adoption of multi-agent systems grew 3× in 2024, with reliability and cost as primary concerns.", "url": "mckinsey.com/ai-agents-2024"},
            {"title": "Reasoning Models Benchmark", "snippet": "Chain-of-thought models achieve 94% on MATH, but hallucination rates remain 8-12% on open-ended factual questions.", "url": "openai.com/o3-eval"},
        ],
        "default": [
            {"title": f"Overview: {query}", "snippet": f"Comprehensive analysis of {query} reveals multiple contributing factors and ongoing research directions.", "url": f"encyclopedia.org/{query.replace(' ', '-')}"},
            {"title": f"Recent Developments in {query}", "snippet": f"The field of {query} has seen significant progress in the past 12 months, with several key papers published.", "url": f"scholar.google.com/search?q={query.replace(' ', '+')}"},
        ],
    }

    # Pick mock results based on query keywords
    key = "default"
    q_lower = query.lower()
    for domain_key in mock_db:
        if domain_key != "default" and domain_key in q_lower:
            key = domain_key
            break

    results = mock_db[key][:max_results]
    return json.dumps(results, indent=2)


@tool("academic_search", description="Search academic databases for peer-reviewed papers.")
async def academic_search(query: str, year_from: int = 2020) -> str:
    """Search academic databases for peer-reviewed papers.

    Args:
        query: Academic search query.
        year_from: Earliest publication year to include.
    """
    # Mock academic results
    mock_papers = [
        {
            "title": f"Systematic Review: {query}",
            "authors": "Zhang et al.",
            "year": 2024,
            "journal": "Nature",
            "abstract": f"This meta-analysis of 47 studies on {query} finds consistent evidence for three primary mechanisms, with effect sizes ranging from moderate to large (d=0.4–1.2).",
            "citations": 312,
            "doi": f"10.1038/nature.{abs(hash(query)) % 99999}",
        },
        {
            "title": f"Longitudinal Study on {query} Dynamics",
            "authors": "Müller & Okonkwo",
            "year": 2023,
            "journal": "Science",
            "abstract": f"Ten-year longitudinal data reveals non-linear trends in {query}, suggesting phase-transition dynamics previously unmodelled.",
            "citations": 89,
            "doi": f"10.1126/science.{abs(hash(query + 'b')) % 99999}",
        },
    ]

    filtered = [p for p in mock_papers if p["year"] >= year_from]
    return json.dumps(filtered, indent=2)


# ---------------------------------------------------------------------------
# Workflow node functions  (State → State)
# ---------------------------------------------------------------------------

MAX_SEARCH_LOOPS = 2  # max re-search passes when findings are thin


async def decompose(state: dict[str, Any]) -> dict[str, Any]:
    """Break the research question into focused sub-queries (structured output)."""
    question = state["question"]

    print(f"\n[decompose] Analysing: '{question}'")

    # In production: LLM call with output_type=SubQueries.
    # Here we mock the structured output using validate_structured_output
    # to show the exact same code path that a real Agent would exercise.
    mock_llm_response = json.dumps(
        {
            "question": question,
            "sub_queries": [
                f"What are the primary causes of {question}?",
                f"What does recent research say about {question}?",
                f"What are the main impacts or consequences of {question}?",
                f"What solutions or mitigation strategies exist for {question}?",
            ],
            "rationale": (
                "These four angles (causes, evidence, impact, solutions) provide "
                "systematic coverage of any research topic."
            ),
        }
    )

    sub_queries = validate_structured_output(mock_llm_response, SubQueries)
    print(f"[decompose] Generated {len(sub_queries.sub_queries)} sub-queries")
    for i, sq in enumerate(sub_queries.sub_queries, 1):
        print(f"  {i}. {sq}")

    state["sub_queries"] = sub_queries
    state["search_pass"] = 0
    state["raw_results"] = []
    return state


async def search(state: dict[str, Any]) -> dict[str, Any]:
    """Execute all sub-queries across web and academic search tools."""
    sub_queries: SubQueries = state["sub_queries"]
    current_pass = state.get("search_pass", 0) + 1
    state["search_pass"] = current_pass

    print(f"\n[search] Pass {current_pass}/{MAX_SEARCH_LOOPS}")

    all_results: list[dict[str, Any]] = list(state.get("raw_results", []))

    for sq in sub_queries.sub_queries:
        print(f"  Searching: '{sq[:60]}...'")

        # Call both tools (in production: Agent routes these via ToolSpec)
        web_defn = web_search.__tool_definition__
        academic_defn = academic_search.__tool_definition__

        web_raw = await web_defn.handler(query=sq, max_results=2)
        academic_raw = await academic_defn.handler(query=sq, year_from=2022)

        web_items: list[dict[str, Any]] = json.loads(web_raw)
        academic_items: list[dict[str, Any]] = json.loads(academic_raw)

        for item in web_items:
            all_results.append(
                SearchResult(
                    query=sq,
                    source="web",
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    relevance=0.75,
                ).model_dump()
            )

        for item in academic_items:
            all_results.append(
                SearchResult(
                    query=sq,
                    source="academic",
                    title=item.get("title", ""),
                    snippet=item.get("abstract", ""),
                    relevance=0.90,  # academic sources weighted higher
                ).model_dump()
            )

    state["raw_results"] = all_results
    print(f"[search] Collected {len(all_results)} total results")
    return state


def should_refine(state: dict[str, Any]) -> str:
    """Conditional edge: loop back to search if findings are thin."""
    results: list[dict[str, Any]] = state.get("raw_results", [])
    search_pass: int = state.get("search_pass", 0)

    # Thin = fewer than 6 results after first pass; give one more chance
    if len(results) < 6 and search_pass < MAX_SEARCH_LOOPS:
        print(f"[route] Only {len(results)} results — refining queries (pass {search_pass + 1})")
        return "search"

    print(f"[route] {len(results)} results — sufficient, proceeding to aggregate")
    return "aggregate"


async def aggregate(state: dict[str, Any]) -> dict[str, Any]:
    """Build a SimpleRetriever corpus from collected results, then RAG-retrieve."""
    raw_results: list[dict[str, Any]] = state["raw_results"]
    question: str = state["question"]

    print(f"\n[aggregate] Building RAG index from {len(raw_results)} documents...")

    # Build Document corpus from all collected snippets
    documents = [
        Document(
            content=r["snippet"],
            metadata={"source": r["source"], "title": r["title"], "query": r["query"]},
        )
        for r in raw_results
        if r.get("snippet")
    ]

    retriever = SimpleRetriever(documents=documents)

    # Retrieve most relevant documents for the original question
    top_docs = await retriever.retrieve(question, top_k=8)
    print(f"[aggregate] Retrieved {len(top_docs)} top-scored documents")

    # RagInputFilter: produce the enriched system prompt a real LLM would receive
    rag_filter = RagInputFilter(retriever=retriever, top_k=6)
    messages = [Message(role="user", content=question)]
    _, enriched_prompt = await rag_filter.filter(
        messages, "You are a rigorous research analyst. Synthesize findings accurately."
    )

    state["top_documents"] = top_docs
    state["enriched_system_prompt"] = enriched_prompt
    state["retriever"] = retriever
    return state


async def synthesize(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesize findings into a structured ResearchReport (structured output)."""
    question: str = state["question"]
    top_docs: list[Document] = state["top_documents"]
    raw_results: list[dict[str, Any]] = state["raw_results"]

    print("\n[synthesize] Generating structured report...")

    # Show the JSON Schema that would be sent to the LLM
    report_schema = extract_pydantic_schema(ResearchReport)
    print(f"[synthesize] Report schema fields: {list(report_schema.get('properties', {}).keys())}")

    # Aggregate key findings from top retrieved documents
    key_findings = [
        textwrap.shorten(doc.content, width=120, placeholder="...")
        for doc in top_docs[:4]
    ]

    # Collect unique source names
    sources = sorted({r["source"] for r in raw_results})
    source_labels = [f"{s.capitalize()} search ({sum(1 for r in raw_results if r['source'] == s)} results)" for s in sources]

    # In production: LLM call with enriched_system_prompt + output_type=ResearchReport.
    # Here we build the mock JSON and validate it through the same code path.
    mock_report_json = json.dumps(
        {
            "question": question,
            "executive_summary": (
                f"Research into '{question}' reveals a well-documented topic with "
                f"consistent findings across {len(raw_results)} sources. "
                "The evidence base includes both empirical studies and recent "
                "web-accessible material, providing a comprehensive view."
            ),
            "key_findings": key_findings or [
                "Multiple mechanisms contribute to the phenomenon",
                "Recent studies confirm earlier theoretical models",
                "Actionable interventions exist at multiple scales",
            ],
            "sources_consulted": source_labels,
            "confidence": "medium",
            "limitations": (
                "This report uses a mock search backend. "
                "Real deployment would query live APIs and apply LLM synthesis "
                "with full citation tracking."
            ),
        }
    )

    report = validate_structured_output(mock_report_json, ResearchReport)
    state["report"] = report
    return state


async def report(state: dict[str, Any]) -> dict[str, Any]:
    """Render the final research report to stdout."""
    r: ResearchReport = state["report"]

    width = 70
    separator = "=" * width

    print(f"\n{separator}")
    print("DEEP RESEARCH REPORT".center(width))
    print(separator)
    print(f"\nQuestion: {r.question}")
    print(f"Confidence: {r.confidence.upper()}")
    print("\n--- Executive Summary ---")
    print(textwrap.fill(r.executive_summary, width=width))
    print("\n--- Key Findings ---")
    for i, finding in enumerate(r.key_findings, 1):
        wrapped = textwrap.fill(finding, width=width - 5, initial_indent=f"  {i}. ", subsequent_indent="     ")
        print(wrapped)
    print("\n--- Sources Consulted ---")
    for source in r.sources_consulted:
        print(f"  - {source}")
    print("\n--- Limitations ---")
    print(textwrap.fill(r.limitations, width=width))
    print(f"\n{separator}\n")

    state["done"] = True
    return state


# ---------------------------------------------------------------------------
# Workflow assembly
# ---------------------------------------------------------------------------


def build_research_graph() -> WorkflowGraph:
    """Assemble the Deep Research pipeline as a WorkflowGraph.

    Graph topology:
        decompose → search → [aggregate | search]  (conditional)
                    aggregate → synthesize → report → END
    """
    g = WorkflowGraph("deep-research")

    # Register nodes
    g.add_node("decompose", decompose)
    g.add_node("search", search)
    g.add_node("aggregate", aggregate)
    g.add_node("synthesize", synthesize)
    g.add_node("report", report)

    # Edges
    g.add_edge("decompose", "search")
    # After search: conditional — refine or proceed
    g.add_conditional_edge("search", should_refine)
    g.add_edge("aggregate", "synthesize")
    g.add_edge("synthesize", "report")
    g.add_edge("report", END_NODE)

    # Guard against infinite re-search loop (max 2 passes through search node)
    g.set_max_loops("search", max_loops=MAX_SEARCH_LOOPS)

    g.set_entry("decompose")
    return g


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    question = os.environ.get(
        "RESEARCH_QUESTION",
        "What are the causes and consequences of climate change?",
    )

    print("Deep Research Agent — Mock Pipeline")
    print(f"Question: {question}")
    print()
    print("[info] Mermaid graph diagram:")
    g = build_research_graph()
    print(g.to_mermaid())

    # Run the full pipeline
    final_state = await g.execute({"question": question})
    print(f"[done] Pipeline complete. State keys: {sorted(final_state.keys())}")


def _resolve_live_model() -> str:
    """Select live model/provider based on available credentials."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "sonnet"

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        os.environ["OPENAI_API_KEY"] = openrouter_key
        return "openrouter:anthropic/claude-3.5-haiku"

    raise SystemExit("Either ANTHROPIC_API_KEY or OPENROUTER_API_KEY is required for --live mode")


async def live(question: str) -> None:
    """Run the same scenario through a real thin runtime."""
    from swarmline import Agent, AgentConfig

    model = _resolve_live_model()

    print("Deep Research Agent — Live Mode")
    print(f"Question: {question}")

    agent = Agent(
        AgentConfig(
            system_prompt=(
                "You are a deep research agent. When asked a question, "
                "break it into sub-queries, search multiple sources, and "
                "synthesize a comprehensive report with citations."
            ),
            runtime="thin",
            model=model,
            tools=(
                web_search.__tool_definition__,
                academic_search.__tool_definition__,
            ),
            output_format=extract_pydantic_schema(ResearchReport),
        )
    )

    result = await agent.query(question)
    if result.structured_output:
        report_obj = ResearchReport.model_validate(result.structured_output)
        print(f"Confidence: {report_obj.confidence}")
        print(f"Findings: {len(report_obj.key_findings)}")
        print("Executive summary:")
        print(textwrap.fill(report_obj.executive_summary, width=70))
        return

    print(result.text)


if __name__ == "__main__":
    question = os.environ.get(
        "RESEARCH_QUESTION",
        "What are the causes and consequences of climate change?",
    )
    if "--live" in sys.argv:
        asyncio.run(live(question))
    else:
        asyncio.run(main())
