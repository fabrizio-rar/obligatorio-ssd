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
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.agent.llm.base import ToolCall, ToolSpec
from app.agent.llm.schema import strict_json_schema
from app.agent.response_schema import PendingAction, UiAction
from app.domain import cart
from app.domain.cart import CartView
from app.domain.catalog import (
    ProductDetail,
    ProductStatus,
    find_products_by_name,
    get_product_detail,
)
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
    """What tools can use. `user_id` comes from the session token: it is NEVER a tool
    parameter, so the model cannot touch someone else's cart (AGENTS.md rule 4)."""

    session: Session
    embedder: Embedder | None
    user_id: int
    # Products that came back from a tool in this conversation (the loop keeps it updated).
    # Level-2 actions only accept these: the model cannot add an ID it made up.
    seen_product_ids: set[str] = field(default_factory=set)


@dataclass
class ToolExecution:
    call: ToolCall
    result: dict[str, Any]  # what goes back to the model (already trimmed)
    is_error: bool
    latency_ms: int
    arguments: dict[str, Any] | None = None  # parsed arguments, for the logs
    product_ids: list[str] = field(default_factory=list)  # products the model has now "seen"
    ui_actions: list[UiAction] = field(default_factory=list)
    pending_confirmation: PendingAction | None = None  # set -> the turn stops here


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool returns: the (trimmed) result for the model, and the products the
    answer is now allowed to show as cards. Each tool decides it explicitly."""

    result: dict[str, Any]
    product_ids: list[str] = field(default_factory=list)
    # Filled by the backend from what the tool did, never by the model (§10.6)
    ui_actions: list[UiAction] = field(default_factory=list)
    pending_confirmation: PendingAction | None = None


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


def _search_products(ctx: ToolContext, args: SearchProductsArgs) -> ToolOutcome:
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
    data = {
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
    return ToolOutcome(data, [h.product_id for h in result.hits])


# --- get_product ------------------------------------------------------------------------------


class GetProductArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = Field(
        description="Exact product ID (e.g. MN-HDP-0004), if it came from a previous tool result."
    )
    name: str | None = Field(
        description="Product name as the user wrote it (e.g. 'Cedar Air 243'), when you do not "
        "have its ID. Pass exactly one of product_id or name."
    )

    @model_validator(mode="after")
    def exactly_one(self) -> Self:
        if (self.product_id is None) == (self.name is None):
            raise ValueError("pass exactly one of product_id or name")
        return self


GET_PRODUCT_DESCRIPTION = (
    "Full sheet of ONE specific product: all specs, warranty, return days, dimensions, "
    "CURRENT price and stock PER WAREHOUSE (for 'can I pick it up in Colonia?'). "
    "Use it when the user names a product or asks about a specific one. "
    "It also finds products that are no longer sold: status 'discontinued' (no price or "
    "stock: do not offer it; offer to search alternatives in its category). "
    "If several products share the name, it returns the matches so you can ask which one."
)


def _detail_for_model(detail: ProductDetail) -> dict[str, Any]:
    data = detail.model_dump(mode="json", exclude_none=True)
    if detail.status == ProductStatus.DISCONTINUED:
        return data
    data["price"] = f"{detail.currency} {detail.current_price}"
    data["list_price"] = f"{detail.currency} {detail.list_price}"
    for key in ("currency", "current_price"):
        data.pop(key, None)
    # Compact specs: "Battery Life: 28 h" (N/D kept: the model must not infer them)
    data["specs"] = [f"{spec.name}: {spec.value}" for spec in detail.specs]
    return data


def _get_product(ctx: ToolContext, args: GetProductArgs) -> ToolOutcome:
    if args.product_id is not None:
        detail = get_product_detail(ctx.session, args.product_id.strip())
    else:
        matches = find_products_by_name(ctx.session, args.name)
        if not matches:
            raise DomainError(
                "NOT_FOUND",
                f"No product named '{args.name}'",
                {"hint": "Try search_products to find similar products"},
            )
        if len(matches) > 1:
            data = {
                "ok": True,
                "ambiguous": True,
                "matches": [
                    {
                        **m.model_dump(exclude={"active"}),
                        "status": "available" if m.active else "discontinued",
                    }
                    for m in matches
                ],
            }
            return ToolOutcome(data, [m.product_id for m in matches if m.active])
        detail = get_product_detail(ctx.session, matches[0].product_id)

    data = {"ok": True, "product": _detail_for_model(detail)}
    # A discontinued product can never become a card
    seen = [] if detail.status == ProductStatus.DISCONTINUED else [detail.product_id]
    return ToolOutcome(data, seen)


# --- Cart tools (docs/PLAN.md §10.4.1: level 1 read, level 2 reversible, level 3 confirm) --


def _money(amount: Decimal) -> str:
    return f"USD {amount}"


def _cart_for_model(view: CartView) -> dict[str, Any]:
    return {
        "items": [
            {
                "product_id": i.product_id,
                "name": i.name,
                "sku": i.sku,
                "quantity": i.quantity,
                "unit_price": _money(i.unit_price),
                "line_total": _money(i.line_total),
                "stock": i.available,
                "issues": i.issues,
            }
            for i in view.items
        ],
        "item_count": view.item_count,
        "total": _money(view.total),
        "can_checkout": view.can_checkout,
    }


def _cart_ids(view: CartView) -> list[str]:
    return [i.product_id for i in view.items if i.active]


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CartItemArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(description="Product ID from a previous tool result.")
    quantity: int = Field(
        description=f"Units, 1-{cart.MAX_QUANTITY_PER_ITEM}. Use 1 if the user did not say."
    )


class ProductRefArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(description="Product ID of an item in the cart.")


def _get_cart(ctx: ToolContext, _args: NoArgs) -> ToolOutcome:
    view = cart.get_cart(ctx.session, ctx.user_id)
    return ToolOutcome({"ok": True, "cart": _cart_for_model(view)}, _cart_ids(view))


def _require_seen(ctx: ToolContext, product_id: str) -> None:
    if product_id not in ctx.seen_product_ids:
        raise DomainError(
            "UNKNOWN_PRODUCT_REFERENCE",
            f"{product_id} did not come from any tool result in this conversation",
            {"hint": "Look the product up first with get_product or search_products"},
        )


def _add_to_cart(ctx: ToolContext, args: CartItemArgs) -> ToolOutcome:
    _require_seen(ctx, args.product_id)
    view = cart.add_item(ctx.session, ctx.user_id, args.product_id, args.quantity)
    data = {
        "ok": True,
        "action": "added",
        "product_id": args.product_id,
        "quantity_added": args.quantity,
        "cart": _cart_for_model(view),
    }
    return ToolOutcome(data, _cart_ids(view), ui_actions=["refresh_cart"])


def _update_cart_item(ctx: ToolContext, args: CartItemArgs) -> ToolOutcome:
    in_cart = {i.product_id for i in cart.get_cart(ctx.session, ctx.user_id).items}
    if args.product_id not in in_cart:
        _require_seen(ctx, args.product_id)  # gives the clearer error if it was made up
    view = cart.set_quantity(ctx.session, ctx.user_id, args.product_id, args.quantity)
    data = {"ok": True, "action": "updated", "cart": _cart_for_model(view)}
    return ToolOutcome(data, _cart_ids(view), ui_actions=["refresh_cart"])


def _remove_from_cart(ctx: ToolContext, args: ProductRefArgs) -> ToolOutcome:
    """Level 3: does NOT execute. The user confirms on screen."""
    view = cart.get_cart(ctx.session, ctx.user_id)
    item = next((i for i in view.items if i.product_id == args.product_id), None)
    if item is None:
        raise DomainError(
            "NOT_IN_CART", "Ese producto no está en el carrito", {"product_id": args.product_id}
        )
    summary = (
        f"¿Querés quitar {item.name} × {item.quantity} ({_money(item.line_total)}) del carrito? "
        f"El total pasaría a {_money(view.total - item.line_total)}. Confirmalo en la tarjeta."
    )
    pending = PendingAction(action="remove_item", product_id=item.product_id, summary=summary)
    data = {"ok": True, "confirmation_required": True, "action": "remove_item", "summary": summary}
    return ToolOutcome(data, [item.product_id], pending_confirmation=pending)


def _clear_cart(ctx: ToolContext, _args: NoArgs) -> ToolOutcome:
    """Level 3: does NOT execute. The user confirms on screen."""
    view = cart.get_cart(ctx.session, ctx.user_id)
    if not view.items:
        return ToolOutcome({"ok": True, "already_empty": True, "cart": _cart_for_model(view)})
    products = len(view.items)
    summary = (
        f"¿Querés vaciar el carrito? Tiene {products} "
        f"{'producto' if products == 1 else 'productos'} ({view.item_count} "
        f"{'unidad' if view.item_count == 1 else 'unidades'}) por {_money(view.total)}. "
        "Confirmalo en la tarjeta."
    )
    pending = PendingAction(action="clear_cart", product_id=None, summary=summary)
    data = {"ok": True, "confirmation_required": True, "action": "clear_cart", "summary": summary}
    return ToolOutcome(data, pending_confirmation=pending)


CART_DESCRIPTIONS = {
    "get_cart": "The user's cart now: items, quantities, CURRENT prices, stock issues, total. "
    "Use it before talking about the cart. Never describe the cart from memory.",
    "add_to_cart": "Add a product to the user's cart (sums if it is already there). ONLY when "
    "the product is unambiguous (one specific product from a tool result) and the quantity is "
    "explicit or 1. If not, ask first.",
    "update_cart_item": "Change the quantity of a product already in the cart (1 or more). "
    "To remove it, use remove_from_cart.",
    "remove_from_cart": "Ask to remove a product from the cart. It does NOT remove it: the user "
    "confirms on screen.",
    "clear_cart": "Ask to empty the cart. It does NOT empty it: the user confirms on screen.",
}


# --- Registry ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    args_model: type[BaseModel]
    describe: Callable[[Session], str]
    run: Callable[[ToolContext, Any], ToolOutcome]


TOOLS: dict[str, Tool] = {
    "search_products": Tool(
        "search_products", SearchProductsArgs, _search_description, _search_products
    ),
    "get_product": Tool(
        "get_product", GetProductArgs, lambda _session: GET_PRODUCT_DESCRIPTION, _get_product
    ),
    **{
        name: Tool(name, args, lambda _session, n=name: CART_DESCRIPTIONS[n], run)
        for name, args, run in [
            ("get_cart", NoArgs, _get_cart),
            ("add_to_cart", CartItemArgs, _add_to_cart),
            ("update_cart_item", CartItemArgs, _update_cart_item),
            ("remove_from_cart", ProductRefArgs, _remove_from_cart),
            ("clear_cart", NoArgs, _clear_cart),
        ]
    },
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

    def done(
        result: dict[str, Any],
        arguments: dict[str, Any] | None = None,
        outcome: ToolOutcome | None = None,
    ) -> ToolExecution:
        return ToolExecution(
            call=call,
            result=result,
            is_error=not result.get("ok", False),
            latency_ms=int((time.monotonic() - started) * 1000),
            arguments=arguments,
            product_ids=outcome.product_ids if outcome else [],
            ui_actions=outcome.ui_actions if outcome else [],
            pending_confirmation=outcome.pending_confirmation if outcome else None,
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
        outcome = tool.run(ctx, args)
        return done(outcome.result, raw, outcome)
    except ValidationError as error:
        return done(
            _error("INVALID_ARGUMENTS", "Invalid arguments", _validation_details(error)), raw
        )
    except DomainError as error:
        return done(error.to_dict(), raw)
