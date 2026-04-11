"""Shopping agent: finds best deals across stores with user clarification.

Demonstrates: WorkflowGraph HITL interrupts, parallel execution, @tool, structured output.
No API keys required -- uses mock data.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from pydantic import BaseModel, Field

from swarmline.agent.tool import tool
from swarmline.orchestration.workflow_graph import (
    END_NODE,
    WorkflowGraph,
    WorkflowInterrupt,
)
from swarmline.runtime.structured_output import validate_structured_output

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class ProductMatch(BaseModel):
    """A single product found in a store search."""

    store: str
    name: str
    price: float
    rating: float = Field(ge=0.0, le=5.0)
    review_count: int
    pros: list[str]
    cons: list[str]
    url: str


class ShoppingReport(BaseModel):
    """Final structured shopping recommendation."""

    query: str
    budget: float
    recommendations: list[ProductMatch]
    summary: str
    best_value_pick: str
    best_rated_pick: str


# ---------------------------------------------------------------------------
# Mock product database
# ---------------------------------------------------------------------------

_MOCK_PRODUCTS: dict[str, list[dict[str, Any]]] = {
    "amazon": [
        {
            "name": "Sony WH-1000XM5 Wireless Headphones",
            "price": 279.99,
            "rating": 4.8,
            "review_count": 14230,
            "pros": ["Best-in-class ANC", "30h battery", "USB-C charging"],
            "cons": ["Non-folding design", "Premium price"],
            "url": "https://amazon.com/dp/B09XS7JWHH",
        },
        {
            "name": "Bose QuietComfort 45",
            "price": 249.00,
            "rating": 4.6,
            "review_count": 9870,
            "pros": ["Comfortable fit", "Balanced sound", "Foldable"],
            "cons": ["No multipoint BT", "Older codec support"],
            "url": "https://amazon.com/dp/B098FKXT8L",
        },
        {
            "name": "Apple AirPods Max",
            "price": 479.00,
            "rating": 4.5,
            "review_count": 7210,
            "pros": ["Apple ecosystem", "Premium build", "Spatial audio"],
            "cons": ["Very expensive", "Heavy", "Lightning case"],
            "url": "https://amazon.com/dp/B08PZHYWJS",
        },
    ],
    "bestbuy": [
        {
            "name": "Sony WH-1000XM5 Wireless Headphones",
            "price": 299.99,
            "rating": 4.7,
            "review_count": 3210,
            "pros": ["Best-in-class ANC", "30h battery", "Speak-to-chat"],
            "cons": ["Non-folding", "Slightly over budget"],
            "url": "https://bestbuy.com/site/6505727.p",
        },
        {
            "name": "Jabra Evolve2 85",
            "price": 319.00,
            "rating": 4.4,
            "review_count": 1840,
            "pros": ["Professional ANC", "Dual microphone array", "All-day comfort"],
            "cons": ["Business-focused design", "No aptX"],
            "url": "https://bestbuy.com/site/6479629.p",
        },
    ],
    "newegg": [
        {
            "name": "Sennheiser Momentum 4 Wireless",
            "price": 229.95,
            "rating": 4.6,
            "review_count": 2100,
            "pros": ["60h battery", "Transparent hearing", "Compact fold"],
            "cons": ["Touch controls learning curve", "Neutral tuning not for bass lovers"],
            "url": "https://newegg.com/p/N82E16834O19001",
        },
        {
            "name": "Anker Soundcore Q45",
            "price": 59.99,
            "rating": 4.3,
            "review_count": 5600,
            "pros": ["Budget-friendly", "50h battery", "LDAC support"],
            "cons": ["Average ANC", "Plasticky build"],
            "url": "https://newegg.com/p/N82E16834596001",
        },
    ],
}


# ---------------------------------------------------------------------------
# @tool definitions (mock implementations)
# ---------------------------------------------------------------------------


@tool("search_store", description="Search a store for products matching a query.")
async def search_store(store: str, query: str, max_budget: float) -> str:
    """Search a specific store for products.

    Args:
        store: Store name (amazon, bestbuy, newegg).
        query: Search query string.
        max_budget: Maximum price to consider.
    """
    await asyncio.sleep(0.05)  # simulate network latency
    products = _MOCK_PRODUCTS.get(store, [])
    matches = [p for p in products if p["price"] <= max_budget]
    return json.dumps({"store": store, "matches": matches})


@tool("get_reviews", description="Fetch detailed reviews for a product.")
async def get_reviews(store: str, product_name: str) -> str:
    """Fetch review details for a specific product.

    Args:
        store: Store where the product is listed.
        product_name: Exact product name.
    """
    await asyncio.sleep(0.02)
    products = _MOCK_PRODUCTS.get(store, [])
    product = next((p for p in products if p["name"] == product_name), None)
    if not product:
        return json.dumps({"error": "product not found"})
    sample_reviews = [
        f"Great purchase, {product['pros'][0].lower()} really stands out.",
        f"Minor issue: {product['cons'][0].lower()} bothered me initially.",
        "Would definitely recommend to friends.",
    ]
    return json.dumps({"product": product_name, "reviews": sample_reviews})


@tool("get_specs", description="Fetch technical specifications for a product.")
async def get_specs(store: str, product_name: str) -> str:
    """Fetch technical specs for a specific product.

    Args:
        store: Store where the product is listed.
        product_name: Exact product name.
    """
    await asyncio.sleep(0.02)
    # Generate plausible headphone specs
    random.seed(hash(product_name) % 10000)
    specs = {
        "product": product_name,
        "driver_size_mm": random.choice([30, 40, 45]),
        "frequency_response_hz": "20–20,000",
        "impedance_ohm": random.choice([16, 32, 47]),
        "weight_g": random.choice([220, 250, 280, 310]),
        "bluetooth_version": random.choice(["5.0", "5.2", "5.3"]),
        "codecs": random.choice(["SBC, AAC", "SBC, AAC, LDAC", "SBC, AAC, aptX"]),
        "foldable": random.choice([True, False]),
    }
    return json.dumps(specs)


# ---------------------------------------------------------------------------
# Workflow node functions
# ---------------------------------------------------------------------------


async def wait_for_input(state: dict) -> dict:
    """Gate node — exists only to trigger a HITL interrupt.

    add_interrupt() fires BEFORE the node runs, so this node is skipped
    when resume() is called. The next node (clarify_requirements) runs
    with human_input merged into state.
    """
    return state


async def clarify_requirements(state: dict) -> dict:
    """Node that processes user preferences after HITL resume."""
    print(f"\n  [clarify_requirements] Query: '{state['query']}'")
    print(f"  [clarify_requirements] Budget: ${state['budget']:.2f}")
    preferences = state.get("clarified_preferences", "no special requirements")
    state["preferences_confirmed"] = True
    print(f"  [clarify_requirements] Preferences confirmed: {preferences}")
    return state


async def search_amazon(state: dict) -> dict:
    """Node 2a — search Amazon in parallel."""
    defn = search_store.__tool_definition__
    raw = await defn.handler(
        store="amazon",
        query=state["query"],
        max_budget=state["budget"],
    )
    data = json.loads(raw)
    state["results_amazon"] = data["matches"]
    print(f"  [search_amazon] Found {len(data['matches'])} products")
    return state


async def search_bestbuy(state: dict) -> dict:
    """Node 2b — search Best Buy in parallel."""
    defn = search_store.__tool_definition__
    raw = await defn.handler(
        store="bestbuy",
        query=state["query"],
        max_budget=state["budget"],
    )
    data = json.loads(raw)
    state["results_bestbuy"] = data["matches"]
    print(f"  [search_bestbuy] Found {len(data['matches'])} products")
    return state


async def search_newegg(state: dict) -> dict:
    """Node 2c — search Newegg in parallel."""
    defn = search_store.__tool_definition__
    raw = await defn.handler(
        store="newegg",
        query=state["query"],
        max_budget=state["budget"],
    )
    data = json.loads(raw)
    state["results_newegg"] = data["matches"]
    print(f"  [search_newegg] Found {len(data['matches'])} products")
    return state


async def fetch_details(state: dict) -> dict:
    """Node 3 — enrich top candidates with reviews and specs."""
    all_results: list[dict[str, Any]] = []
    for store_key in ("results_amazon", "results_bestbuy", "results_newegg"):
        store_name = store_key.replace("results_", "")
        for product in state.get(store_key, []):
            all_results.append({**product, "store": store_name})

    # Fetch details for up to 5 candidates concurrently
    candidates = all_results[:5]

    async def enrich(product: dict[str, Any]) -> dict[str, Any]:
        reviews_raw, specs_raw = await asyncio.gather(
            get_reviews.__tool_definition__.handler(
                store=product["store"], product_name=product["name"]
            ),
            get_specs.__tool_definition__.handler(
                store=product["store"], product_name=product["name"]
            ),
        )
        product["reviews_summary"] = json.loads(reviews_raw).get("reviews", [])
        product["specs"] = json.loads(specs_raw)
        return product

    enriched = await asyncio.gather(*[enrich(p) for p in candidates])
    state["enriched_candidates"] = list(enriched)
    print(f"  [fetch_details] Enriched {len(enriched)} candidates")
    return state


def _has_enough_matches(state: dict) -> str:
    """Conditional edge: route to 'compare' if ≥3 candidates, else 'refine_search'."""
    count = len(state.get("enriched_candidates", []))
    if count >= 3:
        return "compare"
    return "refine_search"


async def refine_search(state: dict) -> dict:
    """Node 4-alt — widen budget by 20% and merge additional newegg results."""
    original_budget = state["budget"]
    widened_budget = round(original_budget * 1.2, 2)
    print(f"  [refine_search] Only {len(state.get('enriched_candidates', []))} matches. "
          f"Widening budget ${original_budget} → ${widened_budget}")
    state["budget"] = widened_budget

    defn = search_store.__tool_definition__
    raw = await defn.handler(
        store="newegg",
        query=state["query"],
        max_budget=widened_budget,
    )
    extra = json.loads(raw)["matches"]
    existing = state.get("results_newegg", [])
    names_seen = {p["name"] for p in existing}
    state["results_newegg"] = existing + [p for p in extra if p["name"] not in names_seen]
    state["search_refined"] = True
    return state


async def compare(state: dict) -> dict:
    """Node 5 — rank candidates and pick top 3 by value and rating."""
    candidates: list[dict[str, Any]] = state.get("enriched_candidates", [])
    preferences: str = state.get("clarified_preferences", "")

    # Score: normalise price (lower = better) + weight rating
    max_price = max(c["price"] for c in candidates) if candidates else 1.0
    for c in candidates:
        price_score = 1.0 - (c["price"] / max_price)   # 0..1, higher = cheaper
        rating_score = c["rating"] / 5.0                 # 0..1
        c["_score"] = 0.4 * price_score + 0.6 * rating_score

    ranked = sorted(candidates, key=lambda c: c["_score"], reverse=True)
    top3 = ranked[:3]

    print(f"  [compare] Top candidates (preferences: '{preferences}'):")
    for i, c in enumerate(top3, 1):
        print(f"    {i}. {c['name']} @ ${c['price']:.2f} | "
              f"rating={c['rating']} | score={c['_score']:.3f}")

    state["top_candidates"] = top3
    return state


async def recommend(state: dict) -> dict:
    """Node 6 — produce a ShoppingReport as structured output."""
    top: list[dict[str, Any]] = state.get("top_candidates", [])

    matches = [
        ProductMatch(
            store=c["store"],
            name=c["name"],
            price=c["price"],
            rating=c["rating"],
            review_count=c["review_count"],
            pros=c["pros"],
            cons=c["cons"],
            url=c["url"],
        )
        for c in top
    ]

    best_value = min(matches, key=lambda m: m.price)
    best_rated = max(matches, key=lambda m: m.rating)

    report_json = ShoppingReport(
        query=state["query"],
        budget=state["budget"],
        recommendations=matches,
        summary=(
            f"Found {len(matches)} strong options for '{state['query']}' "
            f"within ${state['budget']:.2f}. "
            f"Best value: {best_value.name} at ${best_value.price:.2f}. "
            f"Highest rated: {best_rated.name} ({best_rated.rating}/5)."
        ),
        best_value_pick=best_value.name,
        best_rated_pick=best_rated.name,
    ).model_dump_json()

    # Round-trip through validate_structured_output to confirm parsing works
    report = validate_structured_output(report_json, ShoppingReport)
    state["report"] = report
    return state


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_shopping_graph() -> WorkflowGraph:
    """Assemble the shopping workflow graph."""
    graph = WorkflowGraph("shopping-agent")

    # Nodes
    graph.add_node("wait_for_input", wait_for_input)
    graph.add_node("clarify_requirements", clarify_requirements)
    graph.add_node("search_amazon", search_amazon)
    graph.add_node("search_bestbuy", search_bestbuy)
    graph.add_node("search_newegg", search_newegg)
    graph.add_node("fetch_details", fetch_details)
    graph.add_node("refine_search", refine_search)
    graph.add_node("compare", compare)
    graph.add_node("recommend", recommend)

    # Entry: gate node for HITL
    graph.set_entry("wait_for_input")

    # HITL: pause BEFORE wait_for_input runs.
    # resume() skips wait_for_input → goes to clarify_requirements with human_input merged.
    graph.add_interrupt("wait_for_input")
    graph.add_edge("wait_for_input", "clarify_requirements")

    # After requirements: fan out to parallel store searches
    # add_parallel creates internal entry "__parallel_search_amazon_search_bestbuy_search_newegg"
    parallel_entry = "__parallel_search_amazon_search_bestbuy_search_newegg"
    graph.add_parallel(["search_amazon", "search_bestbuy", "search_newegg"], then="fetch_details")
    graph.add_edge("clarify_requirements", parallel_entry)

    # After parallel searches: fetch details
    graph.add_edge("fetch_details", "compare")  # default; overridden by conditional

    # Conditional: enough matches → compare, else → refine_search → fetch_details
    graph.add_conditional_edge("fetch_details", _has_enough_matches)
    graph.add_edge("refine_search", "fetch_details")
    graph.set_max_loops("refine_search", max_loops=1)  # widen budget at most once

    # Linear tail
    graph.add_edge("compare", "recommend")
    graph.add_edge("recommend", END_NODE)

    return graph


# ---------------------------------------------------------------------------
# Main — end-to-end demo
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("Shopping Agent — swarmline WorkflowGraph demo")
    print("=" * 60)

    graph = build_shopping_graph()

    # Print the graph topology
    print("\n--- Workflow topology (Mermaid) ---")
    print(graph.to_mermaid())
    print()

    # Initial state: the user's raw query
    initial_state: dict[str, Any] = {
        "query": "noise-cancelling wireless headphones",
        "budget": 300.0,
    }

    # --- Phase 1: attempt execution, hit HITL interrupt ---
    print("--- Phase 1: starting workflow (expect HITL interrupt) ---")
    interrupt: WorkflowInterrupt | None = None
    try:
        await graph.execute(initial_state)
    except WorkflowInterrupt as exc:
        interrupt = exc
        print(f"\n  >> Workflow paused at '{exc.node_id}'")
        print(f"     State: query='{exc.state['query']}', budget=${exc.state['budget']}")

    assert interrupt is not None, "Expected a WorkflowInterrupt from wait_for_input"

    # --- Phase 2: simulate human input, resume ---
    print("\n--- Phase 2: human provides preferences, resuming ---")
    human_preferences = "prefer Sony or Sennheiser, need 30h+ battery, no Lightning ports"
    print(f"  Human input: '{human_preferences}'")

    final_state = await graph.resume(
        interrupt,
        human_input={"clarified_preferences": human_preferences},
    )

    # --- Phase 3: display structured report ---
    report: ShoppingReport = final_state["report"]

    print("\n" + "=" * 60)
    print("SHOPPING REPORT")
    print("=" * 60)
    print(f"Query      : {report.query}")
    print(f"Budget     : ${report.budget:.2f}")
    print(f"Summary    : {report.summary}")
    print(f"Best value : {report.best_value_pick}")
    print(f"Best rated : {report.best_rated_pick}")
    print()

    for i, match in enumerate(report.recommendations, 1):
        print(f"  Recommendation #{i}")
        print(f"    Store    : {match.store}")
        print(f"    Product  : {match.name}")
        print(f"    Price    : ${match.price:.2f}")
        print(f"    Rating   : {match.rating}/5 ({match.review_count:,} reviews)")
        print(f"    Pros     : {', '.join(match.pros)}")
        print(f"    Cons     : {', '.join(match.cons)}")
        print(f"    URL      : {match.url}")
        print()

    # Verify Pydantic round-trip
    json_output = report.model_dump_json(indent=2)
    reparsed = validate_structured_output(json_output, ShoppingReport)
    assert reparsed.best_value_pick == report.best_value_pick
    print("Structured output round-trip: OK")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
