"""Agent tools and the pipeline every tool call goes through (docs/PLAN.md §10.4, §10.7.1):

    1. Schema and arguments (Pydantic)      -> INVALID_ARGUMENTS back to the model
    2. Authorization and business rules     -> typed error back to the model
    3. Execution (domain / retrieval)

Errors go back to the model as data: {"ok": false, "error": {"code", "message", "details"}}.
The model never receives a raw exception. Tool results are DATA, not instructions.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.agent.llm.base import ToolCall, ToolSpec
from app.agent.llm.schema import strict_json_schema
from app.domain.errors import DomainError
from app.retrieval.embeddings import Embedder
from app.retrieval.search import SearchQuery, search
from app.retrieval.vocabulary import (
    SUBCATEGORIES,
    AvoidCase,
    Category,
    UseCase,
    use_case_categories,
)


@dataclass
class ToolContext:
    """What tools can use. There is no user_id here on purpose: when user tools arrive,
    the backend injects it from the token, never the model (AGENTS.md rule 4)."""

    session: Session
    embedder: Embedder | None


@dataclass
class ToolExecution:
    call: ToolCall
    result: dict[str, Any]  # what goes back to the model (already trimmed)
    is_error: bool
    latency_ms: int
    arguments: dict[str, Any] | None = None  # parsed arguments, for the logs
    product_ids: list[str] = field(default_factory=list)  # products the model has now "seen"


# --- search_products ------------------------------------------------------------------------


class SearchProductsArgs(BaseModel):
    """Strict-mode friendly: every field is required; "not set" is null or an empty list."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        description="What the user needs, ALWAYS IN ENGLISH (the catalog is in English). "
        "E.g. 'comfortable headphones for work and video calls'."
    )
    category: Category | None = Field(description="Set it whenever the need implies one.")
    subcategory: str | None = Field(description="Only together with category. See the list.")
    brand: str | None = Field(description="Only if the user asked for a brand.")
    min_price: float | None = Field(description="USD. Only if the user gave a minimum.")
    max_price: float | None = Field(description="USD. Only if the user gave a budget.")
    use_cases: list[UseCase] = Field(
        description="Uses that match the need. They rank, they do not filter. "
        "Pick the ones that exist in the chosen category (see the tool description)."
    )
    exclude_use_cases: list[AvoidCase] = Field(
        description="Uses the product must NOT be discouraged for (e.g. 'air travel')."
    )
    in_stock_only: bool = Field(
        description="true to recommend. false when the user names a specific product, "
        "so you can tell them whether it has stock."
    )
    limit: int | None = Field(description="1-10, null = 5.")


def _search_description(session: Session) -> str:
    subcategories = "; ".join(f"{cat}: {', '.join(subs)}" for cat, subs in SUBCATEGORIES.items())
    uses = "; ".join(
        f"{use} -> {', '.join(cats)}" for use, cats in use_case_categories(session).items()
    )
    return (
        "Search the MercaNova catalog (active products only). Returns up to `limit` products "
        "with CURRENT price and stock from the database, plus their key features and use cases. "
        "Use it for every recommendation, and to look up a product the user names.\n"
        f"Categories and subcategories: {subcategories}.\n"
        f"Use cases and the categories where they appear: {uses}."
    )


def _search_products(ctx: ToolContext, args: SearchProductsArgs) -> dict[str, Any]:
    # Stage 2: business rules (SearchQuery validates subcategory, price range, limits)
    query = SearchQuery(
        query=args.query,
        category=args.category,
        subcategory=args.subcategory,
        brand=args.brand,
        min_price=args.min_price,
        max_price=args.max_price,
        use_cases=args.use_cases,
        exclude_use_cases=args.exclude_use_cases,
        in_stock_only=args.in_stock_only,
        limit=args.limit or 5,
    )
    # Stage 3: execution
    result = search(ctx.session, query, ctx.embedder)
    return {
        "ok": True,
        "total_candidates": result.total_candidates,
        "products": [
            {
                "product_id": h.product_id,
                "name": h.name,
                "sku": h.sku,
                "brand": h.brand,
                "category": f"{h.category} > {h.subcategory}",
                "price": f"{h.currency} {h.current_price}",
                "list_price": f"{h.currency} {h.list_price}",
                "discount_percent": h.discount_percent,
                "stock": h.available,
                "stock_status": h.stock_status.value,
                "rating": str(h.rating) if h.rating is not None else None,
                "review_count": h.review_count,
                "summary": h.short_description,
                "key_features": h.key_features,
                "recommended_for": h.recommended_for,
                "not_recommended_for": h.not_recommended_for,
            }
            for h in result.hits
        ],
    }


# --- Registry ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    args_model: type[BaseModel]
    describe: Callable[[Session], str]
    run: Callable[[ToolContext, Any], dict[str, Any]]


TOOLS: dict[str, Tool] = {
    "search_products": Tool(
        "search_products", SearchProductsArgs, _search_description, _search_products
    ),
}


def tool_specs(session: Session) -> list[ToolSpec]:
    return [
        ToolSpec(t.name, t.describe(session), strict_json_schema(t.args_model))
        for t in TOOLS.values()
    ]


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return DomainError(code, message, details).to_dict()


def _validation_details(error: ValidationError) -> dict[str, Any]:
    return {
        "errors": [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in error.errors()
        ]
    }


def execute_tool(ctx: ToolContext, call: ToolCall) -> ToolExecution:
    """Run one tool call through the 3-stage pipeline. Unexpected errors (DB down, bugs)
    propagate: they are irrecoverable and stop the turn."""
    started = time.monotonic()

    def done(result: dict[str, Any], arguments: dict[str, Any] | None = None) -> ToolExecution:
        ids = [p["product_id"] for p in result.get("products", [])]
        return ToolExecution(
            call=call,
            result=result,
            is_error=not result.get("ok", False),
            latency_ms=int((time.monotonic() - started) * 1000),
            arguments=arguments,
            product_ids=ids,
        )

    tool = TOOLS.get(call.name)
    if tool is None:
        return done(_error("UNKNOWN_TOOL", f"There is no tool named '{call.name}'"))

    # Stage 1: schema and arguments
    try:
        raw = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return done(_error("INVALID_ARGUMENTS", "Arguments are not valid JSON"))
    try:
        args = tool.args_model.model_validate(raw)
    except ValidationError as error:
        return done(
            _error("INVALID_ARGUMENTS", "Invalid arguments", _validation_details(error)), raw
        )

    # Stages 2 and 3 (inside the tool): business rules, then execution
    try:
        return done(tool.run(ctx, args), raw)
    except ValidationError as error:
        return done(
            _error("INVALID_ARGUMENTS", "Invalid arguments", _validation_details(error)), raw
        )
    except DomainError as error:
        return done(error.to_dict(), raw)
